"""Anna's daily plan file — what she decided the night before to do today.

Written by ``hermes/planner.py`` (Anna calls the ``save_plan`` tool), read by
``hermes/scheduler.py`` which dispatches each task at its scheduled time.

File convention: ``history/plans/YYYY-MM-DD.json`` — one file per day, same
style as ``history/diary/``. Atomic writes (tmp + ``os.replace``) so the
scheduler never sees a partial file.

If a plan file exists for today, the scheduler runs it instead of the static
``hermes/tasks.py`` list. If it doesn't exist (host was offline overnight,
Anna decided not to plan, validation failed), the scheduler falls back to
the defaults.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

PLAN_DIR = Path(__file__).resolve().parent.parent / "history" / "plans"

# Tasks must fall inside this window so they don't collide with the planner
# (23:00) or the quiet-hours rule (00:00-06:00).
EARLIEST_TASK_TIME = time(6, 30)
LATEST_TASK_TIME = time(22, 30)

MAX_TASKS = 6
MIN_GAP_MINUTES = 30
MAX_TITLE_LEN = 30
MAX_INSTRUCTION_LEN = 500


class PlanTask(BaseModel):
    time: str = Field(
        description='Time of day to run, formatted "HH:MM" (24h, local time).',
    )
    title: str = Field(
        description="Short headline for the diary entry.",
        min_length=1,
    )
    instruction: str = Field(
        description="Free-text instruction to Hermes about what to do.",
        min_length=1,
    )


class Plan(BaseModel):
    date: str  # ISO YYYY-MM-DD
    generated_at: str  # ISO timestamp
    tasks: list[PlanTask]


def plan_path(day: date) -> Path:
    return PLAN_DIR / f"{day.isoformat()}.json"


def _parse_hhmm(s: str) -> time | None:
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def validate_tasks(tasks: list[PlanTask]) -> list[str]:
    """Return a list of human-readable errors. Empty list means valid."""
    errors: list[str] = []

    if not tasks:
        errors.append("至少要有 1 条任务。")
        return errors

    if len(tasks) > MAX_TASKS:
        errors.append(f"任务数量 {len(tasks)} 超出上限 {MAX_TASKS}。")

    parsed_times: list[time] = []
    for i, t in enumerate(tasks, 1):
        parsed = _parse_hhmm(t.time)
        if parsed is None:
            errors.append(f"第 {i} 条 time='{t.time}' 格式不对，应为 HH:MM。")
            continue
        if parsed < EARLIEST_TASK_TIME or parsed > LATEST_TASK_TIME:
            errors.append(
                f"第 {i} 条 time={t.time} 超出允许区间 "
                f"[{EARLIEST_TASK_TIME.strftime('%H:%M')}, {LATEST_TASK_TIME.strftime('%H:%M')}]。"
            )
        if len(t.title) > MAX_TITLE_LEN:
            errors.append(f"第 {i} 条 title 超过 {MAX_TITLE_LEN} 字符。")
        if len(t.instruction) > MAX_INSTRUCTION_LEN:
            errors.append(f"第 {i} 条 instruction 超过 {MAX_INSTRUCTION_LEN} 字符。")
        parsed_times.append(parsed)

    # Strict ascending + min gap
    for i in range(1, len(parsed_times)):
        prev, curr = parsed_times[i - 1], parsed_times[i]
        if curr <= prev:
            errors.append(f"第 {i + 1} 条 time={curr.strftime('%H:%M')} 必须严格晚于前一条。")
            continue
        gap = (curr.hour * 60 + curr.minute) - (prev.hour * 60 + prev.minute)
        if gap < MIN_GAP_MINUTES:
            errors.append(
                f"第 {i} 条与第 {i + 1} 条间隔只有 {gap} 分钟，至少要 {MIN_GAP_MINUTES} 分钟。"
            )

    return errors


def write_plan(day: date, tasks: list[PlanTask]) -> Path:
    """Atomically write today's plan. Caller is responsible for validation."""
    PLAN_DIR.mkdir(parents=True, exist_ok=True)

    plan = Plan(
        date=day.isoformat(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        tasks=tasks,
    )
    path = plan_path(day)
    payload = plan.model_dump_json(indent=2)

    fd, tmp_path = tempfile.mkstemp(dir=PLAN_DIR, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return path


def read_plan(day: date) -> Plan | None:
    """Return the plan for *day*, or None if missing / invalid.

    Validation failures here are logged but treated as "no plan" so the
    scheduler falls back to defaults rather than crashing.
    """
    path = plan_path(day)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        plan = Plan.model_validate_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[plan] {} 解析失败: {}", path.name, e)
        return None

    errors = validate_tasks(plan.tasks)
    if errors:
        logger.warning("[plan] {} 校验失败: {}", path.name, "; ".join(errors))
        return None

    return plan
