"""In-process scheduler for Hermes daily slots.

Anna's "scheduled life" is tied to whichever host process owns it (e.g.
``wechat.py``). When the host starts, the scheduler starts; when the host
shuts down, the scheduler stops with it. There is no catch-up — slots that
fire while the host is offline are simply skipped, on the principle that
Anna only "lives" while she's reachable.

The Hermes Python SDK is synchronous (a single ``AIAgent.chat`` can take
minutes), so each slot runs in a worker thread via ``asyncio.to_thread``
to keep the host event loop responsive.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, time, timedelta

from loguru import logger

# (slot_name, daily_time). Slot names must match keys in ``hermes.tasks.TASKS``.
DEFAULT_SCHEDULE: list[tuple[str, time]] = [
    ("morning", time(8, 0)),
    ("noon", time(12, 0)),
    ("evening", time(21, 0)),
]


def _next_due(
    schedule: list[tuple[str, time]],
    now: datetime,
) -> tuple[str, datetime]:
    """Return (slot_name, next_fire_datetime) for the soonest future slot."""
    best: tuple[str, datetime] | None = None
    for name, t in schedule:
        candidate = datetime.combine(now.date(), t)
        if candidate <= now:
            candidate += timedelta(days=1)
        if best is None or candidate < best[1]:
            best = (name, candidate)
    assert best is not None
    return best


async def _scheduler_loop(schedule: list[tuple[str, time]]) -> None:
    # Defer the heavy import — hermes-agent pulls in browser/playwright stubs
    # and slows wechat startup if loaded eagerly.
    from hermes.runner import run_slot

    # Default to deepseek-chat for cron runs unless the user explicitly set
    # HERMES_MODEL. Falling through to OPENAI_MODEL (often deepseek-reasoner)
    # would make each slot take ~30 minutes instead of ~4.
    os.environ.setdefault("HERMES_MODEL", "deepseek-chat")

    while True:
        slot_name, due_at = _next_due(schedule, datetime.now())
        wait = (due_at - datetime.now()).total_seconds()
        logger.info(
            "[hermes-cron] 下一次: {} at {} (在 {:.0f} 秒后)",
            slot_name, due_at.strftime("%Y-%m-%d %H:%M"), wait,
        )
        await asyncio.sleep(max(1.0, wait))

        try:
            # run_slot blocks for minutes; thread keeps the event loop alive.
            exit_code = await asyncio.to_thread(run_slot, slot_name)
            logger.info("[hermes-cron] {} 完成 (exit={})", slot_name, exit_code)
        except Exception:
            logger.exception("[hermes-cron] {} 异常", slot_name)


def start(
    schedule: list[tuple[str, time]] | None = None,
) -> asyncio.Task:
    """Spawn the scheduler as a background task. Cancel it to stop."""
    sched = schedule if schedule is not None else DEFAULT_SCHEDULE
    return asyncio.create_task(_scheduler_loop(sched), name="anna-hermes-cron")


async def stop(task: asyncio.Task) -> None:
    """Cancel the scheduler task and await its clean shutdown.

    Note: a slot already running in a thread (via ``asyncio.to_thread``) will
    continue to completion — Python can't kill threads. Ctrl+C during a slot
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
