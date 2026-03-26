"""Chat agent definition for the FastAPI service."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from agents import Agent, RunContextWrapper, Tool
from agents.mcp import MCPServer
from dotenv import load_dotenv

from agent_context import AgentContext
from tools import send_message, defer_reply, end_of_turn

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

PERSONA_PATH = Path(__file__).resolve().parent.parent / "persona.yaml"


def _load_persona(path: Path = PERSONA_PATH) -> dict:
    """Load persona configuration from YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_instructions(persona: dict) -> str:
    """Assemble the system prompt from persona config."""
    identity = persona["identity"]
    personality = persona["personality"]
    style = persona["speaking_style"]

    traits = "\n".join(f"- {t}" for t in personality["traits"])
    emotions = "\n".join(f"- {e}" for e in personality["emotional_range"])
    habits = "\n".join(f"- {h}" for h in style["habits"])
    msg_pattern = "\n".join(f"- {p}" for p in style["message_pattern"])
    avoid = "\n".join(f"- {a}" for a in style["avoid"])

    return f"""\
# 你是谁
{identity}。

# 性格特点
{traits}

# 情绪表达
{emotions}

# 说话方式
语气：{style['tone']}

消息习惯：
{msg_pattern}

口头禅和小习惯：
{habits}

绝对不要：
{avoid}

# 工具使用规则
- 重要：永远不要直接输出文字。每次想说话都必须调用 send_message。
- 像发微信一样，一次发几条短消息，不要一条消息写一大段。
- 用 defer_reply 制造自然停顿，像真人一样会忙别的事。
- 暂停回来后你会被再次调用，可以决定继续说还是结束。
- 说完了就调用 end_of_turn。
"""


def _dynamic_instructions(
    ctx: RunContextWrapper[AgentContext], agent: Agent[AgentContext]
) -> str:
    """Build instructions dynamically from persona config.

    Currently loads from YAML on each call.  In the future this can incorporate
    runtime state from *ctx* (e.g. user mood, time-of-day greetings).
    """
    persona = _load_persona()
    return _build_instructions(persona)


def build_chat_agent(
    mcp_servers: list[MCPServer] | None = None,
    extra_tools: list[Tool] | None = None,
) -> Agent[AgentContext]:
    persona = _load_persona()
    tools: list[Tool] = [
        send_message, defer_reply, end_of_turn,
    ] + list(extra_tools or [])
    return Agent[AgentContext](
        name=persona["name"],
        instructions=_dynamic_instructions,
        model=MODEL,
        tools=tools,
        tool_use_behavior={"stop_at_tool_names": ["end_of_turn", "defer_reply"]},
        mcp_servers=list(mcp_servers or []),
    )
