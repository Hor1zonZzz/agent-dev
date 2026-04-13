"""Proactive outreach — Anna initiates conversation after a quiet stretch.

Algorithm
---------
For every user with at least one prior Anna reply:

1. ``next_proactive_at`` is sampled from ``last_anna_message_at + random(INTERVAL_MINUTES)``.
2. A background loop checks every ``CHECK_INTERVAL_SECONDS`` whether the target
   has been reached.
3. Quiet hours [00:00, 06:00) are *strictly skipped* — when the alarm would
   fire inside that window, the round is dropped and a fresh interval is
   sampled starting from 06:00.
4. When firing, a synthetic system-style ``user`` message is enqueued; the
   worker treats it as a "you may speak now" prompt and either calls
   ``send_message`` or stays silent. The synthetic message is stripped from
   persisted history so it never appears as a real user turn.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from core.memory import (
    get_last_anna_message,
    get_next_proactive_at,
    update_next_proactive_at,
)

QUIET_START_HOUR = 0
QUIET_END_HOUR = 6
INTERVAL_MINUTES = (120, 240, 360, 480)  # 2h, 4h, 6h, 8h
CHECK_INTERVAL_SECONDS = 60


def is_quiet_hour(when: datetime) -> bool:
    return QUIET_START_HOUR <= when.hour < QUIET_END_HOUR


def _next_wakeup_after_quiet(when: datetime) -> datetime:
    """First moment at/after ``QUIET_END_HOUR`` on or after ``when``'s date."""
    end = when.replace(hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0)
    if when.hour >= QUIET_END_HOUR:
        end += timedelta(days=1)
    return end


def _pick_interval() -> timedelta:
    return timedelta(minutes=random.choice(INTERVAL_MINUTES))


def compute_next_proactive(base: datetime) -> datetime:
    """Pick the next fire time, skipping the quiet window if the roll lands inside."""
    target = base + _pick_interval()
    if is_quiet_hour(target):
        target = _next_wakeup_after_quiet(target) + _pick_interval()
    return target


def _format_gap(delta: timedelta) -> str:
    secs = max(0, int(delta.total_seconds()))
    if secs >= 3600:
        return f"{secs // 3600} 小时"
    return f"{max(1, secs // 60)} 分钟"


def build_trigger_message(now: datetime, last_anna_at: datetime) -> str:
    return (
        f"[系统提示·主动触发，非用户消息] 现在是 {now.strftime('%H:%M')}，"
        f"距离你上次和 TA 说话已经 {_format_gap(now - last_anna_at)}。"
        f"如果有想主动说的就用 send_message 发出来；"
        f"如果现在没什么想说的，直接 end_turn 保持沉默即可。"
    )


EnqueueFn = Callable[[str, str, bool], Awaitable[None]]


async def proactive_loop(history_dir: Path, enqueue: EnqueueFn) -> None:
    """Forever-loop: scan per-user meta files and fire triggers when due."""
    logger.info(
        "[proactive] loop started (intervals={}min, quiet={:02d}-{:02d})",
        INTERVAL_MINUTES,
        QUIET_START_HOUR,
        QUIET_END_HOUR,
    )
    while True:
        try:
            await _scan_once(history_dir, enqueue)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[proactive] scan failed; continuing")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _scan_once(history_dir: Path, enqueue: EnqueueFn) -> None:
    if not history_dir.exists():
        return

    now = datetime.now()

    for history_path in history_dir.glob("*.json"):
        # Skip the sidecar meta files.
        if history_path.name.endswith(".meta.json"):
            continue

        last_anna_at = get_last_anna_message(history_path)
        if last_anna_at is None:
            continue  # Anna never spoke to this user → don't cold-start

        next_at = get_next_proactive_at(history_path)
        if next_at is None:
            update_next_proactive_at(history_path, compute_next_proactive(last_anna_at))
            continue

        if now < next_at:
            continue

        if is_quiet_hour(now):
            new_next = _next_wakeup_after_quiet(now) + _pick_interval()
            update_next_proactive_at(history_path, new_next)
            logger.info(
                "[proactive] quiet-hour skip for {} → next={}",
                history_path.stem, new_next.isoformat(timespec="minutes"),
            )
            continue

        await _fire(history_path, now, last_anna_at, enqueue)


async def _fire(
    history_path: Path,
    now: datetime,
    last_anna_at: datetime,
    enqueue: EnqueueFn,
) -> None:
    from core.memory import get_dispatch_info

    user_id, _ = get_dispatch_info(history_path)
    if not user_id:
        # No raw user_id captured yet — without it we can't dispatch outbound.
        # Push the next attempt forward so we don't busy-loop on this user.
        update_next_proactive_at(history_path, compute_next_proactive(now))
        return

    text = build_trigger_message(now, last_anna_at)

    # Advance schedule first so a slow worker doesn't get re-fired.
    # When the worker finishes it overwrites this with a fresh roll based
    # on the new last_anna_message_at.
    update_next_proactive_at(history_path, compute_next_proactive(now))

    await enqueue(user_id, text, True)
    logger.info("[proactive] fired for {}", user_id)
