"""Tools for companion agent interaction."""

from __future__ import annotations

from agents import RunContextWrapper, function_tool
from loguru import logger

from agent_context import AgentContext


@function_tool
async def send_message(ctx: RunContextWrapper[AgentContext], message: str) -> str:
    """Send a message to the user. Call this every time you want to say something.
    You can call it multiple times to send separate chat bubbles."""
    logger.info("send_message | {}", message[:80])
    await ctx.context.websocket.send_json({"type": "message", "text": message})
    return "Message sent."


@function_tool
async def defer_reply(ctx: RunContextWrapper[AgentContext], seconds: int) -> str:
    """Pause the conversation for a while before deciding what to do next.
    Use this to create natural pacing, like a real person taking a break.
    After the pause, you will be called again with any new user messages."""
    logger.info("defer_reply | {}s", seconds)
    await ctx.context.websocket.send_json({"type": "status", "status": "away"})
    return f"defer:{seconds}"


@function_tool
def end_of_turn() -> str:
    """Signal that you are done and will wait for the user to speak next."""
    logger.info("end_of_turn")
    return "end_of_turn"
