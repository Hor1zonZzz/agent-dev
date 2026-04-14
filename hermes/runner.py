"""Entry point for scheduled Hermes runs.

Usage::

    python -m hermes.runner morning
    python -m hermes.runner noon
    python -m hermes.runner evening

Triggered by crontab. Each invocation instantiates a fresh ``AIAgent`` per
task (per Hermes docs: agents are not thread/task-safe), runs the task,
writes the response into today's diary, then exits.

Model and other Hermes config are read from environment variables the same
way as the Hermes CLI (``OPENAI_API_KEY``, ``OPENAI_BASE_URL``, or
``OPENROUTER_API_KEY``). Our own ``HERMES_MODEL`` env lets you pick the
Hermes-side model without touching the main Anna config.
"""

from __future__ import annotations

import os
import re
import sys

from dotenv import load_dotenv
from loguru import logger
from run_agent import AIAgent

from hermes.diary import append_entry
from hermes.prompt import ANNA_VOICE_PROMPT
from hermes.tasks import TASKS

load_dotenv()

_DIARY_TAG = re.compile(r"<diary>\s*(.+?)\s*</diary>", re.DOTALL)


def _extract_diary(response: str) -> str:
    """Pull the Anna-voice text out of <diary>...</diary>. Falls back to the
    last non-empty paragraph if the tag is missing — weaker models sometimes
    drop the wrapper even when prompted.
    """
    m = _DIARY_TAG.search(response)
    if m:
        return m.group(1).strip()
    # Fallback: last paragraph (heuristic; weaker models without the tag).
    paragraphs = [p.strip() for p in response.strip().split("\n\n") if p.strip()]
    return paragraphs[-1] if paragraphs else response.strip()


def _resolve_hermes_config() -> tuple[str, str | None, str | None]:
    """Return (model, base_url, api_key) for Hermes AIAgent instantiation."""
    model = os.getenv("HERMES_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek-chat"
    base_url = os.getenv("HERMES_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("HERMES_API_KEY") or os.getenv("OPENAI_API_KEY")
    return model, base_url, api_key


def run_single_task(
    title: str,
    instruction: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> bool:
    """Run one Hermes task and append its diary entry. Returns True on success.

    On any failure the fallback "（这件事今天没能做成，晚点再试。）" line is
    appended so the day's diary doesn't silently miss an entry.
    """
    if model is None:
        model, default_base, default_key = _resolve_hermes_config()
        base_url = base_url or default_base
        api_key = api_key or default_key

    try:
        # Fresh instance per task — Hermes docs say don't share across tasks.
        agent = AIAgent(
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_mode="chat_completions",  # force OpenAI-style, not codex
            quiet_mode=True,
            enabled_toolsets=["browser"],  # "web" toolset needs paid API keys; browser is self-contained
            ephemeral_system_prompt=ANNA_VOICE_PROMPT,
            skip_memory=False,  # share ~/.hermes/ with user's regular Hermes
            max_iterations=30,
        )
        response = agent.chat(instruction)
        # Hermes chat() returns None or empty string on failures that it
        # swallowed internally. Treat those as failures rather than crashing.
        if not response or not response.strip():
            raise RuntimeError("agent.chat returned empty response")
        entry = _extract_diary(response)
        if not entry:
            raise RuntimeError("no diary content after extraction")
        append_entry(title, entry)
        has_tag = "<diary>" in response
        logger.info("[hermes] ✓ {} ({})", title, "tagged" if has_tag else "fallback")
        return True
    except Exception:
        logger.exception("[hermes] ✗ {} failed", title)
        append_entry(title, "（这件事今天没能做成，晚点再试。）")
        return False


def run_slot(slot: str) -> int:
    tasks = TASKS.get(slot)
    if tasks is None:
        logger.error("Unknown slot '{}'. Expected one of {}", slot, list(TASKS))
        return 2

    model, base_url, api_key = _resolve_hermes_config()

    logger.info(
        "[hermes] {} slot: {} task(s), model={}, base_url={}",
        slot, len(tasks), model, base_url or "(hermes default)",
    )

    failed = 0
    for title, instruction in tasks:
        ok = run_single_task(title, instruction, model=model, base_url=base_url, api_key=api_key)
        if not ok:
            failed += 1

    return 1 if failed == len(tasks) else 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m hermes.runner <morning|noon|evening>", file=sys.stderr)
        sys.exit(2)
    sys.exit(run_slot(sys.argv[1]))


if __name__ == "__main__":
    main()
