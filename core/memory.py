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

COMPRESS_EVERY = int(os.getenv("MEMORY_COMPRESS_EVERY", "100"))
RECENT_K = int(os.getenv("MEMORY_RECENT_K", "40"))
SUMMARY_MODEL = os.getenv("MEMORY_SUMMARY_MODEL", "deepseek-reasoner")

_SUMMARY_DIMS = ("anna", "user", "shared")
_EMPTY_MARKER = "（暂无）"

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

INCREMENTAL_PROMPT = """\
You are a memory extraction system for a companion chat agent named Anna.

You have an EXISTING summary from a previous compression, and a batch of NEW \
MESSAGES that continue after it. Produce an UPDATED summary reflecting the \
current state. Write in the same language the conversation uses.

Rules for merging:
- PRESERVE from the existing summary any facts, preferences, or context that \
are still true and not contradicted by new messages.
- INTEGRATE new facts, state changes, commitments, and topics from the new messages.
- UPDATE entries that are superseded (e.g. mood changed, location changed).
- REMOVE items that are clearly resolved (e.g. an open thread that was answered).
- Only write "（暂无）" for a section if BOTH the existing summary AND the new \
messages have nothing relevant to it. If the existing summary had content and \
new messages add nothing, carry the existing content forward unchanged.

Output exactly the following 7 sections:

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
Anna's current attitude / tone toward the user. Warm, cautious, playful, concerned?

## anna_commitments
Promises or commitments Anna has made: things she said she'd remember, \
follow up on, or do.

## topic_thread
Summary of conversation topics in chronological order. What was discussed, \
key points, how topics transitioned.

## open_threads
Unresolved topics, pending questions, things that were mentioned but not concluded.

---

EXISTING SUMMARY:
{prev_summary}

NEW MESSAGES (json, continuation of the conversation):
{conversation_json}
"""

# ── Public helpers ────────────────────────────────────────────────────


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: len(json_string) / 3."""
    return len(json.dumps(messages, ensure_ascii=False)) // 3


def count_meaningful(messages: list[dict]) -> int:
    """Count user messages + send_message tool calls. Other roles/tools are noise."""
    n = 0
    for m in messages:
        role = m.get("role")
        if role == "user":
            n += 1
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                if (tc.get("function") or {}).get("name") == "send_message":
                    n += 1
    return n


def _latest_dim_content(dim: str) -> str | None:
    """Return the content of the most recent md file in ``history/{dim}/``."""
    dir_path = HISTORY_DIR / dim
    if not dir_path.is_dir():
        return None
    md_files = sorted(dir_path.glob("*.md"))
    if not md_files:
        return None
    content = md_files[-1].read_text(encoding="utf-8").strip()
    return content or None


def load_latest_summary() -> str | None:
    """Combine each dimension's most recent md (independent per dim) into one markdown."""
    parts: list[str] = []
    for dim, label in (
        ("user", "About the user"),
        ("anna", "About Anna"),
        ("shared", "Conversation context"),
    ):
        content = _latest_dim_content(dim)
        if content and content != _EMPTY_MARKER:
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
    recent = _trim_orphan_tool_prefix(recent)
    return recent, memory_text


def _trim_orphan_tool_prefix(messages: list[dict]) -> list[dict]:
    """Drop leading ``role=tool`` messages whose matching ``tool_calls`` got
    sliced out of the window. OpenAI-compatible APIs reject histories where a
    tool response has no preceding ``assistant`` message with ``tool_calls``.
    """
    i = 0
    while i < len(messages) and messages[i].get("role") == "tool":
        i += 1
    return messages[i:]


# ── Sidecar meta (last_activity_at, etc.) ────────────────────────────


def _meta_path(history_path: Path) -> Path:
    """Return the sibling ``.meta.json`` path for a history file."""
    return history_path.with_suffix(".meta.json")


def load_meta(history_path: Path) -> dict:
    p = _meta_path(history_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read meta at {}, ignoring", p)
        return {}


def save_meta(history_path: Path, meta: dict) -> None:
    p = _meta_path(history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_iso(history_path: Path, key: str) -> datetime | None:
    s = load_meta(history_path).get(key)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _set_iso(history_path: Path, key: str, when: datetime | None = None) -> None:
    meta = load_meta(history_path)
    meta[key] = (when or datetime.now()).isoformat()
    save_meta(history_path, meta)


def get_last_activity(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "last_activity_at")


def update_last_activity(history_path: Path, when: datetime | None = None) -> None:
    _set_iso(history_path, "last_activity_at", when)


def get_last_anna_message(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "last_anna_message_at")


def update_last_anna_message(history_path: Path, when: datetime | None = None) -> None:
    _set_iso(history_path, "last_anna_message_at", when)


def get_next_proactive_at(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "next_proactive_at")


def update_next_proactive_at(history_path: Path, when: datetime) -> None:
    _set_iso(history_path, "next_proactive_at", when)


def update_dispatch_info(
    history_path: Path,
    user_id: str,
    context_token: str | None,
) -> None:
    """Persist the raw user_id and most recent context_token so the proactive
    loop can dispatch outbound messages without an inbound message first."""
    meta = load_meta(history_path)
    meta["user_id"] = user_id
    if context_token is not None:
        meta["context_token"] = context_token
    save_meta(history_path, meta)


def get_dispatch_info(history_path: Path) -> tuple[str | None, str | None]:
    meta = load_meta(history_path)
    return meta.get("user_id"), meta.get("context_token")


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
    """Spawn a background compression task once the slice since the last compression
    accumulates COMPRESS_EVERY meaningful messages (user turns + send_message calls)."""
    global _compress_task

    if _compress_task is not None and not _compress_task.done():
        return

    if not history_path.exists():
        return

    messages = json.loads(history_path.read_text(encoding="utf-8"))
    start_idx = int(load_meta(history_path).get("last_compressed_at_index", 0))
    new_slice = messages[start_idx:]
    if count_meaningful(new_slice) < COMPRESS_EVERY:
        return

    end_idx = len(messages)
    logger.info(
        "Spawning memory compression: messages[{}:{}] ({} meaningful)",
        start_idx, end_idx, count_meaningful(new_slice),
    )
    _compress_task = asyncio.create_task(_compress(history_path, start_idx, end_idx))


async def _compress(history_path: Path, start_idx: int = 0, end_idx: int | None = None) -> None:
    """Background task: slice history → call LLM (incremental if prior summary exists)
    → write only non-empty dimension md files → advance the meta pointer on success."""
    try:
        messages = json.loads(history_path.read_text(encoding="utf-8"))
        if end_idx is None:
            end_idx = len(messages)
        slice_messages = messages[start_idx:end_idx]
        slice_json = json.dumps(slice_messages, ensure_ascii=False, indent=2)

        prev_summary = load_latest_summary()
        if prev_summary:
            prompt = INCREMENTAL_PROMPT.format(
                prev_summary=prev_summary,
                conversation_json=slice_json,
            )
        else:
            prompt = EXTRACTION_PROMPT.format(conversation_json=slice_json)

        client = AsyncOpenAI()
        response = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""
        sections = _parse_summary_response(content)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        written: list[str] = []
        for dim in _SUMMARY_DIMS:
            if sections[dim] and sections[dim] != _EMPTY_MARKER:
                _write_summary(dim, ts, sections[dim])
                written.append(dim)

        meta = load_meta(history_path)
        meta["last_compressed_at_index"] = end_idx
        save_meta(history_path, meta)

        logger.info(
            "Memory compression complete: ts={}, wrote={}, pointer→{}",
            ts, written or "(all empty)", end_idx,
        )
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
