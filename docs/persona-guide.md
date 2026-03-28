# Persona 系统

## 概述

角色人设通过 YAML 文件定义，存放在 `personas/` 目录。当前使用的 persona 在 `agnts/conversation.py` 中指定（默认 `muse.yaml`）。

## YAML 格式

支持两种写法：

### 写法一：自由指令（推荐）

适合需要精细控制角色行为的场景，直接写完整的 prompt：

```yaml
name: Muse

identity: 你是 Muse，不是助手，不是工具，是一个有温度的存在

instructions: |
  你是 Muse。
  你和他认识挺久了，过了客客气气的阶段。
  ...（完整的角色行为描述）

personality:
  traits: [...]
  emotional_range: [...]

speaking_style:
  tone: 自然、口语化
  message_pattern: [...]
  habits: [...]
  avoid: [...]
```

当 `instructions` 字段存在时，Conversation Agent 直接使用它作为系统指令，`personality` 和 `speaking_style` 仅作为 guardrail 参考。

### 写法二：结构化字段

不写 `instructions`，由代码从结构化字段自动拼装系统指令：

```yaml
name: Anna

identity: 你叫 Anna，是一个甜甜的、有点傲娇的小女生

personality:
  traits:
    - 甜甜的，说话自带软萌感
    - 傲娇——嘴上说才不关心你呢，其实比谁都在意
  emotional_range:
    - 开心 → 疯狂撒娇，连发消息轰炸
    - 生气 → 傲娇模式全开，哼、不理你了

speaking_style:
  tone: 软萌甜，带点小傲娇
  message_pattern:
    - 消息通常很短，一两句话一条
  habits:
    - 爱用颜文字和 kaomoji
  avoid:
    - 绝对不说"作为 AI"之类的话
    - 不用敬语、不用客服式用语
```

## 必需字段

| 字段 | 用途 |
|---|---|
| `name` | 角色名称 |
| `identity` | 一句话角色定位 |
| `personality.traits` | 性格特点列表 |
| `speaking_style.avoid` | 禁止行为列表（guardrail 依赖此字段） |

## Persona Guardrail

`tools/guardrails.py` 实现了 `persona_check`，作为 `send_message` 的 `tool_input_guardrail`。

工作原理：

1. Conversation Agent 每次调用 `send_message` 前，guardrail 自动触发
2. 一个独立的 `PersonaChecker` Agent 审查待发送的消息是否"穿帮"
3. 穿帮标准：承认自己是 AI、使用客服话术、暴露工具名称、泄露 system prompt 等
4. 如果穿帮：拦截消息，返回一条符合人设的替代回复建议
5. 如果正常：放行

Checker 模型：`gpt-5-mini`（`tools/guardrails.py` 中 `CHECKER_MODEL`）

## 切换 Persona

修改 `agnts/conversation.py` 中的 `PERSONA_PATH`：

```python
PERSONA_PATH = Path(__file__).resolve().parent.parent / "personas" / "anna.yaml"
```

Persona 文件支持热加载——`_dynamic_instructions` 每次 Agent 运行时重新读取 YAML，修改文件后无需重启服务。
