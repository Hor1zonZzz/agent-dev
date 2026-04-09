"""Send a message to the user."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.tool import Tool


class SendMessageParams(BaseModel):
    message: str = Field(description="The message text to send to the user.")


def _send_message(message: str) -> str:
    print(f"Anna: {message}")
    return "Message sent."


send_message = Tool(
    name="send_message",
    description=(
        "Send a message to the user. Call this every time you want to say something. "
        "You can call it multiple times to send separate chat bubbles."
    ),
    params=SendMessageParams,
    fn=_send_message,
)
