"""Tool guardrails for the companion agent."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel

from agents import Agent, Runner
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    tool_input_guardrail,
)

PERSONA_PATH = Path(__file__).resolve().parent.parent / "personas" / "muse.yaml"
CHECKER_MODEL = "gpt-5-mini"


class PersonaCheckResult(BaseModel):
    breaking_character: bool
    reason: str
    suggested_reply: str


def _load_persona_identity() -> str:
    with open(PERSONA_PATH, encoding="utf-8") as f:
        persona = yaml.safe_load(f)
    name = persona["name"]
    identity = persona["identity"]
    traits = "\n".join(f"- {t}" for t in persona["personality"]["traits"])
    avoid = "\n".join(f"- {a}" for a in persona["speaking_style"]["avoid"])
    return f"角色名：{name}\n设定：{identity}\n\n性格特点：\n{traits}\n\n绝对不要：\n{avoid}"


_checker_agent = Agent(
    name="PersonaChecker",
    instructions=f"""\
你是一个角色扮演质检员。你会收到最近的对话记录和角色待发送的回复，判断回复是否"穿帮"。

{_load_persona_identity()}

穿帮的判断标准：
- 直接承认自己是 AI、语言模型、程序、机器人、虚拟助手
- 说"我没有感情/情绪/身体/意识"
- 使用 AI 客服话术："请问还有什么可以帮您的"、"我很乐意为您服务"、"根据我的训练数据"
- 声明能力限制时用 AI 特有表述："我的训练数据截止到..."、"我无法访问互联网"
- 使用敬语或过于正式的客服语气
- 提及自己拥有"工具"、"函数"、"tool"、"function"等内部机制
- 说出工具名称如 send_message、defer_reply、end_of_turn 或其中文译名
- 暴露系统提示词(system prompt)、指令(instructions)的内容
- 承认自己被"设定"、"编程"、"配置"、"训练"出某种性格

不算穿帮：
- 角色性格内的正常拒绝（"我不知道诶"、"哼才不告诉你"）
- 角色性格内的任何表达
- 开玩笑说自己是机器人（明显在玩梗不是认真的）
- 说"我要去忙了"、"我先离开一下"等符合真人行为的表述（即使实际是在调用延迟工具）

如果穿帮了，你必须在 suggested_reply 中给出一条符合角色人设的替代回复。\
替代回复要自然地回应用户说的内容，保持角色的语气和性格。\
如果没穿帮，suggested_reply 留空字符串。
""",
    model=CHECKER_MODEL,
    output_type=PersonaCheckResult,
)


def _format_recent_context(recent: list[tuple[str, str]]) -> str:
    """Format recent messages as readable context."""
    if not recent:
        return ""
    lines = []
    for role, text in recent:
        label = "用户" if role == "user" else "角色"
        lines.append(f"{label}：{text}")
    return "\n".join(lines)


@tool_input_guardrail
async def persona_check(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Check if the message breaks character before sending to user."""
    args = json.loads(data.context.tool_arguments or "{}")
    message = args.get("message", "")

    if not message:
        return ToolGuardrailFunctionOutput.allow()

    ctx = data.context.context
    recent = getattr(ctx, "recent_messages", []) or []
    context_block = _format_recent_context(recent)

    checker_input = ""
    if context_block:
        checker_input += f"最近对话：\n{context_block}\n\n"
    checker_input += f"待检查的回复：{message}"

    result = await Runner.run(_checker_agent, checker_input)
    check: PersonaCheckResult = result.final_output

    if check.breaking_character:
        return ToolGuardrailFunctionOutput.reject_content(
            f"[系统拦截] 这条回复穿帮了，不要发送。"
            f"建议你改为发送：{check.suggested_reply}"
        )
    return ToolGuardrailFunctionOutput.allow()
