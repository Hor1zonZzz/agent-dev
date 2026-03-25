"""Context assembly policy for chat runs."""

from __future__ import annotations

from agents import RunConfig, SessionSettings
from agents.items import TResponseInputItem
from agents.run_config import CallModelData, ModelInputData
from loguru import logger

# Maximum number of items to retrieve from session storage
SESSION_ITEM_LIMIT = 20
# Maximum number of user turns to keep (each turn = user msg + tool calls + assistant reply)
MAX_TURNS = 10


def _split_turns(items: list[TResponseInputItem]) -> list[list[TResponseInputItem]]:
    """Split a flat item list into turns, each starting with a user message."""
    turns: list[list[TResponseInputItem]] = []
    for item in items:
        is_user = isinstance(item, dict) and item.get("role") == "user"
        if is_user:
            turns.append([item])
        elif turns:
            turns[-1].append(item)
        # items before the first user message are dropped
    return turns


def session_input_callback(
    history: list[TResponseInputItem], new_input: list[TResponseInputItem]
) -> list[TResponseInputItem]:
    turns = _split_turns(history)
    kept = turns[-MAX_TURNS:] if len(turns) > MAX_TURNS else turns
    result = [item for turn in kept for item in turn] + new_input
    return result


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
            data.model_data.input.append({"role": "user", "content": msg})

    return data.model_data


def build_run_config() -> RunConfig:
    return RunConfig(
        session_input_callback=session_input_callback,
        session_settings=SessionSettings(limit=SESSION_ITEM_LIMIT),
        call_model_input_filter=call_model_input_filter,
    )
