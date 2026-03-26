"""FastAPI service entrypoint with WebSocket-based companion agent."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from core import tracing
from agents import Runner, SQLiteSession
from agents.memory import OpenAIResponsesCompactionSession
from loguru import logger
from agents.mcp import MCPServerManager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import AgentContext, build_run_config, CompanionHooks
from agnts import MODEL, build_orchestrator
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
            chat_agent=build_orchestrator(manager.active_servers),
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


@app.websocket("/ws")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime: RuntimeState = app.state.runtime

    session_id = uuid.uuid4().hex
    sqlite_session = SQLiteSession(session_id=session_id, db_path="chat.db")
    session = OpenAIResponsesCompactionSession(
        session_id=session_id, underlying_session=sqlite_session,
    )
    inbox: asyncio.Queue[str | None] = asyncio.Queue()
    ctx = AgentContext(websocket=websocket, inbox=inbox)
    hooks = CompanionHooks()

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
            ctx.last_user_input = message
            ctx.record("user", message)
            logger.info("══ User message: {}", message[:100])
            run_count = 0
            while True:
                run_count += 1
                logger.info("── Orchestrator run #{} | input={}", run_count, agent_input[:100])
                result = await Runner.run(
                    runtime.chat_agent,
                    agent_input,
                    context=ctx,
                    run_config=runtime.run_config,
                    session=session,
                    hooks=hooks,
                )

                output = result.final_output or ""

                if output.startswith("defer:"):
                    seconds = int(output.split(":")[1])
                    logger.info("── Defer | {}s, checking inbox after sleep", seconds)
                    await asyncio.sleep(seconds)
                    await websocket.send_json({"type": "status", "status": "online"})

                    pending = inbox.qsize()
                    logger.info("── Back online | {} pending message(s) in inbox", pending)

                    # New user messages (if any) will be auto-injected by
                    # call_model_input_filter before the next LLM call.
                    agent_input = (
                        "You are back after a pause. "
                        "Decide whether to say something or call end_of_turn."
                    )
                else:
                    logger.info("══ Turn ended after {} run(s)", run_count)
                    break

    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        sqlite_session.close()
        tracing.tracer_provider.force_flush()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
