"""Conversation agent — pure roleplay, only cares about what to say."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from agents import Agent, RunContextWrapper
from dotenv import load_dotenv

from core.context import AgentContext
from tools import send_message

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

PERSONA_PATH = Path(__file__).resolve().parent.parent / "personas" / "muse.yaml"


def _load_persona(path: Path = PERSONA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_instructions(persona: dict) -> str:
    if "instructions" in persona:
        return persona["instructions"].rstrip() + "\n\n" + (
            "你说话的方式是通过 send_message，每次想说一句就调一次，"
            "像发微信一样一条一条发。说完了就停，不用管别的。\n"
            "永远不要直接输出文字，所有话都走 send_message。"
        )

    # Fallback: structured fields
    identity = persona["identity"]
    personality = persona["personality"]
    style = persona["speaking_style"]
    traits = "\n".join(f"- {t}" for t in personality["traits"])
    emotions = "\n".join(f"- {e}" for e in personality["emotional_range"])
    habits = "\n".join(f"- {h}" for h in style["habits"])
    msg_pattern = "\n".join(f"- {p}" for p in style["message_pattern"])
    avoid = "\n".join(f"- {a}" for a in style["avoid"])

    return f"""\
{identity}。

{traits}

{emotions}

语气：{style['tone']}
{msg_pattern}
{habits}

绝对不要：
{avoid}

你说话的方式是通过 send_message，每次想说一句就调一次，
像发微信一样一条一条发。说完了就停，不用管别的。
永远不要直接输出文字，所有话都走 send_message。"""


def _dynamic_instructions(
    ctx: RunContextWrapper[AgentContext], agent: Agent[AgentContext]
) -> str:
    persona = _load_persona()
    return _build_instructions(persona)


def build_conversation_agent() -> Agent[AgentContext]:
    persona = _load_persona()
    return Agent[AgentContext](
        name=persona["name"],
        instructions=_dynamic_instructions,
        model=MODEL,
        tools=[send_message],
    )
