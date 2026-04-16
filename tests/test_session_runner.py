from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from unittest.mock import AsyncMock

import core.session as session_mod
from core.context import AgentContext
from core.loop import Agent, RunResult
from core.meta import load_meta, update_last_activity
from core.session import ChatSessionRequest, ChatSessionRunner


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def _make_result(messages: list[dict], *, run_id: str = "run_cli", trace_seq: int = 5) -> RunResult:
    return RunResult(
        messages=[{"role": "system", "content": "sys"}] + messages,
        final_output="done",
        last_tool=None,
        run_id=run_id,
        trace_seq=trace_seq,
    )


def test_runner_strips_gap_hint_and_updates_meta(tmp_path, monkeypatch):
    history_path = tmp_path / "chat.json"
    sink = ListSink()
    runner = ChatSessionRunner(Agent(name="anna", instructions="sys", model="gpt"), trace_sink=sink)
    monkeypatch.setattr(session_mod, "maybe_compress", AsyncMock(return_value=None))

    captured = {}

    async def fake_run(agent, input, *, ctx, max_turns, trace_sink, run_meta):
        captured["input"] = list(input)
        return _make_result(input + [{"role": "assistant", "content": "done"}], run_id=run_meta.run_id, trace_seq=7)

    monkeypatch.setattr(session_mod, "run", fake_run)
    update_last_activity(history_path, datetime.now() - timedelta(hours=3))

    asyncio.run(
        runner.process(
            ChatSessionRequest(
                history_path=history_path,
                incoming_messages=["hello"],
                send_reply=None,
                source="cli",
                run_kind="cli_chat",
                session_id="cli",
            )
        )
    )

    assert captured["input"][0]["content"].startswith("[距上次说话")
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["content"] == "hello"
    assert persisted[1]["content"] == "done"

    meta = load_meta(history_path)
    assert meta.get("last_activity_at")
    assert meta.get("last_anna_message_at")
    assert meta.get("next_proactive_at")
    assert any(event.type == "artifact.written" for event in sink.events)


def test_runner_drops_proactive_synthetic_message(tmp_path, monkeypatch):
    history_path = tmp_path / "chat.json"
    sink = ListSink()
    runner = ChatSessionRunner(Agent(name="anna", instructions="sys", model="gpt"), trace_sink=sink)
    monkeypatch.setattr(session_mod, "maybe_compress", AsyncMock(return_value=None))

    async def fake_run(agent, input, *, ctx, max_turns, trace_sink, run_meta):
        return _make_result(input + [{"role": "assistant", "content": "nudge"}], run_id=run_meta.run_id, trace_seq=6)

    monkeypatch.setattr(session_mod, "run", fake_run)

    asyncio.run(
        runner.process(
            ChatSessionRequest(
                history_path=history_path,
                incoming_messages=["[系统提示·主动触发]"],
                send_reply=None,
                source="wechat",
                run_kind="wechat_proactive",
                session_id="u1",
                user_id="u1",
                is_proactive=True,
            )
        )
    )

    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted == [{"role": "assistant", "content": "nudge"}]


def test_runner_uses_external_context(tmp_path, monkeypatch):
    history_path = tmp_path / "chat.json"
    sink = ListSink()
    runner = ChatSessionRunner(Agent(name="anna", instructions="sys", model="gpt"), trace_sink=sink)
    monkeypatch.setattr(session_mod, "maybe_compress", AsyncMock(return_value=None))

    external_ctx = AgentContext()
    captured = {}

    async def fake_run(agent, input, *, ctx, max_turns, trace_sink, run_meta):
        captured["ctx"] = ctx
        return _make_result(input + [{"role": "assistant", "content": "done"}], run_id=run_meta.run_id, trace_seq=4)

    monkeypatch.setattr(session_mod, "run", fake_run)

    asyncio.run(
        runner.process(
            ChatSessionRequest(
                history_path=history_path,
                incoming_messages=["hello"],
                send_reply=None,
                source="wechat",
                run_kind="wechat_chat",
                ctx=external_ctx,
                run_id="run_shared",
                start_seq=2,
                session_id="u1",
                user_id="u1",
            )
        )
    )

    assert captured["ctx"] is external_ctx
    assert external_ctx.trace_recorder is not None
    assert external_ctx.trace_recorder.run_id == "run_shared"
