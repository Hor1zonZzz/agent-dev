"""Plan read/write/validate tests.

Run:  uv run python -m pytest tests/test_plan.py -v
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hermes import plan as plan_mod
from hermes.plan import (
    MAX_INSTRUCTION_LEN,
    MAX_TITLE_LEN,
    Plan,
    PlanTask,
    read_plan,
    validate_tasks,
    write_plan,
)


@pytest.fixture
def plan_dir(tmp_path, monkeypatch) -> Path:
    """Redirect PLAN_DIR to a tmp dir for the duration of the test."""
    d = tmp_path / "plans"
    monkeypatch.setattr(plan_mod, "PLAN_DIR", d)
    return d


# ---- validate_tasks -------------------------------------------------------


def _task(t: str, title: str = "title", instr: str = "do stuff") -> PlanTask:
    return PlanTask(time=t, title=title, instruction=instr)


def test_validate_ok():
    tasks = [_task("08:30"), _task("14:00"), _task("20:00")]
    assert validate_tasks(tasks) == []


def test_validate_empty_list():
    errors = validate_tasks([])
    assert len(errors) == 1
    assert "至少要有" in errors[0]


def test_validate_too_many():
    tasks = [_task(f"{6 + i}:30") for i in range(7)]
    # 7 > MAX_TASKS=6
    errors = validate_tasks(tasks)
    assert any("任务数量" in e for e in errors)


def test_validate_bad_time_format():
    errors = validate_tasks([_task("8:30am")])
    assert any("格式不对" in e for e in errors)


def test_validate_time_before_window():
    errors = validate_tasks([_task("06:00")])
    assert any("超出允许区间" in e for e in errors)


def test_validate_time_after_window():
    errors = validate_tasks([_task("23:00")])
    assert any("超出允许区间" in e for e in errors)


def test_validate_descending_times():
    tasks = [_task("14:00"), _task("10:00")]
    errors = validate_tasks(tasks)
    assert any("必须严格晚于前一条" in e for e in errors)


def test_validate_equal_times():
    tasks = [_task("14:00"), _task("14:00")]
    errors = validate_tasks(tasks)
    assert any("必须严格晚于前一条" in e for e in errors)


def test_validate_gap_too_small():
    tasks = [_task("14:00"), _task("14:20")]
    errors = validate_tasks(tasks)
    assert any("间隔只有" in e for e in errors)


def test_validate_title_too_long():
    tasks = [_task("08:00", title="a" * (MAX_TITLE_LEN + 1))]
    errors = validate_tasks(tasks)
    assert any("title 超过" in e for e in errors)


def test_validate_instruction_too_long():
    tasks = [_task("08:00", instr="a" * (MAX_INSTRUCTION_LEN + 1))]
    errors = validate_tasks(tasks)
    assert any("instruction 超过" in e for e in errors)


# ---- write_plan / read_plan roundtrip ------------------------------------


def test_write_read_roundtrip(plan_dir: Path):
    day = date(2026, 4, 15)
    tasks = [_task("08:30", title="查天气"), _task("14:00", title="读长文")]
    path = write_plan(day, tasks)
    assert path.exists()
    assert path.parent == plan_dir

    plan = read_plan(day)
    assert plan is not None
    assert plan.date == "2026-04-15"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].title == "查天气"
    assert plan.tasks[1].time == "14:00"


def test_read_missing_plan(plan_dir: Path):
    assert read_plan(date(2099, 1, 1)) is None


def test_read_invalid_json(plan_dir: Path):
    plan_dir.mkdir(parents=True, exist_ok=True)
    day = date(2026, 4, 15)
    (plan_dir / f"{day.isoformat()}.json").write_text("not json at all", encoding="utf-8")
    assert read_plan(day) is None


def test_read_plan_failing_validation_returns_none(plan_dir: Path):
    """A plan file with time-window-violating tasks should read as None so
    the scheduler falls back to defaults."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    day = date(2026, 4, 15)
    # Construct a raw plan that bypasses write_plan's implicit "no validation"
    # (write_plan doesn't validate — the caller does). So we can write a
    # technically-well-formed JSON with an out-of-window time, and read_plan
    # should reject it.
    bad_plan = Plan(
        date=day.isoformat(),
        generated_at="2026-04-14T23:00:00",
        tasks=[PlanTask(time="05:00", title="too early", instruction="x")],
    )
    (plan_dir / f"{day.isoformat()}.json").write_text(
        bad_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    assert read_plan(day) is None
