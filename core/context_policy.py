"""Context assembly policy for chat runs."""

from __future__ import annotations

from agents import RunConfig
from agents.run_config import CallModelData, ModelInputData
from loguru import logger


def call_model_input_filter(data: CallModelData) -> ModelInputData:
    """Inject pending user messages from inbox before each LLM call."""
    ctx = data.context
    if ctx is None or not hasattr(ctx, "inbox"):
        return data.model_data

    messages: list[str] = []
    while not ctx.inbox.empty():
        msg = ctx.inbox.get_nowait()
        if msg is not None:
            messages.append(msg)

    if messages:
        logger.info("Injecting {} inbox message(s) into LLM input", len(messages))
        for msg in messages:
            ctx.record("user", msg)
            data.model_data.input.append({"role": "user", "content": msg})

    return data.model_data


def build_run_config() -> RunConfig:
    return RunConfig(
        call_model_input_filter=call_model_input_filter,
    )
