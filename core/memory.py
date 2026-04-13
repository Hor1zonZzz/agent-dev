"""Memory compression — background LLM summarisation of conversation history."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

# ── Configuration ─────────────────────────────────────────────────────

HISTORY_DIR = Path(__file__).resolve().parent.parent / "history"

TOKEN_THRESHOLD = int(os.getenv("MEMORY_TOKEN_THRESHOLD", "8000"))
RECENT_K = int(os.getenv("MEMORY_RECENT_K", "40"))
SUMMARY_MODEL = os.getenv("MEMORY_SUMMARY_MODEL", "gpt-4o-mini")

_SUMMARY_DIMS = ("anna", "user", "shared")

_USER_KEYS = ("user_facts", "user_state", "user_preferences")
_ANNA_KEYS = ("anna_stance", "anna_commitments")
_SHARED_KEYS = ("topic_thread", "open_threads")

# ── Extraction prompt ─────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a memory extraction system for a companion chat agent named Anna.

Below is the complete conversation history between Anna and the user. \
Extract structured summaries into exactly 7 sections. Be concise but \
preserve all important information. Write in the same language the \
conversation uses (Chinese / English as appropriate).

For each section, include ONLY what is actually present in the conversation. \
If a section has no relevant information, write "（暂无）".

## user_facts
Factual information about the user: name, age, occupation, location, \
people they mentioned, events in their life. Bullet points.

## user_state
The user's CURRENT state as of the most recent messages: mood, what \
they're doing, energy level, what they seem to want from the conversation.

## user_preferences
User's expressed preferences, habits, likes/dislikes, and sensitive \
topics (things they don't want to discuss). Bullet points.

## anna_stance
Anna's current attitude / tone toward the user. How is she relating to \
them? Warm, cautious, playful, concerned?

## anna_commitments
Promises or commitments Anna has made: things she said she'd remember, \
follow up on, or do.

## topic_thread
Summary of conversation topics in chronological order. What was discussed, \
key points, how topics transitioned.

## open_threads
Unresolved topics, pending questions, things that were mentioned but not \
concluded. The user or Anna might want to return to these.

---

CONVERSATION HISTORY:
{conversation_json}
"""

# ── Public helpers ────────────────────────────────────────────────────


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: len(json_string) / 3."""
    return len(json.dumps(messages, ensure_ascii=False)) // 3


def load_latest_summary() -> str | None:
    """Read the most recent set of summary md files and combine them.

    Returns a combined markdown string, or *None* if no summaries exist.
    """
    # Collect timestamps from the user/ dir (all three dirs share timestamps)
    user_dir = HISTORY_DIR / "user"
    if not user_dir.is_dir():
        return None

    md_files = sorted(user_dir.glob("*.md"))
    if not md_files:
        return None

    latest_ts = md_files[-1].stem  # e.g. "20260410_143000"

    parts: list[str] = []
    for dim, label in (
        ("user", "About the user"),
        ("anna", "About Anna"),
        ("shared", "Conversation context"),
    ):
        path = HISTORY_DIR / dim / f"{latest_ts}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"### {label}\n{content}")

    return "\n\n".join(parts) if parts else None


def load_for_llm(history_path: Path) -> tuple[list[dict], str | None]:
    """Load messages for the LLM context window.

    Returns
    -------
    (recent_messages, memory_text)
        recent_messages : the last *RECENT_K* messages from history
        memory_text     : combined summary markdown, or None
    """
    full: list[dict] = []
    if history_path.exists():
        full = json.loads(history_path.read_text(encoding="utf-8"))

    memory_text = load_latest_summary()
    recent = full[-RECENT_K:] if full else []
    return recent, memory_text


def append_to_history(history_path: Path, new_messages: list[dict]) -> None:
    """Append *new_messages* to the history JSON file (never truncate)."""
    existing: list[dict] = []
    if history_path.exists():
        existing = json.loads(history_path.read_text(encoding="utf-8"))
    existing.extend(new_messages)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Background compression ───────────────────────────────────────────

_compress_task: asyncio.Task | None = None


async def maybe_compress(history_path: Path) -> None:
    """Spawn a background compression task if the history exceeds the token threshold."""
    global _compress_task

    if _compress_task is not None and not _compress_task.done():
        return  # already running

    if not history_path.exists():
        return

    messages = json.loads(history_path.read_text(encoding="utf-8"))
    if estimate_tokens(messages) <= TOKEN_THRESHOLD:
        return

    logger.info("Token threshold exceeded, spawning background compression")
    _compress_task = asyncio.create_task(_compress(history_path))


async def _compress(history_path: Path) -> None:
    """Background task: read history → call LLM → write summary md files."""
    try:
        raw = history_path.read_text(encoding="utf-8")
        prompt = EXTRACTION_PROMPT.format(conversation_json=raw)

        client = AsyncOpenAI()
        response = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""
        sections = _parse_summary_response(content)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        for dim in _SUMMARY_DIMS:
            _write_summary(dim, ts, sections[dim])

        logger.info("Memory compression complete: {}", ts)
    except Exception:
        logger.exception("Background memory compression failed")


# ── Internal helpers ──────────────────────────────────────────────────


def _parse_summary_response(content: str) -> dict[str, str]:
    """Parse an LLM response with ``## header`` sections into three groups."""
    raw_sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        m = re.match(r"^##\s+(\w+)", line)
        if m:
            if current_key:
                raw_sections[current_key] = "\n".join(current_lines).strip()
            current_key = m.group(1)
            current_lines = []
        else:
            current_lines.append(line)

    if current_key:
        raw_sections[current_key] = "\n".join(current_lines).strip()

    def _join(keys: tuple[str, ...]) -> str:
        parts = []
        for k in keys:
            if raw_sections.get(k):
                parts.append(f"### {k}\n{raw_sections[k]}")
        return "\n\n".join(parts) or "（暂无）"

    return {
        "user": _join(_USER_KEYS),
        "anna": _join(_ANNA_KEYS),
        "shared": _join(_SHARED_KEYS),
    }


def _write_summary(dimension: str, ts: str, content: str) -> None:
    dir_path = HISTORY_DIR / dimension
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{ts}.md").write_text(content, encoding="utf-8")
