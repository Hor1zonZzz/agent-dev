"""In-process scheduler for Hermes daily tasks + nightly self-planner.

Anna's "scheduled life" is tied to whichever host process owns it (e.g.
``wechat.py``). When the host starts, the scheduler starts; when the host
shuts down, the scheduler stops with it. There is no catch-up — events that
fire while the host is offline are simply skipped, on the principle that
Anna only "lives" while she's reachable.

Event sources (recomputed fresh before every sleep):

* **Planner** — fixed at :data:`PLANNER_TIME` (23:00). Runs
  :func:`hermes.planner.run_planner`, which lets Anna decide tomorrow's
  plan.
* **Hermes tasks** — either from today's plan file (if Anna saved one) or
  from :data:`DEFAULT_SCHEDULE` mapped onto :mod:`hermes.tasks` (fallback).
  Plan fully overrides defaults for the day.

The Hermes Python SDK is synchronous, so each Hermes task runs in a worker
thread via ``asyncio.to_thread`` to keep the host event loop responsive.
The planner is async-native (calls ``core.loop.run``) and runs inline.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from loguru import logger

# (slot_name, daily_time). Used when no plan file exists for the day.
DEFAULT_SCHEDULE: list[tuple[str, time]] = [
    ("morning", time(8, 0)),
    ("noon", time(12, 0)),
    ("evening", time(21, 0)),
]

# When the nightly planner runs. Must stay before the quiet-hour window
# (00:00-06:00) and after the latest allowed task time (22:30).
PLANNER_TIME: time = time(23, 0)


@dataclass(frozen=True)
class ScheduledEvent:
    """One upcoming event the scheduler will fire."""

    kind: Literal["planner", "hermes_task", "hermes_slot"]
    when: datetime
    # hermes_task: (title, instruction); hermes_slot: slot name; planner: ignored.
    payload: tuple[str, str] | str | None = None


def _candidates_for_day(day: date) -> list[ScheduledEvent]:
    """Build the list of events for *day* (without filtering by now)."""
    # Deferred import: hermes.plan is cheap but keeps the public module
    # surface minimal when someone imports this file for constants.
    from hermes.plan import read_plan

    events: list[ScheduledEvent] = []

    # Planner is always scheduled, every day.
    events.append(
        ScheduledEvent(
            kind="planner",
            when=datetime.combine(day, PLANNER_TIME),
        )
    )

    plan = read_plan(day)
    if plan is not None:
        for task in plan.tasks:
            hh, mm = task.time.split(":")
            events.append(
                ScheduledEvent(
                    kind="hermes_task",
                    when=datetime.combine(day, time(int(hh), int(mm))),
                    payload=(task.title, task.instruction),
                )
            )
    else:
        for slot_name, t in DEFAULT_SCHEDULE:
            events.append(
                ScheduledEvent(
                    kind="hermes_slot",
                    when=datetime.combine(day, t),
                    payload=slot_name,
                )
            )

    return events


def _next_event(now: datetime) -> ScheduledEvent:
    """Return the nearest event strictly after *now*.

    Checks today first; if nothing remains today, rolls to tomorrow (which
    may have a plan file generated tonight by the planner).
    """
    for offset in (0, 1, 2):  # today, tomorrow, day-after (safety)
        day = now.date() + timedelta(days=offset)
        future = [e for e in _candidates_for_day(day) if e.when > now]
        if future:
            future.sort(key=lambda e: e.when)
            return future[0]
    # Should be unreachable — planner is scheduled every day, so there's
    # always *some* event within 24h.
    raise RuntimeError("no upcoming scheduled events (unexpected)")


async def _run_event(event: ScheduledEvent) -> None:
    """Dispatch a single fired event."""
    if event.kind == "planner":
        from hermes.planner import run_planner

        try:
            ok = await run_planner()
            logger.info("[hermes-cron] planner 完成 (ok={})", ok)
        except Exception:
            logger.exception("[hermes-cron] planner 异常")
        return

    if event.kind == "hermes_task":
        from hermes.runner import run_single_task

        assert isinstance(event.payload, tuple)
        title, instruction = event.payload
        try:
            ok = await asyncio.to_thread(run_single_task, title, instruction)
            logger.info("[hermes-cron] task '{}' 完成 (ok={})", title, ok)
        except Exception:
            logger.exception("[hermes-cron] task '{}' 异常", title)
        return

    if event.kind == "hermes_slot":
        from hermes.runner import run_slot

        assert isinstance(event.payload, str)
        slot_name = event.payload
        try:
            exit_code = await asyncio.to_thread(run_slot, slot_name)
            logger.info("[hermes-cron] {} 完成 (exit={})", slot_name, exit_code)
        except Exception:
            logger.exception("[hermes-cron] {} 异常", slot_name)
        return


async def _scheduler_loop() -> None:
    # Default to deepseek-chat for Hermes tasks unless the user explicitly
    # set HERMES_MODEL. Falling through to OPENAI_MODEL (often
    # deepseek-reasoner) would make each task take ~30 minutes instead of ~4.
    os.environ.setdefault("HERMES_MODEL", "deepseek-chat")

    while True:
        event = _next_event(datetime.now())
        wait = (event.when - datetime.now()).total_seconds()

        if event.kind == "planner":
            label = "planner"
        elif event.kind == "hermes_task":
            assert isinstance(event.payload, tuple)
            label = f"task '{event.payload[0]}'"
        else:
            label = f"slot {event.payload}"

        logger.info(
            "[hermes-cron] 下一次: {} at {} (在 {:.0f} 秒后)",
            label, event.when.strftime("%Y-%m-%d %H:%M"), wait,
        )
        await asyncio.sleep(max(1.0, wait))

        await _run_event(event)


def start() -> asyncio.Task:
    """Spawn the scheduler as a background task. Cancel it to stop."""
    return asyncio.create_task(_scheduler_loop(), name="anna-hermes-cron")


async def stop(task: asyncio.Task) -> None:
    """Cancel the scheduler task and await its clean shutdown.

    Note: a task already running in a thread (via ``asyncio.to_thread``) will
    continue to completion — Python can't kill threads. Ctrl+C during a task
    therefore takes up to a few minutes to fully exit.
    """
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


# ---------------------------------------------------------------------------
# Standalone entry: ``python -m hermes.scheduler``
#
# Run the scheduler as its own process (no wechat dependency). Useful when
# you want diary cron without the chat layer, or when debugging the
# scheduler itself.
# ---------------------------------------------------------------------------

async def _standalone() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logger.info("[hermes-cron] standalone scheduler started (Ctrl+C to stop)")
    task = start()
    try:
        await task  # block forever unless task crashes
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(_standalone())
    except KeyboardInterrupt:
        logger.info("[hermes-cron] 已停止。")
