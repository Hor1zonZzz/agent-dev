"""Anna's night-time self-planner.

At 23:00 every night the scheduler fires this planner. It spins up Anna
herself (same soul / guidelines / user_profile / mood that drives chat) and
asks her to decide what she wants to do tomorrow — what small activities,
at what times. Her answer is persisted via the ``save_plan`` tool to
``history/plans/<tomorrow>.json``; the next day Hermes dispatches those
tasks instead of the static defaults in ``hermes/tasks.py``.

On failure: logged and ignored. We don't write anything to the diary and
we don't message the user. The scheduler falls back to the default TASKS
for the day when no plan file is found.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
from loguru import logger

from core.loop import Agent, run
from core.tools import end_turn, recall_day, save_plan
from prompts import build

load_dotenv()


PLANNER_TRIGGER_TEMPLATE = (
    "[系统提示·睡前规划，非用户消息] 现在是 {now}，quiet hour 快到了。"
    "想想明天（{tomorrow}）你想做点什么小事 —— 1 到 6 件就好，"
    "比如查天气、刷刷 HN、看篇文章、了解点新东西。"
    "你可以用 recall_day 翻翻前几天的日记，避免重复或参考节奏。"
    "想好之后用 save_plan 存下来，每条给个时间（HH:MM，6:30-22:30 之间，"
    "相邻至少隔 30 分钟）、简短标题、以及给 Hermes 的指令。"
    "规划完就 end_turn，不用和用户说什么。"
)


def _build_planner_agent() -> Agent:
    """Planner Agent — Anna with a slimmer toolset (no send_message)."""
    return Agent(
        name="anna-planner",
        instructions=lambda ctx: build(memory=ctx.memory if ctx else None),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        tools=[recall_day, save_plan, end_turn],
        stop_at={"end_turn"},
    )


async def run_planner() -> bool:
    """Run one planning turn. Returns True if a plan file was produced."""
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()

    trigger = PLANNER_TRIGGER_TEMPLATE.format(
        now=now.strftime("%H:%M"),
        tomorrow=tomorrow.isoformat(),
    )

    logger.info("[planner] 启动 (目标日期 {})", tomorrow.isoformat())

    agent = _build_planner_agent()

    try:
        result = await run(
            agent,
            input=[{"role": "user", "content": trigger}],
            max_turns=8,
        )
    except Exception:
        logger.exception("[planner] 规划运行异常")
        return False

    # Check whether save_plan was actually called and succeeded. The tool
    # returns "已保存 N 条..." on success. Even if she called it, validation
    # might have failed on the last attempt, in which case the file won't
    # exist — read_plan will handle that tomorrow by returning None.
    from hermes.plan import read_plan

    plan = read_plan(tomorrow)
    if plan is None:
        logger.warning(
            "[planner] 跑完了但没有有效 plan 文件（last_tool={})。明天会回退默认 TASKS。",
            result.last_tool,
        )
        return False

    logger.info("[planner] ✓ 已保存 {} 条任务到 {}.json", len(plan.tasks), tomorrow.isoformat())
    return True


# ---------------------------------------------------------------------------
# Standalone entry: ``python -m hermes.planner`` — for manual debugging.
# ---------------------------------------------------------------------------

async def _main() -> None:
    ok = await run_planner()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
