"""System prompt builder — assembles sections into a complete system prompt."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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

    # 6. Current date — refreshed on each build
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    sections.append(f"## Current date\nToday is {today}.")

    return "\n\n".join(s for s in sections if s)
