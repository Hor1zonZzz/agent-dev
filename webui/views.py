"""View-model helpers for the trace WebUI."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.trace import TraceEvent, TraceRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_ROOT = PROJECT_ROOT / "history"
ARTIFACT_PREVIEW_CHARS = int(os.getenv("TRACE_WEB_PREVIEW_CHARS", "4000"))
STREAM_POLL_SECONDS = float(os.getenv("TRACE_WEB_POLL_SECONDS", "1.0"))
LIST_SCAN_LIMIT = int(os.getenv("TRACE_WEB_SCAN_LIMIT", "500"))

LANE_COLORS = {
    "dispatch": "#3b82f6",
    "runtime": "#64748b",
    "llm": "#0891b2",
    "tool": "#ea580c",
    "scheduler": "#7c3aed",
    "memory": "#16a34a",
    "artifact": "#ca8a04",
}

LANE_ORDER = ["dispatch", "runtime", "llm", "tool", "scheduler", "memory", "artifact"]

TERMINAL_TYPES = {
    "run.finished",
    "run.failed",
    "run.max_turns_hit",
    "schedule.finished",
    "memory.compression_finished",
    "memory.compression_failed",
}


def format_ts(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")


def format_ts_short(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value).strftime("%H:%M:%S.%f")[:-3]


def duration_ms(started_at: str, finished_at: str | None) -> int:
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(finished_at) if finished_at else datetime.now()
    return max(0, int((end - start).total_seconds() * 1000))


def format_duration(value_ms: int) -> str:
    if value_ms < 1000:
        return f"{value_ms}ms"
    seconds = value_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def first_error(events: list[TraceEvent]) -> dict[str, Any] | None:
    for event in events:
        if event.status == "error":
            return {
                "seq": event.seq,
                "ts": event.ts,
                "ts_label": format_ts(event.ts),
                "lane": event.lane,
                "type": event.type,
                "summary": event.summary,
                "payload": event.payload,
            }
    return None


def lane_counts(events: list[TraceEvent]) -> dict[str, int]:
    counts = Counter(event.lane for event in events)
    return {lane: counts[lane] for lane in LANE_ORDER if lane in counts}


def lane_distribution(events: list[TraceEvent]) -> list[dict[str, Any]]:
    counts = lane_counts(events)
    total = sum(counts.values()) or 1
    return [
        {
            "lane": lane,
            "count": count,
            "pct": round(count / total * 100, 2),
            "color": LANE_COLORS.get(lane, "#64748b"),
        }
        for lane, count in counts.items()
    ]


def tool_count(events: list[TraceEvent]) -> int:
    return sum(1 for event in events if event.type == "tool.finished")


def artifact_count(events: list[TraceEvent]) -> int:
    return sum(
        1
        for event in events
        if event.lane == "artifact" and "path" in event.payload
    )


def turn_count(events: list[TraceEvent]) -> int:
    return sum(1 for event in events if event.type == "turn.started")


def _is_running(events: list[TraceEvent]) -> bool:
    if not events:
        return False
    return not any(event.type in TERMINAL_TYPES for event in events)


def _base_run_view(run) -> dict[str, Any]:
    ms = duration_ms(run.started_at, run.finished_at)
    return {
        "run_id": run.run_id,
        "run_kind": run.run_kind,
        "source": run.source,
        "session_id": run.session_id,
        "started_at": run.started_at,
        "started_at_label": format_ts(run.started_at),
        "finished_at": run.finished_at,
        "finished_at_label": format_ts(run.finished_at),
        "status": run.status,
        "event_count": len(run.events),
        "duration_ms": ms,
        "duration_label": format_duration(ms),
        "is_running": _is_running(run.events),
        "turn_count": turn_count(run.events),
    }


def build_runs_payload(
    repo: TraceRepository,
    *,
    limit: int,
    day: str | None = None,
    run_kind: str | None = None,
    source: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    scan_limit = max(limit, LIST_SCAN_LIMIT)
    summaries = repo.list_runs(
        limit=scan_limit,
        run_kind=run_kind,
        source=source,
        session_id=session_id,
        day=day,
    )

    items: list[dict[str, Any]] = []
    observed_run_kinds: set[str] = set()
    observed_sources: set[str] = set()
    observed_statuses: set[str] = set()

    for summary in summaries:
        run = repo.get_run(summary.run_id)
        if run is None:
            continue
        observed_run_kinds.add(run.run_kind)
        observed_sources.add(run.source)
        observed_statuses.add(run.status)

        item = _base_run_view(run)
        item["summary"] = summary.summary
        item["lane_counts"] = lane_counts(run.events)
        item["lane_distribution"] = lane_distribution(run.events)
        item["tool_count"] = tool_count(run.events)
        item["artifact_count"] = artifact_count(run.events)
        item["first_error"] = first_error(run.events)

        if status and item["status"] != status:
            continue

        items.append(item)
        if len(items) >= limit:
            break

    return {
        "filters": {
            "limit": limit,
            "day": day or "",
            "run_kind": run_kind or "",
            "source": source or "",
            "session_id": session_id or "",
            "status": status or "",
        },
        "options": {
            "run_kinds": sorted(observed_run_kinds),
            "sources": sorted(observed_sources),
            "statuses": sorted(observed_statuses),
        },
        "runs": items,
        "count": len(items),
        "empty": len(items) == 0,
    }


def _extract_turn(type_: str, payload: dict[str, Any]) -> int | None:
    turn = payload.get("turn")
    if isinstance(turn, int):
        return turn
    request = payload.get("request")
    if isinstance(request, dict) and isinstance(request.get("turn"), int):
        return request["turn"]
    start = payload.get("start")
    if isinstance(start, dict) and isinstance(start.get("turn"), int):
        return start["turn"]
    return None


def _surface_fields(lane: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    if type_ == "llm.exchange":
        req = payload.get("request") or {}
        res = payload.get("response") or {}
        return {
            "kind": "llm_exchange",
            "turn": req.get("turn") or res.get("turn"),
            "message_count": req.get("message_count"),
            "tool_count": req.get("tool_count"),
            "last_message_role": req.get("last_message_role"),
            "last_message_preview": req.get("last_message_preview"),
            "content_preview": res.get("content_preview"),
            "reasoning_preview": res.get("reasoning_preview"),
            "tool_call_names": res.get("tool_call_names") or [],
            "tool_call_count": res.get("tool_call_count") or 0,
        }
    if type_.startswith("tool."):
        start = payload.get("start") if isinstance(payload.get("start"), dict) else payload
        finish = payload.get("finish") if isinstance(payload.get("finish"), dict) else {}
        return {
            "kind": "tool",
            "tool_name": start.get("tool_name") or finish.get("tool_name"),
            "arguments_preview": start.get("arguments_preview"),
            "arguments": start.get("arguments"),
            "result_preview": finish.get("result_preview") or payload.get("result_preview"),
            "error_message": finish.get("error_message") or payload.get("error_message"),
        }
    if type_ == "llm.requested":
        return {
            "kind": "llm_request",
            "turn": payload.get("turn"),
            "message_count": payload.get("message_count"),
            "tool_count": payload.get("tool_count"),
            "last_message_role": payload.get("last_message_role"),
            "last_message_preview": payload.get("last_message_preview"),
        }
    if type_ == "llm.responded":
        return {
            "kind": "llm_response",
            "turn": payload.get("turn"),
            "content_preview": payload.get("content_preview"),
            "reasoning_preview": payload.get("reasoning_preview"),
            "tool_call_names": payload.get("tool_call_names") or [],
            "tool_call_count": payload.get("tool_call_count") or 0,
        }
    if lane == "artifact":
        return {
            "kind": "artifact",
            "artifact_kind": payload.get("artifact_kind"),
            "path": payload.get("path"),
        }
    if lane == "memory":
        return {
            "kind": "memory",
            "event_count": payload.get("event_count"),
            "turn_count": payload.get("turn_count"),
            "error_message": payload.get("error_message"),
        }
    if lane == "dispatch":
        return {
            "kind": "dispatch",
            "message_count": payload.get("message_count"),
            "preview": payload.get("first_preview") or payload.get("preview"),
            "inbox_size": payload.get("inbox_size"),
            "session_id": payload.get("session_id"),
        }
    if lane == "runtime":
        return {
            "kind": "runtime",
            "agent_name": payload.get("agent_name"),
            "model": payload.get("model"),
            "tool_names": payload.get("tool_names") or [],
            "turn": payload.get("turn"),
            "final_output_preview": payload.get("final_output_preview"),
            "error_type": payload.get("error_type"),
            "error_message": payload.get("error_message"),
            "previews": payload.get("previews") or [],
            "count": payload.get("count"),
        }
    return {"kind": "generic"}


def _event_view(event: TraceEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts,
        "ts_label": format_ts(event.ts),
        "ts_short": format_ts_short(event.ts),
        "lane": event.lane,
        "lane_color": LANE_COLORS.get(event.lane, "#64748b"),
        "type": event.type,
        "status": event.status,
        "summary": event.summary,
        "payload": event.payload,
        "raw_events": [event.to_dict()],
        "event_count": 1,
        "turn": _extract_turn(event.type, event.payload),
        "surface": _surface_fields(event.lane, event.type, event.payload),
    }


def _paired_item(
    *,
    title: str,
    lane: str,
    status: str,
    summary: str,
    events: list[TraceEvent],
    payload: dict[str, Any],
) -> dict[str, Any]:
    first = events[0]
    last = events[-1]
    pair_ms = duration_ms(first.ts, last.ts)
    return {
        "seq": first.seq,
        "ts": first.ts,
        "ts_label": format_ts(first.ts),
        "ts_short": format_ts_short(first.ts),
        "lane": lane,
        "lane_color": LANE_COLORS.get(lane, "#64748b"),
        "type": title,
        "status": status,
        "summary": summary,
        "payload": payload,
        "raw_events": [event.to_dict() for event in events],
        "event_count": len(events),
        "turn": _extract_turn(title, payload),
        "surface": _surface_fields(lane, title, payload),
        "pair_duration_ms": pair_ms,
        "pair_duration_label": format_duration(pair_ms),
    }


def _timeline_items(events: list[TraceEvent]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current_turn: int | None = None
    index = 0

    while index < len(events):
        current = events[index]
        nxt = events[index + 1] if index + 1 < len(events) else None

        candidate_turn = _extract_turn(current.type, current.payload)
        if candidate_turn is not None:
            current_turn = candidate_turn

        if (
            current.type == "llm.requested"
            and nxt is not None
            and nxt.type == "llm.responded"
            and nxt.lane == "llm"
        ):
            item = _paired_item(
                title="llm.exchange",
                lane="llm",
                status="error" if "error" in {current.status, nxt.status} else nxt.status,
                summary=nxt.summary,
                events=[current, nxt],
                payload={
                    "request": current.payload,
                    "response": nxt.payload,
                },
            )
            if item["turn"] is None:
                item["turn"] = current_turn
            items.append(item)
            index += 2
            continue

        if (
            current.type == "tool.started"
            and nxt is not None
            and nxt.type == "tool.finished"
            and nxt.payload.get("tool_name") == current.payload.get("tool_name")
        ):
            tool_name = current.payload.get("tool_name", "tool")
            item = _paired_item(
                title=f"tool.{tool_name}",
                lane="tool",
                status=nxt.status,
                summary=nxt.summary,
                events=[current, nxt],
                payload={
                    "start": current.payload,
                    "finish": nxt.payload,
                },
            )
            if item["turn"] is None:
                item["turn"] = current_turn
            items.append(item)
            index += 2
            continue

        item = _event_view(current)
        if item["turn"] is None:
            item["turn"] = current_turn
        items.append(item)
        index += 1

    return items


def _annotate_offsets(
    items: list[dict[str, Any]],
    *,
    started_at: str,
    finished_at: str | None,
) -> None:
    if not items:
        return
    total_ms = duration_ms(started_at, finished_at)
    for item in items:
        offset_ms = duration_ms(started_at, item["ts"])
        item["offset_ms"] = offset_ms
        item["offset_pct"] = (
            0.0 if total_ms == 0 else round(min(100.0, offset_ms / total_ms * 100), 2)
        )
        if item.get("pair_duration_ms"):
            item["pair_width_pct"] = (
                0.0
                if total_ms == 0
                else round(min(100.0, item["pair_duration_ms"] / total_ms * 100), 2)
            )
        else:
            item["pair_width_pct"] = 0.0


def _infer_artifact_kind(relative_path: Path) -> str | None:
    if not relative_path.parts:
        return None
    head = relative_path.parts[0]
    if head == "plans":
        return "plan"
    if head == "diary":
        return "diary"
    if head in {"anna", "user", "shared"}:
        return "memory_summary"
    if head == "wechat" or relative_path.name == "cli.json":
        return "history"
    return None


def resolve_artifact_path(raw_path: str, history_root: Path = DEFAULT_HISTORY_ROOT) -> tuple[Path, str]:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    resolved = candidate.resolve()
    history_resolved = history_root.resolve()
    if resolved != history_resolved and history_resolved not in resolved.parents:
        raise PermissionError("artifact path must stay under history/")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))

    relative = resolved.relative_to(history_resolved)
    artifact_kind = _infer_artifact_kind(relative)
    if artifact_kind is None:
        raise PermissionError("unsupported artifact path")
    return resolved, artifact_kind


def build_artifact_preview(raw_path: str, history_root: Path = DEFAULT_HISTORY_ROOT) -> dict[str, Any]:
    path, artifact_kind = resolve_artifact_path(raw_path, history_root)
    content = path.read_text(encoding="utf-8", errors="replace")
    preview = content[:ARTIFACT_PREVIEW_CHARS]
    truncated = len(content) > ARTIFACT_PREVIEW_CHARS
    line_count = content.count("\n") + (0 if content.endswith("\n") or content == "" else 1)
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(history_root.resolve())),
        "artifact_kind": artifact_kind,
        "content_preview": preview,
        "full_content": content,
        "truncated": truncated,
        "char_count": len(content),
        "line_count": line_count,
    }


def _narrative(run, events: list[TraceEvent]) -> dict[str, Any]:
    tool_names: Counter[str] = Counter()
    final_output: str | None = None
    last_tool: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    error_turn: int | None = None
    for event in events:
        if event.type == "tool.finished" and event.status == "ok":
            name = event.payload.get("tool_name")
            if name:
                tool_names[name] += 1
                last_tool = name
        if event.type == "run.finished":
            final_output = event.payload.get("final_output_preview") or final_output
            last_tool = event.payload.get("last_tool") or last_tool
        if event.status == "error" and error_message is None:
            error_type = event.payload.get("error_type")
            error_message = event.payload.get("error_message") or event.summary
            error_turn = event.payload.get("turn") if isinstance(event.payload.get("turn"), int) else None

    tool_calls_total = sum(tool_names.values())
    top_tool: str | None = None
    top_tool_share: float = 0.0
    if tool_calls_total:
        most = tool_names.most_common(1)[0]
        top_tool = most[0]
        top_tool_share = most[1] / tool_calls_total
    distinct_tools = list(tool_names.keys())

    has_dispatch_only = all(event.lane == "dispatch" for event in events)
    return {
        "tool_calls_total": tool_calls_total,
        "top_tool": top_tool,
        "top_tool_dominant": top_tool_share >= 0.5 and len(distinct_tools) > 1,
        "distinct_tools": distinct_tools,
        "last_tool": last_tool,
        "final_output_preview": final_output,
        "error_type": error_type,
        "error_message": error_message,
        "error_turn": error_turn,
        "dispatch_only": has_dispatch_only,
    }


def build_run_detail_payload(
    repo: TraceRepository,
    run_id: str,
    *,
    history_root: Path = DEFAULT_HISTORY_ROOT,
) -> dict[str, Any] | None:
    run = repo.get_run(run_id)
    if run is None:
        return None

    base = _base_run_view(run)
    errors = [
        {
            "seq": event.seq,
            "ts_label": format_ts(event.ts),
            "ts_short": format_ts_short(event.ts),
            "lane": event.lane,
            "type": event.type,
            "summary": event.summary,
            "payload": event.payload,
        }
        for event in run.events
        if event.status == "error"
    ]

    timeline = _timeline_items(run.events)
    _annotate_offsets(timeline, started_at=run.started_at, finished_at=run.finished_at)

    ruler_markers = [
        {
            "seq": item["seq"],
            "offset_pct": item["offset_pct"],
            "width_pct": max(item.get("pair_width_pct") or 0.0, 0.4),
            "lane": item["lane"],
            "status": item["status"],
            "ts_short": item["ts_short"],
            "type": item["type"],
        }
        for item in timeline
    ]

    turn_ids = sorted({item["turn"] for item in timeline if isinstance(item["turn"], int)})
    lane_ids = sorted({item["lane"] for item in timeline})

    artifacts_by_path: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for event in run.events:
        raw_path = event.payload.get("path")
        if not raw_path:
            continue
        record = artifacts_by_path.setdefault(
            raw_path,
            {
                "path": raw_path,
                "artifact_kind": event.payload.get("artifact_kind"),
                "event_types": [],
            },
        )
        record["event_types"].append(event.type)
        try:
            path, artifact_kind = resolve_artifact_path(raw_path, history_root)
            record["artifact_kind"] = record["artifact_kind"] or artifact_kind
            record["relative_path"] = str(path.relative_to(history_root.resolve()))
        except (FileNotFoundError, PermissionError):
            record["relative_path"] = raw_path
        record["preview_url"] = f"/artifacts/preview?path={quote(raw_path, safe='')}"

    return {
        "run": {
            **base,
            "lane_counts": lane_counts(run.events),
            "lane_distribution": lane_distribution(run.events),
            "tool_count": tool_count(run.events),
            "artifact_count": artifact_count(run.events),
            "first_error": first_error(run.events),
        },
        "summary": {
            "lane_counts": lane_counts(run.events),
            "lane_distribution": lane_distribution(run.events),
            "tool_count": tool_count(run.events),
            "artifact_count": artifact_count(run.events),
            "first_error": first_error(run.events),
        },
        "narrative": _narrative(run, run.events),
        "timeline": timeline,
        "ruler": ruler_markers,
        "facets": {
            "turns": turn_ids,
            "lanes": lane_ids,
        },
        "artifacts": list(artifacts_by_path.values()),
        "errors": errors,
        "raw_events": [event.to_dict() for event in run.events],
    }


async def stream_run_summaries(
    repo: TraceRepository,
    *,
    limit: int,
    day: str | None = None,
    run_kind: str | None = None,
    source: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    poll_seconds: float = STREAM_POLL_SECONDS,
):
    initial = build_runs_payload(
        repo,
        limit=limit,
        day=day,
        run_kind=run_kind,
        source=source,
        session_id=session_id,
        status=status,
    )
    known = {
        run["run_id"]: (run["status"], run["event_count"], run["summary"])
        for run in initial["runs"]
    }
    while True:
        payload = build_runs_payload(
            repo,
            limit=limit,
            day=day,
            run_kind=run_kind,
            source=source,
            session_id=session_id,
            status=status,
        )
        current: dict[str, tuple[str, int, str]] = {}
        for run in payload["runs"]:
            signature = (run["status"], run["event_count"], run["summary"])
            current[run["run_id"]] = signature
            if known.get(run["run_id"]) != signature:
                yield {
                    "event": "run_update",
                    "data": json.dumps(
                        {
                            "run_id": run["run_id"],
                            "status": run["status"],
                            "event_count": run["event_count"],
                            "summary": run["summary"],
                        },
                        ensure_ascii=False,
                    ),
                }
        known = current
        await asyncio.sleep(poll_seconds)


async def stream_run_events(
    repo: TraceRepository,
    run_id: str,
    *,
    poll_seconds: float = STREAM_POLL_SECONDS,
):
    run = repo.get_run(run_id)
    last_seq = run.events[-1].seq if run and run.events else 0
    while True:
        run = repo.get_run(run_id)
        if run is not None:
            new_events = [event for event in run.events if event.seq > last_seq]
            for event in new_events:
                last_seq = max(last_seq, event.seq)
                yield {
                    "event": "run_event",
                    "data": json.dumps(_event_view(event), ensure_ascii=False),
                }
        await asyncio.sleep(poll_seconds)
