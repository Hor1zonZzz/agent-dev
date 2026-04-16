"""Structured execution traces for runtime observability."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


TRACE_ENABLED = os.getenv("TRACE_ENABLED", "1").lower() not in {"0", "false", "no"}
TRACE_DIR = _resolve_env_path("TRACE_DIR", PROJECT_ROOT / "history" / "traces")
TRACE_MAX_PREVIEW_CHARS = int(os.getenv("TRACE_MAX_PREVIEW_CHARS", "200"))

RUN_KINDS = {
    "cli_chat",
    "wechat_chat",
    "wechat_proactive",
    "planner",
    "hermes_task",
    "hermes_slot",
    "memory_compress",
}
LANES = {
    "dispatch",
    "runtime",
    "llm",
    "tool",
    "scheduler",
    "memory",
    "artifact",
}
STATUSES = {"ok", "error", "skipped", "info"}


def new_trace_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def truncate_preview(value: Any, limit: int = TRACE_MAX_PREVIEW_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    run_id: str
    seq: int
    ts: str
    run_kind: str
    source: str
    lane: str
    type: str
    status: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.run_kind not in RUN_KINDS:
            raise ValueError(f"unsupported run_kind: {self.run_kind}")
        if self.lane not in LANES:
            raise ValueError(f"unsupported lane: {self.lane}")
        if self.status not in STATUSES:
            raise ValueError(f"unsupported status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.ts,
            "run_kind": self.run_kind,
            "source": self.source,
            "lane": self.lane,
            "type": self.type,
            "status": self.status,
            "summary": self.summary,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TraceEvent":
        return cls(
            event_id=str(raw["event_id"]),
            run_id=str(raw["run_id"]),
            seq=int(raw["seq"]),
            ts=str(raw["ts"]),
            run_kind=str(raw["run_kind"]),
            source=str(raw["source"]),
            lane=str(raw["lane"]),
            type=str(raw["type"]),
            status=str(raw["status"]),
            summary=str(raw["summary"]),
            payload=dict(raw.get("payload") or {}),
        )


@dataclass(frozen=True)
class RunMeta:
    run_kind: str
    source: str
    run_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    start_seq: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def payload_base(self) -> dict[str, Any]:
        payload = dict(self.context)
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.user_id is not None:
            payload["user_id"] = self.user_id
        return payload


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None | Any: ...


def _combine_payload(base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(base)
    if extra:
        payload.update(extra)
    return payload


async def emit_trace_event(sink: TraceSink | None, event: TraceEvent) -> None:
    if sink is None:
        return
    result = sink.emit(event)
    if inspect.isawaitable(result):
        await result


def emit_trace_event_sync(sink: TraceSink | None, event: TraceEvent) -> None:
    if sink is None:
        return
    result = sink.emit(event)
    if inspect.isawaitable(result):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(result)
        else:
            raise RuntimeError("cannot synchronously emit an awaitable trace inside a running loop")


class NullTraceSink:
    def emit(self, event: TraceEvent) -> None:
        return None


class FanoutTraceSink:
    def __init__(self, sinks: list[TraceSink]):
        self.sinks = sinks

    def emit(self, event: TraceEvent) -> None | Any:
        pending: list[Any] = []
        for sink in self.sinks:
            result = sink.emit(event)
            if inspect.isawaitable(result):
                pending.append(result)
        if not pending:
            return None

        async def _await_all() -> None:
            for item in pending:
                await item

        return _await_all()


class NdjsonTraceSink:
    def __init__(self, trace_dir: Path | None = None):
        self.trace_dir = trace_dir or TRACE_DIR
        self._lock = threading.Lock()

    def _path_for(self, ts: str) -> Path:
        day = datetime.fromisoformat(ts).date().isoformat()
        return self.trace_dir / f"{day}.ndjson"

    def emit(self, event: TraceEvent) -> None:
        path = self._path_for(event.ts)
        line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)


class LoggerTraceSink:
    def emit(self, event: TraceEvent) -> None:
        logger.debug(
            "[trace] {} {} {} {} {}",
            event.run_id,
            event.seq,
            event.lane,
            event.type,
            event.summary,
        )


class TraceRecorder:
    def __init__(self, sink: TraceSink | None, meta: RunMeta):
        self.sink = sink
        self.meta = meta
        self.run_id = meta.run_id or new_trace_id("run")
        self.seq = meta.start_seq
        self._base_payload = meta.payload_base()

    def sync(self, seq: int) -> None:
        self.seq = seq

    def build_event(
        self,
        *,
        lane: str,
        type: str,
        status: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> TraceEvent:
        self.seq += 1
        return TraceEvent(
            event_id=new_trace_id("evt"),
            run_id=self.run_id,
            seq=self.seq,
            ts=datetime.now().isoformat(timespec="milliseconds"),
            run_kind=self.meta.run_kind,
            source=self.meta.source,
            lane=lane,
            type=type,
            status=status,
            summary=summary,
            payload=_combine_payload(self._base_payload, payload),
        )

    async def emit(
        self,
        *,
        lane: str,
        type: str,
        status: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = self.build_event(
            lane=lane,
            type=type,
            status=status,
            summary=summary,
            payload=payload,
        )
        await emit_trace_event(self.sink, event)
        return event

    def emit_sync(
        self,
        *,
        lane: str,
        type: str,
        status: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = self.build_event(
            lane=lane,
            type=type,
            status=status,
            summary=summary,
            payload=payload,
        )
        emit_trace_event_sync(self.sink, event)
        return event


@lru_cache(maxsize=1)
def get_default_trace_sink() -> TraceSink:
    if not TRACE_ENABLED:
        return NullTraceSink()
    return NdjsonTraceSink()


def reset_default_trace_sink() -> None:
    get_default_trace_sink.cache_clear()


@dataclass(frozen=True)
class TraceRunSummary:
    run_id: str
    run_kind: str
    source: str
    session_id: str | None
    started_at: str
    finished_at: str | None
    status: str
    event_count: int
    summary: str


@dataclass(frozen=True)
class TraceRun:
    run_id: str
    run_kind: str
    source: str
    session_id: str | None
    started_at: str
    finished_at: str | None
    status: str
    events: list[TraceEvent]


class TraceRepository:
    def __init__(self, trace_dir: Path | None = None):
        self.trace_dir = trace_dir or TRACE_DIR

    def _paths(self, day: str | date | None = None) -> list[Path]:
        if day is not None:
            day_str = day.isoformat() if isinstance(day, date) else str(day)
            path = self.trace_dir / f"{day_str}.ndjson"
            return [path] if path.exists() else []
        return sorted(self.trace_dir.glob("*.ndjson"))

    def _iter_events(self, day: str | date | None = None) -> list[TraceEvent]:
        events: list[TraceEvent] = []
        for path in self._paths(day):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                raw = json.loads(line)
                events.append(TraceEvent.from_dict(raw))
        return events

    def _group_runs(self, day: str | date | None = None) -> OrderedDict[str, list[TraceEvent]]:
        grouped: OrderedDict[str, list[TraceEvent]] = OrderedDict()
        for event in self._iter_events(day):
            grouped.setdefault(event.run_id, []).append(event)
        for run_events in grouped.values():
            run_events.sort(key=lambda event: (event.ts, event.seq))
        return grouped

    @staticmethod
    def _session_id(events: list[TraceEvent]) -> str | None:
        for event in events:
            session_id = event.payload.get("session_id")
            if session_id is not None:
                return str(session_id)
        return None

    @staticmethod
    def _status(events: list[TraceEvent]) -> str:
        for event in reversed(events):
            if event.type in {"run.failed", "memory.compression_failed"}:
                return "error"
            if event.type in {"run.finished", "schedule.finished", "memory.compression_finished"}:
                return event.status
        return events[-1].status if events else "info"

    def list_runs(
        self,
        limit: int,
        run_kind: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        day: str | date | None = None,
    ) -> list[TraceRunSummary]:
        summaries: list[TraceRunSummary] = []
        for _, events in self._group_runs(day).items():
            if not events:
                continue
            first = events[0]
            current_session_id = self._session_id(events)
            if run_kind is not None and first.run_kind != run_kind:
                continue
            if source is not None and first.source != source:
                continue
            if session_id is not None and current_session_id != session_id:
                continue
            summaries.append(
                TraceRunSummary(
                    run_id=first.run_id,
                    run_kind=first.run_kind,
                    source=first.source,
                    session_id=current_session_id,
                    started_at=first.ts,
                    finished_at=events[-1].ts,
                    status=self._status(events),
                    event_count=len(events),
                    summary=events[-1].summary,
                )
            )
        summaries.sort(key=lambda item: item.started_at, reverse=True)
        return summaries[:limit]

    def get_run(self, run_id: str) -> TraceRun | None:
        events: list[TraceEvent] = []
        for event in self._iter_events():
            if event.run_id == run_id:
                events.append(event)
        if not events:
            return None
        events.sort(key=lambda event: (event.ts, event.seq))
        first = events[0]
        return TraceRun(
            run_id=run_id,
            run_kind=first.run_kind,
            source=first.source,
            session_id=self._session_id(events),
            started_at=first.ts,
            finished_at=events[-1].ts,
            status=self._status(events),
            events=events,
        )
