"""Save Anna's plan for tomorrow (or today, if manually triggered before 23:00).

Anna uses this tool at the end of a planner run. On success the plan becomes
the schedule for the target day, overriding ``hermes/tasks.py`` defaults.

If validation fails, the error is returned to the LLM so Anna can correct
her plan and call ``save_plan`` again — the planner agent loop keeps going
until she either succeeds or gives up (end_turn).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from core.tool import Tool
from hermes.plan import PlanTask, validate_tasks, write_plan


class SavePlanParams(BaseModel):
    tasks: list[PlanTask] = Field(
        description=(
            "The plan for tomorrow — a list of small activities, each with "
            '"time" (HH:MM, 24h, between 06:30 and 22:30), "title" (short '
            'headline, <= 30 chars), and "instruction" (what Hermes should '
            "do, <= 500 chars). 1–6 tasks, strictly ascending times with "
            "at least 30 minutes between adjacent entries."
        ),
    )


def _save_plan(tasks: list[dict]) -> str:
    # ``core/tool.py`` calls ``parsed.model_dump()``, which recursively turns
    # nested Pydantic models into plain dicts before invoking the function.
    # Re-hydrate them here so validate_tasks sees real PlanTask objects.
    try:
        plan_tasks = [PlanTask.model_validate(t) for t in tasks]
    except Exception as e:
        return f"保存失败，task 字段格式不对：{e}"

    errors = validate_tasks(plan_tasks)
    if errors:
        return "保存失败，请修正后再调用 save_plan：\n- " + "\n- ".join(errors)

    # Planner always writes for the next calendar day. Stays consistent with
    # run_planner() which reads `now + 1 day`, regardless of what time the
    # planner was triggered (scheduled 23:00 or a manual debug run).
    day = (datetime.now() + timedelta(days=1)).date()
    path = write_plan(day, plan_tasks)
    return f"已保存 {len(plan_tasks)} 条任务到 {path.name}。"


save_plan = Tool(
    name="save_plan",
    description=(
        "Save your plan for tomorrow as a list of scheduled activities. "
        "Each task has a time (HH:MM), a short title, and an instruction "
        "telling Hermes what to do. Times must be between 06:30 and 22:30, "
        "strictly ascending, with at least 30 minutes between adjacent "
        "tasks. 1-6 tasks total. Call this once you've thought through "
        "what you want to do tomorrow."
    ),
    params=SavePlanParams,
    fn=_save_plan,
)
