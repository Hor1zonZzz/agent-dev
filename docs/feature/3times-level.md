# 拟人化回复行为：三层时间模型

## 背景

当前系统已实现基础的拟人对话循环（send_message × N → defer_reply → 检查 inbox → 继续或 end_of_turn），但在时间维度上的拟人化还不够完整。真人聊天中的时间行为至少包含三个层次，本文档定义这三个层次的设计方案。

## 一、三层时间模型总览

```
┌─────────────────────────────────────────────────────────────────┐
│  第一层：对话内节奏（秒级）                                        │
│  消息气泡之间的打字延迟 + 中途打断感知                              │
│  ──────────────────────────────                                  │
│  触发：agent 每次调用 send_message                                │
│  退出：defer_reply / end_of_turn                                 │
├─────────────────────────────────────────────────────────────────┤
│  第二层：已读不回（分钟级）                                        │
│  看到消息但选择不回复，保持关注                                     │
│  ──────────────────────────────                                  │
│  触发：agent 判断无需回复（如"嗯"、"哈哈"、表情）                   │
│  退出：外部 timer 到期后唤醒 agent 重新决策                        │
├─────────────────────────────────────────────────────────────────┤
│  第三层：心跳/主动关心（小时级）                                    │
│  长时间无互动后 agent 主动发起对话                                  │
│  ──────────────────────────────                                  │
│  触发：会话级调度器基于时间/事件/亲密度判断                          │
│  退出：用户回复 → 回到第一层正常对话                                │
└─────────────────────────────────────────────────────────────────┘
```

时间尺度递进关系：

```
第一层（秒）──→ 对话结束 ──→ 第二层（分钟）──→ 无更多消息 ──→ 第三层（小时）
     ↑                                                              │
     └──────────────── 用户发新消息，回到第一层 ←───────────────────────┘
```

---

## 二、第一层：对话内节奏（秒级）

### 2.1 消息间的打字延迟

**现状**：`send_message` 通过 WebSocket 直接推送，多条气泡几乎同时到达。

**目标**：每条消息发送前模拟真人打字时间，让用户看到"对方正在输入..."后消息自然弹出。

#### 延迟模型

```python
def calculate_typing_delay(text: str, persona_speed: float = 1.0) -> float:
    """
    计算模拟打字延迟（秒）。

    参数：
    - text: 消息文本
    - persona_speed: 人设打字速度系数（Muse=0.8 慢一点, Anna=1.2 快一点）

    基础规则：
    - 每个中文字符 ~0.15-0.3 秒
    - 最小延迟 0.8 秒（即使只有一个字）
    - 最大延迟 8 秒（避免等太久）
    - 加入 ±20% 随机波动
    """
    base_delay = len(text) * 0.2 / persona_speed
    jitter = random.uniform(-0.2, 0.2) * base_delay
    return max(0.8, min(8.0, base_delay + jitter))
```

#### 连续消息间的思考间隙

两条消息之间除了打字时间，还有一个"想了一下"的间隔：

```
send_message("怎么了？")
  → typing 延迟 0.8s → 发送
  → 思考间隙 0.5-1.5s（随机）
  → typing 状态显示
send_message("发生什么事了吗")
  → typing 延迟 2.5s → 发送
```

#### 实现位置

延迟逻辑放在 `send_message` 工具内部（或编排层），不需要 LLM 参与决策：

```python
async def send_message(ctx: AgentContext, message: str) -> str:
    # 1. 发送 typing 状态
    await ctx.ws.send_json({"type": "status", "status": "typing"})

    # 2. 模拟打字延迟
    delay = calculate_typing_delay(message, ctx.persona_speed)
    await asyncio.sleep(delay)

    # 3. 发送实际消息
    await ctx.ws.send_json({"type": "message", "text": message})

    # 4. 连续消息间的思考间隙
    await asyncio.sleep(random.uniform(0.5, 1.5))

    return message
```

#### 进阶：打字速度与状态绑定

打字速度可以跟事件系统、情绪系统联动：

| 状态 | 速度系数 | 说明 |
|------|---------|------|
| 默认 | 1.0 | 正常打字速度 |
| 精力充沛（刚运动完） | 1.3 | 打字更快 |
| 困了/无聊 | 0.7 | 打字更慢 |
| 激动/开心 | 1.4 | 打字飞快 |
| 认真思考中 | 0.6 | 打字更慢，思考间隙更长 |

### 2.2 中途打断感知

**现状**：`Runner.run()` 执行完整轮 tool call 序列后才检查 inbox。用户在 agent 发送多条消息过程中发的新消息，要等到下一轮 agent run 才能被看到。

**目标**：在 send_message 的打字延迟期间，如果用户发了新消息，agent 能感知到并调整后续行为。

#### 利用 call_model_input_filter 的方案

核心思路：不需要中断当前轮次，而是利用已有的 `call_model_input_filter` 机制，在下一次 model call 时自动注入新消息。

```
LLM 输出: [send_message("A"), send_message("B"), send_message("C"), defer_reply(5)]
                  │                    │                    │
              打字延迟 2s          打字延迟 3s          打字延迟 4s
                  │                    │                    │
              检查 inbox           检查 inbox           检查 inbox
              (无新消息)           ← 用户发了新消息!      (标记中断)
                  │                    │                    │
              正常发送 A           正常发送 B            跳过 C（可选）
                                       │
                                  将新消息存入 inbox
                                       │
                          defer_reply 执行 → agent 退出
                                       │
                          服务端检查 inbox → 有新消息
                                       │
                          启动 agent run #2
                                       │
                          call_model_input_filter 注入新消息
                                       │
                          LLM 看到新消息，调整回复方向
```

#### 两种策略

**策略 A：温和打断（推荐）**

当前轮的 tool call 继续执行完毕，新消息在下一轮 agent run 时通过 `call_model_input_filter` 注入。

优点：实现简单，不改变 SDK 行为。
缺点：用户可能看到 agent "没注意到"自己说的话继续发了一两条。

**策略 B：即时打断**

在 send_message 的打字延迟中检测到新消息后，设置一个 `interrupted` 标记。后续的 send_message 检查到这个标记后变成 no-op（不发送）。

```python
async def send_message(ctx: AgentContext, message: str) -> str:
    if ctx.interrupted:
        return "[interrupted - message not sent]"

    await ctx.ws.send_json({"type": "status", "status": "typing"})
    delay = calculate_typing_delay(message, ctx.persona_speed)

    # 在延迟期间检查 inbox
    try:
        new_msg = await asyncio.wait_for(ctx.inbox.get(), timeout=delay)
        # 有新消息！放回 inbox 供下一轮使用，标记中断
        await ctx.inbox.put(new_msg)
        ctx.interrupted = True
        # 当前这条还是发出去（人也是打完当前这句再看新消息）
    except asyncio.TimeoutError:
        pass  # 没有新消息，正常发送

    await ctx.ws.send_json({"type": "message", "text": message})
    await asyncio.sleep(random.uniform(0.5, 1.5))
    return message
```

优点：用户感受到 agent "停下来看了我的消息"。
缺点：已经由 LLM 生成但未发送的消息被丢弃，需要 agent 在下一轮重新组织语言。

**建议**：先实现策略 A，后续根据用户体验反馈决定是否升级到策略 B。

---

## 三、第二层：已读不回（分钟级）

### 3.1 场景

真人聊天中，很多消息不需要回复：

- 用户发了"嗯"、"好的"、"哈哈" → 对话自然收尾，不回复
- 用户发了一个表情包 → 看到了，笑了，但不回
- 用户发了一条信息但 agent 当前"在忙"（事件系统） → 稍后再看

### 3.2 设计方案：复用 end_of_turn + 外部 timer

不新增工具。agent 通过现有工具组合表达"已读不回"：

```
用户: "哈哈"
  → agent run
  → agent 判断无需回复
  → end_of_turn()  ← 正常退出
```

**关键区分**：服务端需要区分两种 end_of_turn：

| 类型 | 含义 | 服务端行为 |
|------|------|-----------|
| end_of_turn（有 send_message） | agent 说完了 | 正常结束，等用户下次发言 |
| end_of_turn（无 send_message） | agent 选择不回复 | 发送已读状态（可选），启动中期 timer |

服务端通过检查本轮是否调用过 `send_message` 来区分。

### 3.3 已读状态（可选）

当 agent 选择不回复时，服务端可以向客户端发送一个已读标记：

```json
{"type": "status", "status": "read"}
```

客户端可以在对应消息下显示"已读"或对方头像的小标记。这个是否实现取决于产品决策——有些场景下"完全沉默"比"已读不回"更自然。

### 3.4 中期 timer

agent 不回复后，服务端启动一个 5-15 分钟的 timer：

```python
# 服务端编排逻辑
if not has_sent_message_this_turn:
    # agent 选择了不回复
    await send_status("read")  # 可选

    # 启动中期 timer
    timer_seconds = random.randint(300, 900)  # 5-15 分钟
    await asyncio.sleep(timer_seconds)

    # timer 到期，检查这段时间内有没有新消息
    new_messages = drain_inbox()
    if new_messages:
        # 有新消息，启动新一轮 agent run
        agent_input = format_new_messages(new_messages)
    else:
        # 没有新消息，问 agent 要不要主动说点什么
        agent_input = "过了一会儿了，用户还没有发新消息。你可以主动说点什么，或者结束。"

    result = await Runner.run(agent, agent_input, ...)
```

### 3.5 LLM 的决策依据

agent 需要在 prompt 中获得足够信息来判断是否回复：

```
【当前对话上下文】
用户: 今天心情不好
你: 怎么了？
你: 发生什么事了吗
用户: 工作上的事
你: 工作压力大确实挺难受的
你: 要不要具体说说？我听着呢
用户: 嗯

【决策指引】
根据用户的最后一条消息和对话上下文，决定：
- 如果用户的消息是对话的自然收尾（如"嗯"、"好的"、"哈哈"），可以选择不回复，直接 end_of_turn
- 如果用户的消息需要回应，正常回复
```

---

## 四、第三层：心跳/主动关心（小时级）

### 4.1 设计目标

当对话彻底结束（end_of_turn）且用户长时间没有新消息时，agent 可以像真人朋友一样主动发起聊天：

- "早上好呀，今天天气不错"
- "刚看完一部电影，突然想到你说你也喜欢这个导演"
- "你昨天说工作上的事，后来怎么样了？"

### 4.2 会话级调度器（Session Scheduler）

心跳机制独立于对话循环，由一个会话级调度器管理：

```
对话结束（end_of_turn）
        │
        ▼
  会话调度器启动
        │
        ├── 计算下次心跳时间
        │     ├── 考虑当前时间（不能半夜发消息）
        │     ├── 考虑对话频率/亲密度
        │     └── 考虑事件系统（有没有值得分享的事）
        │
        ▼
  等待心跳时间到达
        │
        ├── 期间用户发了新消息 → 取消心跳，进入正常对话循环
        │
        ▼
  心跳触发 → 启动 agent run
        │
        ├── 输入信息：
        │     ├── "距离上次聊天已经过了 X 小时"
        │     ├── "现在是 [时间段]"
        │     ├── "你现在的状态：[当前事件]"
        │     └── "上次聊天的话题是：[摘要]"（需要记忆系统支持）
        │
        ▼
  agent 决定是否主动说话
        │
        ├── 决定说 → send_message → 进入正常对话循环
        └── 决定不说 → 重新调度下一次心跳
```

### 4.3 调度策略（待定）

以下三种策略各有优劣，需要通过实际体验确定最佳方案，也可以组合使用：

#### 策略 A：固定时段检查

每天在固定时间点检查是否需要主动打招呼：

```yaml
heartbeat_schedule:
  morning: "08:30-09:30"    # 早上好
  evening: "20:00-21:00"    # 晚上闲聊
  # 只在上次对话距今 > 6 小时时才触发
  min_silence_hours: 6
```

优点：简单可预测，不会打扰太频繁。
缺点：机械感强，不够自然。

#### 策略 B：动态间隔

根据用户行为模式动态计算：

```python
def calculate_next_heartbeat(
    last_chat_time: datetime,
    chat_frequency: float,     # 过去7天平均每天聊天次数
    intimacy_score: float,     # 0-1 亲密度
    current_hour: int
) -> datetime:
    # 基础间隔：对话越频繁，心跳越频繁
    base_hours = 24 / max(chat_frequency, 0.5)

    # 亲密度调节：越亲密越可以频繁
    adjusted = base_hours * (1 - intimacy_score * 0.3)

    # 时间段过滤：只在合理时间发消息
    next_time = last_chat_time + timedelta(hours=adjusted)
    next_time = clamp_to_reasonable_hours(next_time, min_hour=8, max_hour=22)

    return next_time
```

优点：自然、个性化。
缺点：需要维护用户数据，逻辑复杂。

#### 策略 C：事件驱动

当事件系统产生了"值得分享"的事件时触发：

```yaml
events:
  - text: 刚看到一个超搞笑的视频
    shareable: true       # 标记为"值得分享"
    share_probability: 0.7  # 70% 概率主动分享
  - text: 在看书
    shareable: false      # 不主动分享
```

优点：有话题时才聊，最自然。
缺点：依赖事件系统的丰富度，可能长时间沉默。

#### 建议的组合方案

```
心跳触发条件 = (固定时段 OR 值得分享的事件) AND 距上次对话 > 最小沉默时间
```

即：在固定时段到来时、或事件系统产生有趣事件时，如果距离上次对话已经足够久，就触发心跳。这样兼顾了可预测性和自然感。

### 4.4 与事件系统的联动

心跳机制天然与 event-system-roadmap 中的 v4（Proactive Event Sharing）对齐：

```
事件系统产生有趣事件
        │
        ▼
  检查：距上次对话是否 > min_silence?
        │
    是 ──┼── 否 → 忽略（用户刚聊过，不需要主动找话题）
        │
        ▼
  检查：当前是否在合理时间段？
        │
    是 ──┼── 否 → 延迟到下个合理时间段
        │
        ▼
  启动 agent run，注入事件信息
  agent 决定怎么说
```

### 4.5 防打扰机制

无论哪种策略，都需要防打扰规则：

- **时间过滤**：只在 8:00-22:00 发消息（可配置）
- **频率上限**：每天最多主动发起 2-3 次
- **连续无回复降级**：如果 agent 主动发了消息用户没理，下次心跳间隔自动拉长
- **用户设置**：后续可开放让用户设定"免打扰时段"

---

## 五、轻量回应模式

### 5.1 背景

当前 `send_message` 总是发送文字内容。真人聊天中有很多非文字形式的轻量回应。

### 5.2 扩展消息类型

在现有 WebSocket 协议基础上扩展 message 类型：

```json
// 文字消息（现有）
{"type": "message", "text": "怎么了？"}

// 表情回应
{"type": "reaction", "emoji": "😂", "target_message_id": "msg_123"}

// 简短表情消息（不是回应某条消息，而是独立发送）
{"type": "message", "text": "😂😂😂"}

// 语音消息占位（未来）
{"type": "message", "media_type": "voice", "text": "[语音消息]", "duration": 3}
```

### 5.3 send_message 工具的扩展

可以让 LLM 自然地使用表情和简短回应，不需要新增工具：

```
agent 的 prompt 中指引：
- 你可以发送纯表情消息，如"😂"、"🤗"
- 你可以发送很短的回应，如"？"、"哈哈哈"、"啊这"
- 不是每条消息都需要有实质内容，轻量回应本身就是一种交流
```

### 5.4 表情回应（Reaction）

对某条消息"点赞/表情回应"是独立于 send_message 的行为，可以作为未来新工具：

```python
react_to_message(emoji: str)  # 对用户最后一条消息表情回应
```

这个可以作为 P1 后续实现，当前先支持纯表情文字消息即可。

---

## 六、四大功能优先级

| 功能 | 优先级 | 实现复杂度 | 拟人提升 | 说明 |
|------|--------|-----------|---------|------|
| 消息间打字延迟 | P0 | 低 | 高 | 改动小，体验提升明显 |
| 已读不回 + 中期 timer | P0 | 中 | 高 | 核心拟人行为，复用 end_of_turn |
| 轻量回应模式 | P1 | 低 | 中 | prompt 调整即可，协议小幅扩展 |
| 中途打断感知 | P1 | 中 | 中 | 先用策略A，后续视反馈升级 |
| 心跳/主动关心 | P2 | 高 | 高 | 需要会话调度器，依赖记忆系统 |

---

## 七、与现有架构的关系

```
现有模块                        新增/修改
─────────────                  ──────────
send_message 工具        →     + 打字延迟逻辑
                               + inbox 检查（打断感知）
end_of_turn 工具         →     不变，服务端区分有无消息的 end_of_turn
defer_reply 工具         →     不变
server.py 编排循环       →     + 已读不回的中期 timer 分支
                               + 心跳调度器（新增模块）
events.yaml 事件系统     →     + shareable 标记（心跳触发）
context_policy.py        →     不变（input_filter 已支持 inbox 注入）
WebSocket 协议           →     + "read" 状态
                               + "reaction" 消息类型（P1）
```

---

## 八、双 Agent 架构下的 input_filter 决策

### 8.1 问题

`call_model_input_filter` 可以在每次 LLM 调用前注入 inbox 中的用户新消息。在双 agent 架构下，这个 filter 应该作用在哪一层？

### 8.2 矛盾分析

三个需求互相冲突：

```
需求 A：conversation agent 需要实时看到新消息 → 回复更自然
需求 B：要不要回复、什么时候回复，是 orchestrator 的决策 → 流程控制权归编排层
需求 C：conversation agent 需要知道之前的决策上下文 → 不然回复会偏移
```

如果给 conversation agent 注入新消息（满足 A），它会直接回复，破坏 orchestrator 的流程控制（违反 B）。如果把 defer/end_of_turn 也给 conversation agent（满足 B），就退化回单 agent 设计。

### 8.3 决策：input_filter 不作用于 conversation agent

**结论**：`call_model_input_filter` 只作用在 orchestrator 的 `Runner.run()` 上。conversation agent 的 `Runner.run()` 不传 `run_config`，执行期间是"盲"的。

**理由**：

1. conversation agent 一次 run 只有几秒（发 2-3 条消息），用户在这几秒内发的新消息等 orchestrator 拿到再决策，延迟很短，用户感知不强
2. 保持 conversation agent prompt 的纯粹性——只负责扮演角色、输出内容
3. 所有流程决策（是否回复、是否等待、是否结束）统一由 orchestrator 控制
4. 避免 conversation agent 和 orchestrator 对同一条消息做出冲突反应

### 8.4 conversation agent 的上下文传递

conversation agent 通过两个渠道获取上下文：

**渠道一：对话历史（已实现）**

通过 `_build_input_list(ctx.context.recent_messages)` 获取完整对话记录。

**渠道二：orchestrator 的轻量 hint（新增）**

给 `chat` 工具增加 `hint` 参数，orchestrator 通过自然语言传递情境提示：

```python
@function_tool
async def chat(ctx: RunContextWrapper[AgentContext], hint: str = "") -> str:
    """让角色回复用户。
    hint: 可选的情境提示，帮助角色理解当前状态。"""
    input_list = _build_input_list(ctx.context.recent_messages)

    if hint:
        input_list.append({"role": "user", "content": f"【情境】{hint}"})

    await Runner.run(
        _conversation_agent,
        input_list,
        context=ctx.context,
    )
    ...
```

orchestrator 使用示例：
- `chat(hint="用户等了一会儿没说话")` → conversation agent 可能主动追问或发送关心
- `chat(hint="用户刚发了新消息")` → conversation agent 知道要先回应新内容
- `chat()` → 正常回复，无额外上下文

这样 conversation agent 获得了轻量的情境感知，但不参与流程决策，prompt 保持纯粹。

### 8.5 未来演进路径

当前方案是"方向一"（不注入，orchestrator 完全掌控）。后续可按需演进：

```
v1（当前）：方向一，conversation agent 每次发 N 条消息
     ↓ 如果体验评估发现"中途打断"是刚需
v2：orchestrator 控制粒度，chat 工具增加 mode 参数
    - mode="normal"：conversation agent 正常发多条（默认）
    - mode="single"：conversation agent 只发一条就返回
     ↓ 如果需要更精细的实时感知
v3：conversation agent 增加 pause_and_check 工具（只读感知，无决策）
```

---

## 九、Open Questions

- [ ] **打字延迟的具体参数**：需要通过实际体验调优，建议做成可配置参数
- [ ] **已读状态是否展示给用户**：有些场景"完全沉默"比"已读不回"更自然，需要产品决策
- [ ] **心跳调度策略的最终选择**：固定时段 / 动态间隔 / 事件驱动 / 组合方案，需要实际测试
- [ ] **亲密度模型**：心跳频率依赖亲密度，但亲密度如何计算？需要记忆系统支撑
- [ ] **中途打断策略 B 的必要性**：策略 A（温和打断）是否足够？需要用户反馈验证
- [ ] **轻量回应的边界**：agent 在什么情况下应该发表情 vs 文字？需要 prompt 工程实验
