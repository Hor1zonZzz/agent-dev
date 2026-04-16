"""System prompt builder — assembles sections into a complete system prompt."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.diary import read_today

_DIR = Path(__file__).parent


def _read(name: str) -> str:
    path = _DIR / name
    if not path.exists():
        return ""
    return path.read_text().strip()


def build(
    *,
    memory: str | None = None,
) -> str:
    """Assemble the system prompt from markdown sections.

    All .md files are read as-is — sub-agents maintain them directly.
    """
    sections: list[str] = []

    # 1. Soul — identity & personality (evolves over time)
    sections.append(_read("soul.md"))

    # 2. Guidelines — behavioral rules
    sections.append(_read("guidelines.md"))

    # 3. User Profile — who the user is
    sections.append(_read("user_profile.md"))

    # 4. Mood — current emotional tone
    sections.append(_read("mood.md"))

    # 5. Long-term Memory — placeholder for future
    if memory:
        sections.append(f"## Long-term memory\n{memory}")

    # 6. Today's diary — what Anna actually did today (written by Hermes).
    # If empty, Anna must acknowledge she hasn't done anything yet today
    # instead of fabricating. See the "Grounded activity" rule in guidelines.
    diary = read_today()
    if diary:
        sections.append(f"## 我今天做了这些\n{diary}")
    else:
        sections.append(
            "## 我今天做了这些\n"
            "（今天还没有记录。如果用户问起今天做了什么，诚实说还没开始 / 还没做什么，不要编。）"
        )

    # 7. Current time — refreshed on each build
    now = datetime.now().strftime("%Y-%m-%d %A %H:%M")
    sections.append(f"## Now\n{now}")

    return "\n\n".join(s for s in sections if s)
