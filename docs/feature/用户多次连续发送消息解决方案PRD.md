# 用户多次连续发送消息解决方案 PRD

## 问题陈述

当前系统在处理用户连续发送多条消息时存在两个核心缺陷：

1. **agent 回复是瞬时的**：`send_message` 直接通过 WebSocket 推送，多条气泡几乎同时到达，没有真人打字的节奏感。
2. **agent 回复期间是"盲"的**：当 conversation agent 在执行 `send_message × N` 的过程中，用户新发的消息被放入 inbox，但要等整个 agent run 结束、orchestrator 获取控制权后才能被感知和处理。

这导致用户体验偏离"像朋友发微信"的核心设计目标。

## 目标

- **G1**：消息气泡之间有自然的打字延迟，用户能看到"对方正在输入"后消息弹出
- **G2**：用户在 agent 回复期间发送的新消息，能在合理的延迟内被 orchestrator 感知并做出决策
- **G3**：维持双 agent 架构的职责分离——conversation agent 负责内容，orchestrator 负责流程决策
- **G4**：为后续演进（粒度控制、实时感知）预留架构空间

## 非目标

- **不在 conversation agent 层注入 inbox 消息**：经过架构讨论，`call_model_input_filter` 只作用于 orchestrator 的 `Runner.run()`。理由：避免 conversation agent 绕过 orchestrator 直接回复用户消息，破坏流程控制权的统一性
- **不实现中途中断+重启**（策略 B）：当前阶段采用温和方案，不在 send_message 的打字延迟中检测 inbox 并中断后续 tool call。后续根据体验反馈决定是否升级
- **不新增工具给 conversation agent**：不增加 `pause_and_check`、`acknowledge` 等新工具，保持 conversation agent 只有 `send_message` 一个工具
- **不实现心跳/主动关心机制**：属于第三层时间模型，本期不涉及

## 用户故事

### 核心场景

- 作为用户，我发送一条消息后，想看到对方"正在输入"几秒后消息弹出，而不是瞬间出现，这样感觉像在跟真人聊天
- 作为用户，我连续快速发了两条消息（"今天心情不好" + "工作上的事"），希望 agent 能完整看到这两条消息再回复我，而不是只回应第一条就开始打字
- 作为用户，我在 agent 正在回复我的时候（发了第一条气泡还没发完）又补了一句话，希望 agent 在当前几条消息发完后能注意到我说的新内容

### 边界场景

- 作为用户，我发了"嗯"一个字，agent 应该快速判断不需要回复（由 orchestrator 决定），而不是漫长等待后给我一个无意义的回复
- 作为用户，我在 agent defer 期间连续发了 3 条消息，希望 agent 回来后能全部看到，而不是只看到最后一条

## 需求

### P0：消息间打字延迟

#### 需求描述

在 `send_message` 工具内部增加模拟打字延迟。每条消息发送前，先推送 `typing` 状态，等待与消息长度成正比的延迟时间后，再发送实际消息内容。

#### 修改文件

`tools/chat.py` — `send_message` 函数

#### 延迟计算规则

```python
import asyncio
import random

def calculate_typing_delay(text: str) -> float:
    """
    计算模拟打字延迟（秒）。

    规则：
    - 每个字符约 0.15 秒（中文字符和英文字符同等计算）
    - 最小延迟 0.8 秒（即使只有一个字）
    - 最大延迟 6 秒（避免用户等太久）
    - 加入 ±20% 随机波动，避免机械感
    """
    base = len(text) * 0.15
    jitter = random.uniform(-0.2, 0.2) * base
    return max(0.8, min(6.0, base + jitter))
```

#### 连续消息间的思考间隙

两条 `send_message` 之间，除打字延迟外，额外增加 0.3-1.0 秒的随机间隔，模拟"想了一下"。

#### 改造后的 send_message

```python
@function_tool(tool_input_guardrails=[persona_check])
async def send_message(ctx: RunContextWrapper[AgentContext], message: str) -> str:
    """Send a message to the user. Call this every time you want to say something.
    You can call it multiple times to send separate chat bubbles."""
    # 1. 发送 typing 状态
    await ctx.context.websocket.send_json({"type": "status", "status": "typing"})

    # 2. 模拟打字延迟
    delay = calculate_typing_delay(message)
    await asyncio.sleep(delay)

    # 3. 发送实际消息
    await ctx.context.websocket.send_json({"type": "message", "text": message})
    ctx.context.record("assistant", message)

    # 4. 连续消息间思考间隙
    await asyncio.sleep(random.uniform(0.3, 1.0))

    return "Message sent."
```

#### 验收标准

- [ ] 发送一条 10 字消息，用户看到 typing 状态后约 1.5 秒消息出现
- [ ] 连续发送 3 条消息，每条之间有明显的可感知间隔（不低于 0.8 秒），且间隔有随机差异
- [ ] 单条消息的等待时间不超过 6 秒
- [ ] typing 状态在消息发送后自动消失（客户端收到 message 时清除 typing）

### P0：chat 工具增加 hint 参数

#### 需求描述

给 orchestrator 的 `chat` 工具增加 `hint` 可选参数。orchestrator 通过自然语言将轻量情境信息传递给 conversation agent，让 conversation agent 在不参与流程决策的前提下获得必要的上下文。

#### 修改文件

`agnts/orchestrator.py` — `chat` 函数和 `INSTRUCTIONS`

#### 改造后的 chat 工具

```python
@function_tool
async def chat(ctx: RunContextWrapper[AgentContext], hint: str = "") -> str:
    """让角色回复用户。
    hint: 可选的情境提示，如 "用户等了一会儿没说话"、"用户刚发了新消息"。
    不传 hint 则角色正常回复。返回值是最近的对话记录，帮助你做决策。"""
    input_list = _build_input_list(ctx.context.recent_messages)

    # 注入 hint 作为情境上下文（非 user 消息，不需要回应 hint 本身）
    if hint:
        input_list.append({
            "role": "developer",
            "content": f"【情境】{hint}",
        })

    logger.info("│  chat tool → conversation input: {} items, hint={}", len(input_list), hint[:50] if hint else "none")

    await Runner.run(
        _conversation_agent,
        input_list,
        context=ctx.context,
    )

    # Return recent messages so orchestrator can see what happened
    recent = ctx.context.recent_messages
    if not recent:
        return "<context>（没有对话记录）</context>"
    lines = []
    for role, text in recent:
        tag = "user" if role == "user" else "agent"
        lines.append(f"<{tag}>{text}</{tag}>")
    return f"<context>\n{''.join(lines)}\n</context>"
```

#### 更新 orchestrator INSTRUCTIONS

在现有 INSTRUCTIONS 中补充 hint 的使用指引：

```python
INSTRUCTIONS = """\
你是对话状态管理器。你决定什么时候让角色回复、什么时候暂缓、什么时候结束。
你自己不跟用户说话。

你有三个工具：
- chat(hint?)：让角色回复用户。
  hint 是可选的情境提示，告诉角色当前处于什么情况。
  例如：chat(hint="用户等了一会儿没说话") 或 chat(hint="用户又发了新消息")
  不传 hint 时角色正常回复。
  返回值是最近的对话记录，用来帮助你做下一步决策。
- defer_reply：暂停一会儿。暂停后你会被再次调用，可以继续聊或结束。
- end_of_turn：本轮彻底结束，等用户下次发消息。

标准流程（大多数情况都应该这样）：
1. 收到用户消息 → 先调用 chat 让角色回复
2. chat 返回后 → 调用 defer_reply(2~5秒)，制造自然停顿
3. 暂停回来后 → 看情况：
   - 有新用户消息 → 调 chat(hint="用户又发了新消息") 让角色回应
   - 没有新消息 → 可以调 chat(hint="用户暂时没说话，你可以再补一句或者结束") 或直接 end_of_turn

什么时候直接 end_of_turn（跳过 defer）：
- 用户只发了语气词/表情（嗯、哦、哈哈、👍）
- 对话已经自然收尾，双方都没什么要说的了

重要：
- 回复后默认用 defer_reply 而不是 end_of_turn。真人聊天不会每句话说完就离开。
- 不要自己生成面向用户的文字。"""
```

#### 验收标准

- [ ] orchestrator 调用 `chat()` 时不传 hint，conversation agent 正常回复
- [ ] orchestrator 调用 `chat(hint="用户等了一会儿没说话")`，conversation agent 的回复能体现出这个情境（如主动追问、表达关心）
- [ ] hint 以 `developer` role 注入，不会被 conversation agent 当成用户消息回复
- [ ] orchestrator 的 INSTRUCTIONS 中包含 hint 的使用指引和示例

### P0：服务端编排循环改造

#### 需求描述

改造 `server.py` 中的 agent 编排循环，使其在 defer 回来后能正确判断 inbox 状态，并通过 `call_model_input_filter` 将新消息注入 orchestrator 的下一次 LLM 调用。

#### 修改文件

`server.py` — `ws_chat` 函数中的 agent 循环

#### 当前问题

当前 defer 循环在 sleep 结束后检查 `inbox.qsize()`，但 agent_input 传的是固定英文文本 `"You are back after a pause."`。需要改为：

1. 由 `call_model_input_filter` 统一注入 inbox 消息到 orchestrator 的 LLM 输入中
2. agent_input 传中文提示（与 orchestrator 的 INSTRUCTIONS 语言一致）
3. 区分有新消息和无新消息两种情况

#### 改造后的编排循环

```python
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
        # 注意：away 状态已在 defer_reply 工具内部发送（tools/chat.py），此处无需重复
        await asyncio.sleep(seconds)
        await websocket.send_json({"type": "status", "status": "online"})

        # 检查 inbox 中的新消息数量（不取出，留给 input_filter 注入）
        pending = inbox.qsize()
        logger.info("── Back online | {} pending message(s) in inbox", pending)

        if pending > 0:
            agent_input = "暂停回来了，用户发了新消息。先调 chat 回应用户。"
        else:
            agent_input = "暂停回来了，用户没有发新消息。你可以调 chat 让角色再说点什么，或者调 end_of_turn 结束。"
        continue

    else:  # end_of_turn
        logger.info("══ Turn ended after {} run(s)", run_count)
        break
```

#### 关键设计：inbox 消息的注入方式

inbox 中的消息**不在编排循环中手动取出拼接**，而是保留在 queue 中，由 `call_model_input_filter` 在 orchestrator 的下一次 LLM 调用前自动注入。这样：

1. 注入逻辑统一在 `context_policy.py` 的 filter 中，不分散
2. 消息会被 `ctx.record("user", msg)` 记录到 `recent_messages`，conversation agent 通过 `_build_input_list` 也能看到
3. 即使在一次 orchestrator run 中有多轮 LLM 调用，每轮都能捞到最新消息

#### 验收标准

- [ ] defer 回来后 inbox 中有消息 → orchestrator 下一次 LLM 调用时消息被 input_filter 注入 → orchestrator 能看到用户说了什么并决策
- [ ] defer 回来后 inbox 为空 → orchestrator 收到"用户没有发新消息"的提示 → 决定 chat 或 end_of_turn
- [ ] agent_input 使用中文，与 INSTRUCTIONS 语言一致
- [ ] defer 期间用户发送多条消息 → 所有消息都被 input_filter 注入（不丢消息）
- [ ] away 状态在 sleep 开始时发送，online 状态在 sleep 结束后发送

### P1：已读不回行为

#### 需求描述

当 orchestrator 判断用户消息不需要回复时（如"嗯"、"哈哈"、单个表情），直接调用 `end_of_turn` 而不调用 `chat`。服务端通过检查本轮是否调用过 `send_message` 来区分"说完了"和"已读不回"。

#### 修改文件

- `server.py` — 编排循环中 end_of_turn 分支
- `core/context.py` — AgentContext 增加 `messages_sent_this_turn` 计数器

#### AgentContext 增加计数器

```python
@dataclass
class AgentContext:
    websocket: WebSocket
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    last_user_input: str = ""
    recent_messages: list[tuple[str, str]] = field(default_factory=list)
    messages_sent_this_turn: int = 0  # 新增：本轮发送的消息数

    def record(self, role: str, text: str) -> None:
        """Record a (role, text) pair, keeping at most MAX_RECENT entries."""
        self.recent_messages.append((role, text))
        if len(self.recent_messages) > MAX_RECENT:
            self.recent_messages = self.recent_messages[-MAX_RECENT:]
```

#### send_message 更新计数器

```python
@function_tool(tool_input_guardrails=[persona_check])
async def send_message(ctx: RunContextWrapper[AgentContext], message: str) -> str:
    # ... typing delay logic ...
    await ctx.context.websocket.send_json({"type": "message", "text": message})
    ctx.context.record("assistant", message)
    ctx.context.messages_sent_this_turn += 1  # 新增
    return "Message sent."
```

#### 服务端编排循环中的分支

```python
else:  # end_of_turn
    if ctx.messages_sent_this_turn == 0:
        # 已读不回：agent 选择了不回复
        logger.info("══ Read-no-reply | no messages sent this turn")
        await websocket.send_json({"type": "status", "status": "read"})
    else:
        logger.info("══ Turn ended after {} run(s), {} messages sent", run_count, ctx.messages_sent_this_turn)

    # 重置计数器
    ctx.messages_sent_this_turn = 0
    break
```

#### WebSocket 协议扩展

新增 `read` 状态：

```json
{"type": "status", "status": "read"}
```

客户端收到此状态后，可在用户最后一条消息下显示"已读"标记（具体 UI 行为由客户端决定）。

#### 验收标准

- [ ] 用户发送"嗯" → orchestrator 判断不回复 → 直接 end_of_turn → 服务端发送 `{"type": "status", "status": "read"}`
- [ ] 用户发送"今天心情不好" → orchestrator 调 chat → conversation agent 回复 → 正常流程
- [ ] `messages_sent_this_turn` 在每轮对话开始时被重置为 0
- [ ] 已读不回后用户再发消息，系统恢复正常响应

### P1：轻量回应支持

#### 需求描述

通过 prompt 指引让 conversation agent 能输出轻量回应（纯表情、简短反应），不需要新增工具或协议变更。

#### 修改文件

`agnts/conversation.py` — `_build_instructions` 函数中追加指引

#### 追加到 conversation agent 的 instructions 末尾

```
你也可以发很轻的回应：
- 纯表情："😂"、"🤗"、"😭"
- 简短反应："哈哈哈"、"啊这"、"？"、"好耶"
- 不是每条消息都需要有实质内容，轻量回应本身就是一种交流方式
```

#### 验收标准

- [ ] conversation agent 在合适的场景下（如用户发了搞笑内容）能使用纯表情或简短回应
- [ ] 轻量回应经过 `send_message` 正常发送，typing 延迟正常生效（但因为文本短，延迟接近最小值 0.8 秒）
- [ ] persona_check guardrail 不拦截正常的表情和简短回应

## 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `core/context_policy.py` | `call_model_input_filter` 逻辑不变，仍然在 orchestrator 的 LLM 调用前注入 inbox 消息 |
| `tools/guardrails.py` | persona_check 逻辑不变 |
| `core/hooks.py` | CompanionHooks 逻辑不变，on_agent_start 已推送 typing 状态 |
| `agnts/conversation.py`（结构） | conversation agent 只有 `send_message` 一个工具，不增不减 |

## 技术约束

1. **`call_model_input_filter` 只在 orchestrator 的 `Runner.run()` 生效**：conversation agent 的 `Runner.run()` 不传 `run_config`，保持现有行为
2. **`send_message` 中的 `asyncio.sleep` 会阻塞 agent run**：这是预期行为，模拟真人打字时间。单条消息最大等待 6 秒，3 条消息连发最长约 18+3 秒
3. **typing 延迟期间 inbox 不检查**：当前阶段（方向一）send_message 的 sleep 期间不 poll inbox，新消息等 orchestrator 下一个决策点处理
4. **hint 使用 `developer` role**：确保 conversation agent 将 hint 视为系统级上下文而非需要回应的用户消息
5. **`recent_messages` 上限为 4 条**（`MAX_RECENT = 4`）：conversation agent 看到的历史有限，hint 提供补充上下文

## 成功指标

| 指标 | 目标 | 衡量方式 |
|------|------|---------|
| 打字延迟体感自然度 | 主观评测，>80% 的测试对话感觉"像真人打字" | 人工体验测试 |
| 新消息感知延迟 | 用户在 agent 回复期间发消息，≤15 秒内 agent 能回应到 | 日志计时 |
| 已读不回触发率 | 对语气词/表情消息，>70% 的情况 orchestrator 选择不回复 | 日志统计 |
| 系统稳定性 | typing 延迟不导致 WebSocket 超时或连接断开 | 连续运行测试 |

## 实现顺序

```
Step 1: send_message 打字延迟（P0，独立改动，可立即验证）
    ↓
Step 2: chat 工具 hint 参数 + orchestrator INSTRUCTIONS 更新（P0）
    ↓
Step 3: server.py 编排循环改造 — defer 后 agent_input 中文化（P0）
    ↓
Step 4: AgentContext 增加 messages_sent_this_turn + 已读不回分支（P1）
    ↓
Step 5: conversation agent instructions 轻量回应指引（P1）
```

每个 Step 完成后可独立测试，不依赖后续 Step。

## 关联文档

- [三层时间模型设计](3times-level.md) — 整体架构设计，包含心跳机制（第三层，本 PRD 不涉及）
- [陪伴助手 Agent 设计文档](../companion-agent-design.md) — 原始架构设计
- [事件系统路线图](../event-system-roadmap.md) — 事件系统演进计划
