from __future__ import annotations

import asyncio

import pytest

from hermes import scheduler


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def test_scheduler_loop_emits_schedule_events(monkeypatch):
    sink = ListSink()
    event = scheduler.ScheduledEvent(kind="planner", when=scheduler.datetime.now(), payload=None)
    calls = {"count": 0}

    def fake_next_event(now):
        calls["count"] += 1
        if calls["count"] == 1:
            return event
        raise asyncio.CancelledError()

    async def fake_run_event(event, recorder):
        return "ok", {"ok": True}

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(scheduler, "_next_event", fake_next_event)
    monkeypatch.setattr(scheduler, "_run_event", fake_run_event)
    monkeypatch.setattr(scheduler, "get_default_trace_sink", lambda: sink)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler._scheduler_loop())

    event_types = [event.type for event in sink.events]
    assert event_types == [
        "schedule.next_computed",
        "schedule.fired",
        "schedule.finished",
    ]
