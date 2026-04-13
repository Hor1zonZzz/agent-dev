"""Recall a past day's diary entries.

Today's diary is already injected into the system prompt, so this tool is
only for looking up *other* days — "what did I do yesterday?" / "two days
ago?" — when the user asks about the past.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.diary import read_days_ago
from core.tool import Tool


class RecallDayParams(BaseModel):
    days_ago: int = Field(
        description=(
            "How many days back to look. 1 = yesterday, 2 = the day before, "
            "etc. Do not use 0 — today is already in your system prompt."
        ),
        ge=1,
        le=365,
    )


def _recall_day(days_ago: int) -> str:
    target, content = read_days_ago(days_ago)
    if content is None:
        return f"{target.isoformat()} 没有日记记录。"
    return f"{target.isoformat()} 的日记：\n{content}"


recall_day = Tool(
    name="recall_day",
    description=(
        "Look up the diary for a past day to recall what you actually did. "
        "Use this whenever the user asks about something you did before today "
        "(yesterday, last week, etc.). Never fabricate past activities — if "
        "nothing was logged, say so."
    ),
    params=RecallDayParams,
    fn=_recall_day,
)
