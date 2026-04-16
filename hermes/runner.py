"""Entry point for scheduled Hermes runs."""

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
from core.trace import RunMeta, TraceRecorder, TraceSink, get_default_trace_sink, truncate_preview

load_dotenv()

_DIARY_TAG = re.compile(r"<diary>\s*(.+?)\s*</diary>", re.DOTALL)


def _extract_diary(response: str) -> str:
    m = _DIARY_TAG.search(response)
    if m:
        return m.group(1).strip()
    paragraphs = [p.strip() for p in response.strip().split("\n\n") if p.strip()]
    return paragraphs[-1] if paragraphs else response.strip()


def _resolve_hermes_config() -> tuple[str, str | None, str | None]:
    model = os.getenv("HERMES_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek-chat"
    base_url = os.getenv("HERMES_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("HERMES_API_KEY") or os.getenv("OPENAI_API_KEY")
    return model, base_url, api_key


def _task_recorder(
    title: str,
    *,
    trace_sink: TraceSink | None = None,
    run_kind: str = "hermes_task",
    run_id: str | None = None,
    start_seq: int = 0,
) -> TraceRecorder:
    return TraceRecorder(
        trace_sink or get_default_trace_sink(),
        RunMeta(
            run_kind=run_kind,
            source="hermes",
            run_id=run_id,
            start_seq=start_seq,
            context={"title": title},
        ),
    )


def run_single_task(
    title: str,
    instruction: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    trace_recorder: TraceRecorder | None = None,
    trace_sink: TraceSink | None = None,
) -> bool:
    """Run one Hermes task and append its diary entry. Returns True on success."""
    recorder = trace_recorder or _task_recorder(title, trace_sink=trace_sink)
    emit_run_boundary = trace_recorder is None or recorder.meta.run_kind == "hermes_task"

    if model is None:
        model, default_base, default_key = _resolve_hermes_config()
        base_url = base_url or default_base
        api_key = api_key or default_key

    if emit_run_boundary:
        recorder.emit_sync(
            lane="runtime",
            type="run.started",
            status="ok",
            summary=f"hermes task started: {title}",
            payload={"title": title, "model": model},
        )

    try:
        agent = AIAgent(
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_mode="chat_completions",
            quiet_mode=True,
            enabled_toolsets=["browser"],
            ephemeral_system_prompt=ANNA_VOICE_PROMPT,
            skip_memory=False,
            max_iterations=30,
        )
        response = agent.chat(instruction)
        if not response or not response.strip():
            raise RuntimeError("agent.chat returned empty response")

        entry = _extract_diary(response)
        if not entry:
            raise RuntimeError("no diary content after extraction")

        recorder.emit_sync(
            lane="runtime",
            type="runtime.response_received",
            status="ok",
            summary=f"hermes task produced response: {title}",
            payload={
                "title": title,
                "response_preview": truncate_preview(response),
                "diary_preview": truncate_preview(entry),
            },
        )
        append_entry(title, entry, trace_recorder=recorder)
        has_tag = "<diary>" in response
        logger.info("[hermes] ✓ {} ({})", title, "tagged" if has_tag else "fallback")

        if emit_run_boundary:
            recorder.emit_sync(
                lane="runtime",
                type="run.finished",
                status="ok",
                summary=f"hermes task finished: {title}",
                payload={"title": title},
            )
        return True
    except Exception as exc:
        logger.exception("[hermes] ✗ {} failed", title)
        append_entry(title, "（这件事今天没能做成，晚点再试。）", trace_recorder=recorder)
        if emit_run_boundary:
            recorder.emit_sync(
                lane="runtime",
                type="run.failed",
                status="error",
                summary=f"hermes task failed: {title}",
                payload={
                    "title": title,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
        return False


def run_slot(
    slot: str,
    *,
    trace_recorder: TraceRecorder | None = None,
    trace_sink: TraceSink | None = None,
    run_id: str | None = None,
    start_seq: int = 0,
) -> int:
    tasks = TASKS.get(slot)
    if tasks is None:
        logger.error("Unknown slot '{}'. Expected one of {}", slot, list(TASKS))
        return 2

    model, base_url, api_key = _resolve_hermes_config()
    recorder = trace_recorder or _task_recorder(
        slot,
        trace_sink=trace_sink,
        run_kind="hermes_slot",
        run_id=run_id,
        start_seq=start_seq,
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.started",
        status="ok",
        summary=f"hermes slot started: {slot}",
        payload={"slot": slot, "task_count": len(tasks), "model": model},
    )

    logger.info(
        "[hermes] {} slot: {} task(s), model={}, base_url={}",
        slot, len(tasks), model, base_url or "(hermes default)",
    )

    failed = 0
    for title, instruction in tasks:
        ok = run_single_task(
            title,
            instruction,
            model=model,
            base_url=base_url,
            api_key=api_key,
            trace_recorder=recorder,
        )
        if not ok:
            failed += 1

    recorder.emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok" if failed < len(tasks) else "error",
        summary=f"hermes slot finished: {slot}",
        payload={"slot": slot, "failed_count": failed, "task_count": len(tasks)},
    )
    return 1 if failed == len(tasks) else 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m hermes.runner <morning|noon|evening>", file=sys.stderr)
        sys.exit(2)
    sys.exit(run_slot(sys.argv[1]))


if __name__ == "__main__":
    main()
