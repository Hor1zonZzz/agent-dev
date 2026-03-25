"""FastAPI service entrypoint with WebSocket-based companion agent."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import tracing
from agents import Runner, SQLiteSession
from loguru import logger
from agents.mcp import MCPServerManager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_context import AgentContext
from crew import MODEL, build_chat_agent
from context_policy import build_run_config
from mcp_servers import build_servers


@dataclass
class RuntimeState:
    active_servers: int
    chat_agent: Any
    run_config: Any


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    mcp_servers = build_servers()
    run_config = build_run_config()

    async with MCPServerManager(mcp_servers, strict=False) as manager:
        app.state.runtime = RuntimeState(
            active_servers=len(manager.active_servers),
            chat_agent=build_chat_agent(manager.active_servers),
            run_config=run_config,
        )
        try:
            yield
        finally:
            tracing.tracer_provider.force_flush()


app = FastAPI(lifespan=lifespan)
UI_DIR = Path(__file__).resolve().parent / "ui"


@app.get("/health")
async def health() -> dict[str, Any]:
    runtime = app.state.runtime
    return {
        "status": "ok",
        "model": MODEL,
        "active_servers": runtime.active_servers,
    }


def _drain_inbox(inbox: asyncio.Queue[str | None]) -> list[str]:
    """Non-blocking drain of all pending user messages."""
    messages: list[str] = []
    while not inbox.empty():
        msg = inbox.get_nowait()
        if msg is not None:
            messages.append(msg)
    return messages


@app.websocket("/ws")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime: RuntimeState = app.state.runtime

    session_id = uuid.uuid4().hex
    session = SQLiteSession(session_id=session_id, db_path="chat.db")
    inbox: asyncio.Queue[str | None] = asyncio.Queue()
    ctx = AgentContext(websocket=websocket, inbox=inbox)

    logger.info("WebSocket connected | session={}", session_id)
    await websocket.send_json({"type": "session", "session_id": session_id})

    async def reader() -> None:
        """Read WebSocket messages into inbox."""
        try:
            while True:
                data = await websocket.receive_json()
                msg = data.get("message", "")
                if msg:
                    await inbox.put(msg)
        except (WebSocketDisconnect, Exception):
            await inbox.put(None)

    reader_task = asyncio.create_task(reader())

    try:
        while True:
            # Wait for user message
            message = await inbox.get()
            if message is None:
                break

            # Agent loop: run → defer → run → ... → end_of_turn
            agent_input: str = message
            run_count = 0
            while True:
                run_count += 1
                logger.info("Agent run #{} start | input={}", run_count, agent_input[:80])
                await websocket.send_json({"type": "status", "status": "typing"})
                result = await Runner.run(
                    runtime.chat_agent,
                    agent_input,
                    context=ctx,
                    run_config=runtime.run_config,
                    session=session,
                )

                output = result.final_output or ""
                logger.info("Agent run #{} end | output={}", run_count, output)

                if output.startswith("defer:"):
                    seconds = int(output.split(":")[1])
                    logger.info("Defer triggered | waiting {}s", seconds)
                    await asyncio.sleep(seconds)
                    await websocket.send_json({"type": "status", "status": "online"})

                    new_messages = _drain_inbox(inbox)
                    if new_messages:
                        agent_input = "User sent new messages:\n" + "\n".join(new_messages)
                        logger.info("Inbox has {} new message(s)", len(new_messages))
                    else:
                        agent_input = (
                            "No new messages from user. "
                            "You can proactively say something or call end_of_turn."
                        )
                        logger.info("Inbox empty, prompting agent for proactive action")
                else:
                    logger.info("Turn ended after {} run(s)", run_count)
                    break

    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        session.close()
        tracing.tracer_provider.force_flush()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
