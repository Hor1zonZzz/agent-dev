"""Scheduler next-event dispatch tests.

Run:  uv run python -m pytest tests/test_scheduler_next_due.py -v

We test ``_next_event`` / ``_candidates_for_day`` in isolation (without
sleeping or actually running planner/hermes) by monkeypatching
``hermes.plan.read_plan``.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from hermes import plan as plan_mod
from hermes import scheduler
from hermes.plan import Plan, PlanTask


@pytest.fixture
def no_plan(monkeypatch):
    """Force read_plan -> None so scheduler uses DEFAULT_SCHEDULE."""
    monkeypatch.setattr("hermes.plan.read_plan", lambda day: None)


@pytest.fixture
def plan_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "plans"
    monkeypatch.setattr(plan_mod, "PLAN_DIR", d)
    return d


def _mk_plan(day: date, times_and_titles: list[tuple[str, str]]) -> Plan:
    return Plan(
        date=day.isoformat(),
        generated_at="2026-04-14T23:00:00",
        tasks=[PlanTask(time=t, title=tt, instruction="x") for t, tt in times_and_titles],
    )


def test_no_plan_returns_default_schedule_plus_planner(no_plan):
    day = date(2026, 4, 14)
    events = scheduler._candidates_for_day(day)
    kinds = [e.kind for e in events]
    # 1 planner + 3 default slots
    assert kinds.count("planner") == 1
    assert kinds.count("hermes_slot") == 3
    slots = sorted(
        e.payload for e in events if e.kind == "hermes_slot" and isinstance(e.payload, str)
    )
    assert slots == ["evening", "morning", "noon"]


def test_plan_replaces_default_schedule(monkeypatch, plan_dir):
    day = date(2026, 4, 15)
    plan = _mk_plan(day, [("08:30", "查天气"), ("20:00", "读文章")])
    monkeypatch.setattr("hermes.plan.read_plan", lambda d: plan if d == day else None)

    events = scheduler._candidates_for_day(day)
    kinds = [e.kind for e in events]
    assert kinds.count("planner") == 1
    assert kinds.count("hermes_task") == 2
    assert kinds.count("hermes_slot") == 0
    titles = sorted(
        e.payload[0] for e in events if e.kind == "hermes_task" and isinstance(e.payload, tuple)
    )
    assert titles == ["查天气", "读文章"]


def test_next_event_picks_strictly_future(no_plan, monkeypatch):
    # Today = 2026-04-14 10:30 — morning (08:00) already past, should skip.
    now = datetime(2026, 4, 14, 10, 30)
    event = scheduler._next_event(now)
    assert event.kind == "hermes_slot"
    assert event.payload == "noon"
    assert event.when == datetime(2026, 4, 14, 12, 0)


def test_next_event_rolls_to_tomorrow(no_plan):
    # 23:30 — planner (23:00) already past; tomorrow morning (08:00) is next.
    now = datetime(2026, 4, 14, 23, 30)
    event = scheduler._next_event(now)
    assert event.kind == "hermes_slot"
    assert event.payload == "morning"
    assert event.when == datetime(2026, 4, 15, 8, 0)


def test_next_event_picks_planner_at_22_30(no_plan):
    # At 22:30, next event is the 23:00 planner.
    now = datetime(2026, 4, 14, 22, 30)
    event = scheduler._next_event(now)
    assert event.kind == "planner"
    assert event.when == datetime(2026, 4, 14, 23, 0)


def test_next_event_skips_past_plan_tasks(monkeypatch, plan_dir):
    day = date(2026, 4, 15)
    plan = _mk_plan(day, [("08:30", "a"), ("14:00", "b"), ("20:00", "c")])
    monkeypatch.setattr("hermes.plan.read_plan", lambda d: plan if d == day else None)

    # 15:00 — 08:30 and 14:00 are past, next plan task is 20:00.
    event = scheduler._next_event(datetime(2026, 4, 15, 15, 0))
    assert event.kind == "hermes_task"
    assert isinstance(event.payload, tuple)
    assert event.payload[0] == "c"
    assert event.when == datetime(2026, 4, 15, 20, 0)


def test_planner_fires_every_day(no_plan):
    # Over two consecutive days, planner should appear both days.
    today = date(2026, 4, 14)
    tomorrow = date(2026, 4, 15)
    today_events = scheduler._candidates_for_day(today)
    tomorrow_events = scheduler._candidates_for_day(tomorrow)
    assert any(e.kind == "planner" for e in today_events)
    assert any(e.kind == "planner" for e in tomorrow_events)
