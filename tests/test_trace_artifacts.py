from __future__ import annotations

import asyncio

from core.context import AgentContext
from core.trace import RunMeta, TraceRecorder
from hermes import diary as diary_mod
from hermes import plan as plan_mod


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def test_plan_save_emits_trace_events(tmp_path, monkeypatch):
    sink = ListSink()
    recorder = TraceRecorder(sink, RunMeta(run_kind="planner", source="test"))
    ctx = AgentContext(trace_recorder=recorder)
    monkeypatch.setattr(plan_mod, "PLAN_DIR", tmp_path)

    result = plan_mod._save_plan(
        ctx,
        [
            {"time": "08:30", "title": "查天气", "instruction": "看一眼天气"},
            {"time": "09:30", "title": "读文章", "instruction": "读一篇文章"},
        ],
    )

    assert "已保存 2 条任务" in result
    assert any(event.type == "plan.saved" for event in sink.events)
    assert any(event.type == "artifact.written" for event in sink.events)


def test_diary_append_emits_trace_events(tmp_path, monkeypatch):
    sink = ListSink()
    recorder = TraceRecorder(sink, RunMeta(run_kind="hermes_task", source="test"))
    monkeypatch.setattr(diary_mod, "DIARY_DIR", tmp_path)

    path = diary_mod.append_entry("标题", "内容", trace_recorder=recorder)

    assert path.exists()
    assert any(event.type == "diary.appended" for event in sink.events)
    assert any(event.type == "artifact.written" for event in sink.events)


def test_memory_compress_emits_trace_events(tmp_path, monkeypatch):
    import core.memory as memory_mod

    sink = ListSink()
    history_path = tmp_path / "chat.json"
    history_path.write_text('[{"role":"user","content":"hello"}]', encoding="utf-8")
    monkeypatch.setattr(memory_mod, "HISTORY_DIR", tmp_path)

    class FakeCompletions:
        async def create(self, **kwargs):
            content = """\
## user_facts
- 用户说了 hello

## user_state
（暂无）

## user_preferences
（暂无）

## anna_stance
（暂无）

## anna_commitments
（暂无）

## topic_thread
- 打了个招呼

## open_threads
（暂无）
"""
            return type(
                "Resp",
                (),
                {"choices": [type("Choice", (), {"message": type("Msg", (), {"content": content})()})]},
            )()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(memory_mod, "AsyncOpenAI", FakeClient)

    asyncio.run(memory_mod._compress(history_path, 0, 1, trace_sink=sink))

    event_types = [event.type for event in sink.events]
    assert "memory.compression_started" in event_types
    assert "memory.compression_finished" in event_types
    assert "artifact.written" in event_types
