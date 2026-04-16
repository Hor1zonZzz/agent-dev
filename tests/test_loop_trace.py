from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import core.loop as loop_mod
from core.context import AgentContext
from core.loop import Agent, run
from core.tool import Tool
from core.trace import RunMeta


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class DummyParams(BaseModel):
    value: str = ""


class FakeMessage:
    def __init__(self, *, content: str | None = None, tool_calls=None, reasoning_content: str | None = None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content

    def model_dump(self, exclude_none: bool = True):
        payload = {"role": "assistant"}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in self.tool_calls
            ]
        if self.reasoning_content is not None:
            payload["reasoning_content"] = self.reasoning_content
        return payload


class FakeToolCall:
    def __init__(self, name: str, arguments: str, call_id: str):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


def _install_client(monkeypatch, messages):
    queue = list(messages)

    async def create(**kwargs):
        message = queue.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        )
    )
    monkeypatch.setattr(loop_mod, "client", fake_client)


def test_pure_text_run_emits_trace(monkeypatch):
    sink = ListSink()
    reasoning = "r" * 1000
    _install_client(monkeypatch, [FakeMessage(content="hello", reasoning_content=reasoning)])

    agent = Agent(name="anna", instructions="sys", model="gpt-test")
    result = asyncio.run(
        run(
            agent,
            [{"role": "user", "content": "hi"}],
            trace_sink=sink,
            run_meta=RunMeta(run_kind="cli_chat", source="test"),
        )
    )

    assert result.final_output == "hello"
    event_types = [event.type for event in sink.events]
    assert event_types == [
        "run.started",
        "turn.started",
        "inbox.drained",
        "llm.requested",
        "llm.responded",
        "run.finished",
    ]
    llm_response = next(event for event in sink.events if event.type == "llm.responded")
    assert len(llm_response.payload["reasoning_preview"]) <= 200
    assert llm_response.payload["reasoning_preview"] != reasoning


def test_multiple_tool_calls_keep_order(monkeypatch):
    sink = ListSink()
    _install_client(
        monkeypatch,
        [
            FakeMessage(
                tool_calls=[
                    FakeToolCall("tool1", '{"value":"one"}', "c1"),
                    FakeToolCall("tool2", '{"value":"two"}', "c2"),
                ]
            ),
            FakeMessage(content="done"),
        ],
    )

    tool1 = Tool(name="tool1", description="", params=DummyParams, fn=lambda value: value)
    tool2 = Tool(name="tool2", description="", params=DummyParams, fn=lambda value: value)
    agent = Agent(name="anna", instructions="sys", model="gpt-test", tools=[tool1, tool2])

    result = asyncio.run(
        run(
            agent,
            [{"role": "user", "content": "hi"}],
            trace_sink=sink,
            run_meta=RunMeta(run_kind="cli_chat", source="test"),
        )
    )

    assert result.last_tool == "tool2"
    tool_events = [(event.type, event.payload.get("tool_name"), event.status) for event in sink.events if event.lane == "tool"]
    assert tool_events == [
        ("tool.started", "tool1", "ok"),
        ("tool.finished", "tool1", "ok"),
        ("tool.started", "tool2", "ok"),
        ("tool.finished", "tool2", "ok"),
    ]


def test_unknown_tool_appends_error_and_traces(monkeypatch):
    sink = ListSink()
    _install_client(
        monkeypatch,
        [
            FakeMessage(tool_calls=[FakeToolCall("missing_tool", '{"value":"x"}', "c1")]),
            FakeMessage(content="done"),
        ],
    )

    agent = Agent(name="anna", instructions="sys", model="gpt-test")
    result = asyncio.run(
        run(
            agent,
            [{"role": "user", "content": "hi"}],
            trace_sink=sink,
            run_meta=RunMeta(run_kind="cli_chat", source="test"),
        )
    )

    assert any(message.get("role") == "tool" and "unknown tool" in message.get("content", "") for message in result.messages)
    assert any(event.type == "tool.finished" and event.status == "error" for event in sink.events)


def test_tool_exception_emits_failed_run(monkeypatch):
    sink = ListSink()
    _install_client(
        monkeypatch,
        [FakeMessage(tool_calls=[FakeToolCall("boom", '{"value":"x"}', "c1")])],
    )

    def _boom(value: str) -> str:
        raise RuntimeError("boom")

    boom_tool = Tool(name="boom", description="", params=DummyParams, fn=_boom)
    agent = Agent(name="anna", instructions="sys", model="gpt-test", tools=[boom_tool])

    with pytest.raises(RuntimeError):
        asyncio.run(
            run(
                agent,
                [{"role": "user", "content": "hi"}],
                trace_sink=sink,
                run_meta=RunMeta(run_kind="cli_chat", source="test"),
            )
        )

    assert any(event.type == "tool.finished" and event.status == "error" for event in sink.events)
    assert any(event.type == "run.failed" for event in sink.events)


def test_max_turns_and_mid_run_inbox(monkeypatch):
    sink = ListSink()

    def _enqueue(ctx, value: str) -> str:
        ctx.inbox.put_nowait("later")
        return "queued"

    enqueue_tool = Tool(name="enqueue", description="", params=DummyParams, fn=_enqueue)
    noop_tool = Tool(name="noop", description="", params=DummyParams, fn=lambda value: value or "ok")

    _install_client(
        monkeypatch,
        [
            FakeMessage(tool_calls=[FakeToolCall("enqueue", '{"value":"first"}', "c1")]),
            FakeMessage(tool_calls=[FakeToolCall("noop", '{"value":"next"}', "c2")]),
        ],
    )

    agent = Agent(
        name="anna",
        instructions="sys",
        model="gpt-test",
        tools=[enqueue_tool, noop_tool],
    )
    ctx = AgentContext()

    result = asyncio.run(
        run(
            agent,
            [{"role": "user", "content": "hi"}],
            ctx=ctx,
            max_turns=2,
            trace_sink=sink,
            run_meta=RunMeta(run_kind="cli_chat", source="test"),
        )
    )

    assert result.trace_seq > 0
    second_turn_drain = [
        event for event in sink.events
        if event.type == "inbox.drained" and event.payload.get("turn") == 2
    ][0]
    assert second_turn_drain.payload["count"] == 1

    sink2 = ListSink()
    _install_client(
        monkeypatch,
        [FakeMessage(tool_calls=[FakeToolCall("noop", '{"value":"x"}', "c3")])],
    )
    agent2 = Agent(name="anna", instructions="sys", model="gpt-test", tools=[noop_tool])
    asyncio.run(
        run(
            agent2,
            [{"role": "user", "content": "hi"}],
            max_turns=1,
            trace_sink=sink2,
            run_meta=RunMeta(run_kind="cli_chat", source="test"),
        )
    )
    assert any(event.type == "run.max_turns_hit" for event in sink2.events)
