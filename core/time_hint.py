"""Format time-gap hints for conversation re-engagement.

The hint is a short natural-language annotation (e.g. ``[3 天没说话了]``)
prepended to a user message when the agent resumes a conversation after a
meaningful silence. The goal is to give the model *feeling* of time, not
precision — so the output is bucketed by human-scale intervals.
"""

from __future__ import annotations

from datetime import timedelta


def format_gap_hint(delta: timedelta) -> str | None:
    """Return a natural-language gap hint, or None if the gap is too small.

    Gaps under 2 minutes are treated as an active conversation and get no
    annotation (noise in rapid back-and-forth).
    """
    secs = delta.total_seconds()
    if secs < 120:
        return None

    mins = secs / 60
    hours = mins / 60
    days = hours / 24

    if mins < 30:
        return "[刚聊过没多久]"
    if hours < 1:
        return f"[距上次说话 {int(mins)} 分钟]"
    if hours < 12:
        return f"[距上次说话 {int(hours)} 小时]"
    if hours < 24:
        return "[距上次说话已过半天]"
    if days < 2:
        return "[距上次说话约一天]"
    if days < 3:
        return "[距上次说话约两天]"
    if days < 14:
        return f"[{int(days)} 天没说话了]"

    weeks = int(days / 7)
    return f"[好久没联系了，约 {weeks} 周]"
