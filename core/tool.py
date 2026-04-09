"""Lightweight tool abstraction using pydantic_function_tool for schema generation."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from openai.lib._tools import pydantic_function_tool
from pydantic import BaseModel


@dataclass(frozen=True)
class Tool:
    """A tool that an Agent can call.

    - ``params`` is a Pydantic model whose schema is sent to the LLM.
    - ``fn`` is the implementation.  If its first parameter is annotated as
      (or named) ``ctx``, the runtime context will be injected automatically;
      remaining kwargs come from the parsed ``params`` model.
    """

    name: str
    description: str
    params: type[BaseModel]
    fn: Callable[..., Any]

    # ── schema ──────────────────────────────────────────────

    def to_openai(self) -> dict:
        """Return the ``tools=[...]`` element for Chat Completions."""
        return pydantic_function_tool(
            self.params,
            name=self.name,
            description=self.description,
        )

    # ── execution ───────────────────────────────────────────

    async def execute(self, arguments: str, ctx: Any = None) -> str:
        """Parse *arguments* (JSON string from LLM), call *fn*, return result."""
        parsed = self.params.model_validate_json(arguments)
        kwargs = parsed.model_dump()

        sig = inspect.signature(self.fn)
        params = list(sig.parameters.keys())
        if params and params[0] == "ctx":
            result = self.fn(ctx, **kwargs)
        else:
            result = self.fn(**kwargs)

        if inspect.isawaitable(result):
            result = await result

        return str(result)
