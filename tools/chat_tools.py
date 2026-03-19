"""Tools for chat agent interaction control."""

from agents import function_tool


@function_tool
def response_to_user(message: str) -> str:
    """Send a message to the user. Call this tool every time you want to say something.
    You may call it multiple times to send follow-up messages."""
    return message


@function_tool
def end_of_turn() -> str:
    """Signal that you are done with this turn. Call this after you have finished
    sending all messages via response_to_user."""
    return "end_of_turn"
