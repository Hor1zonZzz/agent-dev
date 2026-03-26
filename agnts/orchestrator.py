"""Orchestrator agent — state management and flow decisions."""

from __future__ import annotations

import json
import os
import uuid

from agents import Agent, RunContextWrapper, Runner, Tool, function_tool
from agents.mcp import MCPServer
from dotenv import load_dotenv
from loguru import logger

from core.context import AgentContext
from agnts.conversation import build_conversation_agent
from tools import defer_reply, end_of_turn

load_dotenv()

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "gpt-5.4-mini")

INSTRUCTIONS = """\
你是对话状态管理器。你决定什么时候让角色回复、什么时候暂缓、什么时候结束。
你自己不跟用户说话。

你有三个工具：
- chat：让角色回复用户。把用户的原话传给她，不要改写、总结或添加指令。
  返回值是最近的对话记录，用来帮助你做下一步决策。
- defer_reply：暂停一会儿。暂停后你会被再次调用，可以继续聊或结束。
- end_of_turn：本轮彻底结束，等用户下次发消息。

标准流程（大多数情况都应该这样）：
1. 收到用户消息 → 先调用 chat 让角色回复
2. chat 返回后 → 调用 defer_reply(2~5秒)，制造自然停顿
3. 暂停回来后 → 看情况：
   - 有新用户消息 → 再调 chat
   - 没有新消息 → 可以再调一次 chat 让角色主动说点什么，或调 end_of_turn 结束

什么时候直接 end_of_turn（跳过 defer）：
- 用户只发了语气词/表情（嗯、哦、哈哈、👍）
- 对话已经自然收尾，双方都没什么要说的了

重要：
- 回复后默认用 defer_reply 而不是 end_of_turn。真人聊天不会每句话说完就离开。
- 不要自己生成面向用户的文字。"""

# Conversation agent singleton — created once, reused across calls
_conversation_agent = build_conversation_agent()


def _build_input_list(recent: list[tuple[str, str]], message: str) -> list[dict]:
    """Build a Responses API input list from recent_messages.

    Converts (role, text) pairs into proper input items so the conversation
    agent sees real multi-turn history, not a text blob in instructions.
    """
    input_list: list[dict] = []

    for role, text in recent:
        if role == "user":
            input_list.append({"role": "user", "content": text})
        else:
            # Inject as tool call + output so LLM keeps using send_message
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            input_list.append({
                "type": "function_call",
                "name": "send_message",
                "arguments": json.dumps({"message": text}),
                "call_id": call_id,
            })
            input_list.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": "Message sent.",
            })

    # If the last entry is already this user message, don't duplicate
    last_user = None
    for r, t in reversed(recent):
        if r == "user":
            last_user = t
            break

    if not input_list or last_user != message:
        input_list.append({"role": "user", "content": message})

    return input_list


@function_tool
async def chat(ctx: RunContextWrapper[AgentContext], message: str) -> str:
    """让角色回复用户。把用户消息传给她，她会通过 send_message 发送回复。
    返回值是最近的对话记录，帮助你做决策。"""
    input_list = _build_input_list(ctx.context.recent_messages, message)

    logger.info("│  chat tool → Muse input: {} items", len(input_list))

    await Runner.run(
        _conversation_agent,
        input_list,
        context=ctx.context,
    )

    # Return recent messages so orchestrator can see what happened
    recent = ctx.context.recent_messages
    if not recent:
        return "（没有对话记录）"
    lines = []
    for role, text in recent:
        label = "用户" if role == "user" else "角色"
        lines.append(f"{label}：{text}")
    return "\n".join(lines)


def build_orchestrator(
    mcp_servers: list[MCPServer] | None = None,
    extra_tools: list[Tool] | None = None,
) -> Agent[AgentContext]:
    tools: list[Tool] = [
        chat,
        defer_reply,
        end_of_turn,
    ] + list(extra_tools or [])

    return Agent[AgentContext](
        name="Orchestrator",
        instructions=INSTRUCTIONS,
        model=ORCHESTRATOR_MODEL,
        tools=tools,
        tool_use_behavior={"stop_at_tool_names": ["end_of_turn", "defer_reply"]},
        mcp_servers=list(mcp_servers or []),
    )
