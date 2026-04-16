"""Conversation history persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path


def load_recent_messages(history_path: Path, limit: int) -> list[dict]:
    if not history_path.exists():
        return []
    full = json.loads(history_path.read_text(encoding="utf-8"))
    recent = full[-limit:] if full else []
    return trim_orphan_tool_prefix(recent)


def trim_orphan_tool_prefix(messages: list[dict]) -> list[dict]:
    i = 0
    while i < len(messages) and messages[i].get("role") == "tool":
        i += 1
    return messages[i:]


def append_to_history(history_path: Path, new_messages: list[dict]) -> None:
    existing: list[dict] = []
    if history_path.exists():
        existing = json.loads(history_path.read_text(encoding="utf-8"))
    existing.extend(new_messages)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
