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


def format_ts(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")


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
    return dict(sorted(counts.items()))


def tool_count(events: list[TraceEvent]) -> int:
    return sum(1 for event in events if event.type == "tool.finished")


def artifact_count(events: list[TraceEvent]) -> int:
    return sum(
        1
        for event in events
        if event.lane == "artifact" and "path" in event.payload
    )


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
    for summary in summaries:
        run = repo.get_run(summary.run_id)
        if run is None:
            continue

        item = _base_run_view(run)
        item["summary"] = summary.summary
        item["lane_counts"] = lane_counts(run.events)
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
        "runs": items,
        "count": len(items),
        "empty": len(items) == 0,
    }


def _event_view(event: TraceEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts,
        "ts_label": format_ts(event.ts),
        "lane": event.lane,
        "lane_color": LANE_COLORS.get(event.lane, "#64748b"),
        "type": event.type,
        "status": event.status,
        "summary": event.summary,
        "payload": event.payload,
        "raw_events": [event.to_dict()],
        "event_count": 1,
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
    return {
        "seq": first.seq,
        "ts": first.ts,
        "ts_label": format_ts(first.ts),
        "lane": lane,
        "lane_color": LANE_COLORS.get(lane, "#64748b"),
        "type": title,
        "status": status,
        "summary": summary,
        "payload": payload,
        "raw_events": [event.to_dict() for event in events],
        "event_count": len(events),
    }


def _timeline_items(events: list[TraceEvent]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    index = 0

    while index < len(events):
        current = events[index]
        nxt = events[index + 1] if index + 1 < len(events) else None

        if (
            current.type == "llm.requested"
            and nxt is not None
            and nxt.type == "llm.responded"
            and nxt.lane == "llm"
        ):
            items.append(
                _paired_item(
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
            )
            index += 2
            continue

        if (
            current.type == "tool.started"
            and nxt is not None
            and nxt.type == "tool.finished"
            and nxt.payload.get("tool_name") == current.payload.get("tool_name")
        ):
            tool_name = current.payload.get("tool_name", "tool")
            items.append(
                _paired_item(
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
            )
            index += 2
            continue

        items.append(_event_view(current))
        index += 1

    return items


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
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(history_root.resolve())),
        "artifact_kind": artifact_kind,
        "content_preview": preview,
        "full_content": content,
        "truncated": truncated,
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
            "lane": event.lane,
            "type": event.type,
            "summary": event.summary,
            "payload": event.payload,
        }
        for event in run.events
        if event.status == "error"
    ]

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
            "tool_count": tool_count(run.events),
            "artifact_count": artifact_count(run.events),
            "first_error": first_error(run.events),
        },
        "summary": {
            "lane_counts": lane_counts(run.events),
            "tool_count": tool_count(run.events),
            "artifact_count": artifact_count(run.events),
            "first_error": first_error(run.events),
        },
        "timeline": _timeline_items(run.events),
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
