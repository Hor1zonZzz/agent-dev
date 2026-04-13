"""Signal that the agent is done and will wait for the user to speak next."""

from __future__ import annotations

from pydantic import BaseModel

from core.tool import Tool


class EndTurnParams(BaseModel):
    pass


def _end_turn() -> str:
    return "end_turn"


end_turn = Tool(
    name="end_turn",
    description="Signal that you are done speaking and will wait for the user's next message.",
    params=EndTurnParams,
    fn=_end_turn,
)
