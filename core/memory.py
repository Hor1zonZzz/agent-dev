"""Memory compression — background LLM summarisation of conversation history."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

from core.history import append_to_history, load_recent_messages
from core.meta import (
    get_dispatch_info,
    get_last_activity,
    get_last_anna_message,
    get_next_proactive_at,
    load_meta,
    save_meta,
    update_dispatch_info,
    update_last_activity,
    update_last_anna_message,
    update_next_proactive_at,
)
from core.trace import RunMeta, TraceRecorder, TraceSink, get_default_trace_sink

# ── Configuration ─────────────────────────────────────────────────────

HISTORY_DIR = Path(__file__).resolve().parent.parent / "history"

COMPRESS_EVERY = int(os.getenv("MEMORY_COMPRESS_EVERY", "100"))
IDLE_COMPRESS_MINUTES = int(os.getenv("MEMORY_IDLE_COMPRESS_MINUTES", "60"))
WATCHDOG_INTERVAL_SECONDS = int(os.getenv("MEMORY_WATCHDOG_INTERVAL_SECONDS", "300"))
RECENT_K = int(os.getenv("MEMORY_RECENT_K", "140"))
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
    return load_recent_messages(history_path, RECENT_K), load_latest_summary()


# ── Background compression ───────────────────────────────────────────

_compress_task: asyncio.Task | None = None


def _latest_activity(meta: dict) -> datetime | None:
    """Latest timestamp from either side — user msg or Anna's reply."""
    stamps: list[datetime] = []
    for key in ("last_activity_at", "last_anna_message_at"):
        s = meta.get(key)
        if not s:
            continue
        try:
            stamps.append(datetime.fromisoformat(s))
        except ValueError:
            continue
    return max(stamps) if stamps else None


async def maybe_compress(history_path: Path, trace_sink: TraceSink | None = None) -> None:
    """Spawn a background compression task when either:
    - buffer_full: COMPRESS_EVERY meaningful messages accumulated since last compression, or
    - idle: both sides have been silent for >= IDLE_COMPRESS_MINUTES and there is new content.

    On success `_compress` advances `last_compressed_at_index`, so the next run starts
    counting from scratch regardless of which trigger fired.
    """
    global _compress_task

    if _compress_task is not None and not _compress_task.done():
        return

    if not history_path.exists():
        return

    messages = json.loads(history_path.read_text(encoding="utf-8"))
    meta = load_meta(history_path)
    start_idx = int(meta.get("last_compressed_at_index", 0))
    new_slice = messages[start_idx:]
    meaningful = count_meaningful(new_slice)

    if meaningful == 0:
        return

    buffer_full = meaningful >= COMPRESS_EVERY

    idle = False
    last = _latest_activity(meta)
    if last is not None:
        if datetime.now() - last >= timedelta(minutes=IDLE_COMPRESS_MINUTES):
            idle = True

    if not (buffer_full or idle):
        return

    end_idx = len(messages)
    reason = "buffer_full" if buffer_full else "idle"
    logger.info(
        "Spawning memory compression: reason={}, messages[{}:{}] ({} meaningful)",
        reason, start_idx, end_idx, meaningful,
    )
    _compress_task = asyncio.create_task(
        _compress(history_path, start_idx, end_idx, trace_sink=trace_sink or get_default_trace_sink())
    )


async def compression_watchdog(
    history_dir: Path,
    *,
    trace_sink: TraceSink | None = None,
) -> None:
    """Forever-loop: periodically check every history file in ``history_dir`` for
    the idle-compression trigger. Complements the inline post-turn check in worker
    — necessary because idle time elapses without any event to hook into."""
    logger.info(
        "[compress-watchdog] loop started (interval={}s, idle_threshold={}min)",
        WATCHDOG_INTERVAL_SECONDS, IDLE_COMPRESS_MINUTES,
    )
    while True:
        try:
            if history_dir.is_dir():
                for history_path in history_dir.glob("*.json"):
                    if history_path.name.endswith(".meta.json"):
                        continue
                    await maybe_compress(history_path, trace_sink=trace_sink)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[compress-watchdog] scan failed; continuing")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)


async def _compress(
    history_path: Path,
    start_idx: int = 0,
    end_idx: int | None = None,
    *,
    trace_sink: TraceSink | None = None,
) -> None:
    """Background task: slice history → call LLM (incremental if prior summary exists)
    → write only non-empty dimension md files → advance the meta pointer on success."""
    recorder = TraceRecorder(
        trace_sink or get_default_trace_sink(),
        RunMeta(
            run_kind="memory_compress",
            source="memory",
            context={"history_path": str(history_path)},
        ),
    )
    await recorder.emit(
        lane="memory",
        type="memory.compression_started",
        status="ok",
        summary=f"memory compression started for {history_path.name}",
        payload={"start_idx": start_idx, "end_idx": end_idx},
    )
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
                path = _write_summary(dim, ts, sections[dim])
                written.append(dim)
                await recorder.emit(
                    lane="artifact",
                    type="artifact.written",
                    status="ok",
                    summary=f"memory summary written: {path.name}",
                    payload={
                        "artifact_kind": "memory_summary",
                        "dimension": dim,
                        "path": str(path),
                    },
                )

        meta = load_meta(history_path)
        meta["last_compressed_at_index"] = end_idx
        save_meta(history_path, meta)

        logger.info(
            "Memory compression complete: ts={}, wrote={}, pointer→{}",
            ts, written or "(all empty)", end_idx,
        )
        await recorder.emit(
            lane="memory",
            type="memory.compression_finished",
            status="ok",
            summary=f"memory compression finished for {history_path.name}",
            payload={
                "written_dimensions": written,
                "last_compressed_at_index": end_idx,
            },
        )
    except Exception as exc:
        await recorder.emit(
            lane="memory",
            type="memory.compression_failed",
            status="error",
            summary=f"memory compression failed for {history_path.name}",
            payload={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
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


def _write_summary(dimension: str, ts: str, content: str) -> Path:
    dir_path = HISTORY_DIR / dimension
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path
