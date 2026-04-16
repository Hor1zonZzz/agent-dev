"""Shared orchestration for chat-oriented sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from core.context import AgentContext
from core.history import append_to_history, load_recent_messages
from core.loop import Agent, RunResult, run
from core.memory import RECENT_K, load_latest_summary, maybe_compress
from core.meta import (
    get_last_activity,
    update_last_activity,
    update_last_anna_message,
    update_next_proactive_at,
)
from core.proactive import compute_next_proactive
from core.time_hint import format_gap_hint
from core.trace import RunMeta, TraceRecorder, TraceSink, get_default_trace_sink


def drop_end_turn_pairs(messages: list[dict]) -> list[dict]:
    end_turn_ids: set[str] = set()
    keep: list[dict] = []
    for message in messages:
        if message.get("role") == "assistant":
            tool_calls = message.get("tool_calls") or []
            names = [(tool_call.get("function") or {}).get("name") for tool_call in tool_calls]
            if names and all(name == "end_turn" for name in names):
                for tool_call in tool_calls:
                    end_turn_ids.add(tool_call.get("id"))
                continue
        elif message.get("role") == "tool" and message.get("tool_call_id") in end_turn_ids:
            continue
        keep.append(message)
    return keep


@dataclass(frozen=True)
class ChatSessionRequest:
    history_path: Path
    incoming_messages: list[str]
    send_reply: Callable[[str], Awaitable[None]] | None
    source: str
    run_kind: str
    ctx: AgentContext | None = None
    run_id: str | None = None
    start_seq: int = 0
    session_id: str | None = None
    user_id: str | None = None
    is_proactive: bool = False
    context: dict[str, object] | None = None
    max_turns: int = 10


class ChatSessionRunner:
    def __init__(self, agent: Agent, trace_sink: TraceSink | None = None):
        self.agent = agent
        self.trace_sink = trace_sink or get_default_trace_sink()

    async def process(self, request: ChatSessionRequest) -> RunResult:
        recent = load_recent_messages(request.history_path, RECENT_K)
        memory_text = load_latest_summary()

        gap_hint: str | None = None
        if not request.is_proactive:
            last_activity = get_last_activity(request.history_path)
            gap_hint = format_gap_hint(datetime.now() - last_activity) if last_activity else None

        for index, text in enumerate(request.incoming_messages):
            content = f"{gap_hint}\n{text}" if (index == 0 and gap_hint) else text
            recent.append({"role": "user", "content": content})
        n_from_disk = len(recent) - len(request.incoming_messages)

        context = {
            "history_path": str(request.history_path),
        }
        if request.context:
            context.update(request.context)
        meta = RunMeta(
            run_kind=request.run_kind,
            source=request.source,
            run_id=request.run_id,
            session_id=request.session_id,
            user_id=request.user_id,
            start_seq=request.start_seq,
            context=context,
        )
        recorder = TraceRecorder(self.trace_sink, meta)

        ctx = request.ctx or AgentContext()
        ctx.send_reply = request.send_reply
        ctx.memory = memory_text
        ctx.last_user_input = request.incoming_messages[-1] if request.incoming_messages else ""
        ctx.trace_recorder = recorder

        result = await run(
            self.agent,
            recent,
            ctx=ctx,
            max_turns=request.max_turns,
            trace_sink=self.trace_sink,
            run_meta=RunMeta(
                run_kind=request.run_kind,
                source=request.source,
                run_id=recorder.run_id,
                session_id=request.session_id,
                user_id=request.user_id,
                start_seq=recorder.seq,
                context=context,
            ),
        )

        recorder.sync(result.trace_seq)
        new_this_turn = result.messages[1 + n_from_disk:]
        if request.is_proactive and new_this_turn and new_this_turn[0].get("role") == "user":
            new_this_turn = new_this_turn[1:]
        elif gap_hint and new_this_turn and new_this_turn[0].get("role") == "user":
            new_this_turn[0] = {**new_this_turn[0], "content": request.incoming_messages[0]}

        new_this_turn = drop_end_turn_pairs(new_this_turn)
        append_to_history(request.history_path, new_this_turn)
        await recorder.emit(
            lane="artifact",
            type="artifact.written",
            status="ok",
            summary=f"history appended: {request.history_path.name}",
            payload={
                "artifact_kind": "history",
                "path": str(request.history_path),
                "message_count": len(new_this_turn),
            },
        )

        if not request.is_proactive:
            update_last_activity(request.history_path)

        now = datetime.now()
        update_last_anna_message(request.history_path, now)
        update_next_proactive_at(request.history_path, compute_next_proactive(now))

        await maybe_compress(request.history_path, trace_sink=self.trace_sink)

        result.run_id = recorder.run_id
        result.trace_seq = recorder.seq
        return result
