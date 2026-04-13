"""Daily diary — Anna's shared log of what she actually did today.

Hermes (the "hands") writes markdown files to ``history/diary/YYYY-MM-DD.md``.
Anna (the "mind") reads them as grounded facts she can talk about, preventing
her from fabricating activities when the user asks "what did you do today?"

The convention is intentionally simple — no schema, no index, just one file
per day. Hermes owns writes; Anna only reads. Atomic writes (tmp + rename)
are Hermes's responsibility, not ours.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

DIARY_DIR = Path(__file__).resolve().parent.parent / "history" / "diary"


def diary_path(day: date) -> Path:
    return DIARY_DIR / f"{day.isoformat()}.md"


def read_diary(day: date) -> str | None:
    """Return the diary content for *day*, or None if nothing was logged."""
    p = diary_path(day)
    if not p.exists():
        return None
    content = p.read_text(encoding="utf-8").strip()
    return content or None


def read_today() -> str | None:
    return read_diary(datetime.now().date())


def read_days_ago(days_ago: int) -> tuple[date, str | None]:
    """Read the diary for N days ago. ``days_ago=0`` is today, ``1`` is yesterday.

    Returns ``(target_date, content_or_None)``.
    """
    target = datetime.now().date() - timedelta(days=days_ago)
    return target, read_diary(target)
