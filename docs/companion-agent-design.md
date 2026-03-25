# 陪伴助手 Agent 设计文档

## 一、设计目标

构建一个拟人化的陪伴助手（Anna），不是传统的一问一答式 AI，而是像朋友发微信一样自然交流。

### 核心特征

1. **多条消息**：一次回复拆成多个短消息气泡，而不是一个长段落
2. **有节奏感**：消息之间有自然的停顿，不是瞬间全部弹出
3. **暂缓回复**：agent 可以"忙别的去了"，过一会儿再回来
4. **感知用户**：暂缓期间如果用户发了新消息，agent 能看到并回应
5. **主动关心**：暂缓回来后即使用户没说话，agent 也可以决定要不要主动说点什么

## 二、技术选型（已确定）

| 项目 | 选择 | 原因 |
|---|---|---|
| Agent 框架 | OpenAI Agents SDK | 已有基础，工具系统成熟 |
| 通信协议 | WebSocket | 双向通信，天然支持实时推送和接收 |
| Runner 模式 | `Runner.run()` | 工具自行推送消息，stream events 无法干预 agent 内部行为，不需要流式 |
| 记忆系统 | 暂不实现 | 后续独立开发再接入 |

## 三、工具设计

### 3 个工具

| 工具 | 签名 | 职责 | 是否退出 agent 循环 |
|---|---|---|---|
| `send_message` | `send_message(message: str)` | 发送一条消息气泡给用户 | 否 |
| `defer_reply` | `defer_reply(seconds: int)` | 暂缓回复，交出控制权给服务端 | **是** |
| `end_of_turn` | `end_of_turn()` | 本轮结束，等待用户下一次主动发言 | **是** |

### 关键设计决策

- `defer_reply` 和 `end_of_turn` 都是 **退出信号**（`stop_at_tool_names`）
- `defer_reply` 不在工具内部 sleep，而是返回秒数交给服务端外部定时器处理
- 不需要 `check_inbox` 工具——收件箱检查由服务端编排，结果作为下一轮 agent 输入

### 两个退出信号的区别

```
defer_reply(seconds) → 退出循环 → 服务端等 N 秒 → 检查收件箱 → 再次启动 agent
end_of_turn()        → 退出循环 → 服务端等用户主动发消息 → 再次启动 agent
```

## 四、交互流程

### 核心循环

```
[用户发消息] → agent run #1 → send_message × N → defer_reply(8) → 退出
                                                                      ↓
                                                             服务端等待 8 秒
                                                                      ↓
                                                             检查用户收件箱
                                                            ↙            ↘
                                                  有新消息               没有新消息
                                                      ↓                      ↓
                                            "用户说了: ..."       "没有新消息，你可以
                                                      ↓            主动说点什么或结束"
                                                      ↓                      ↓
                                                  agent run #2          agent run #2
                                                      ↓                      ↓
                                             send_message × N        决定说 or 结束
                                                      ↓                      ↓
                                          defer_reply / end_of_turn    end_of_turn
                                                      ↓                      ↓
                                                  继续循环...          回到等待用户
```

### 场景举例

```
用户: "今天心情不好"

  [agent run #1]
  → send_message("怎么了？")
  → send_message("发生什么事了吗")
  → defer_reply(8)                    ← 退出，等 8 秒

  [服务端等 8 秒，期间用户发了 "工作上的事"]
  [检查收件箱 → 有新消息]

  [agent run #2，输入: "用户说了: 工作上的事"]
  → send_message("工作压力大确实挺难受的")
  → defer_reply(3)                    ← 退出，等 3 秒

  [服务端等 3 秒，用户没说话]
  [检查收件箱 → 无新消息]

  [agent run #3，输入: "没有新消息，你可以主动说点什么或结束"]
  → send_message("要不要具体说说？我听着呢")
  → end_of_turn()                     ← 本轮彻底结束

  [等待用户下一次发消息...]
```

## 五、WebSocket 协议

### 客户端 → 服务端

```json
{"message": "今天心情不好"}
```

### 服务端 → 客户端

```json
{"type": "session", "session_id": "abc123"}
{"type": "message", "text": "怎么了？"}
{"type": "message", "text": "发生什么事了吗"}
{"type": "status", "status": "typing"}
{"type": "status", "status": "away"}
{"type": "status", "status": "online"}
```

消息类型：
- `session`：连接建立时发送 session_id
- `message`：agent 发送的消息气泡
- `status`：agent 状态变化
  - `typing` = agent 正在思考（从 stream events 检测到 LLM 开始生成）
  - `away` = 暂缓回复中
  - `online` = 回来了

### 为什么选 `Runner.run()`

`run()` 和 `run_streamed()` 的 agent 循环和工具执行逻辑完全一样（共享同一个 `execute_tools_and_side_effects()`）。
`run_streamed()` 额外提供 stream events，但这些事件是**只读的**——外部无法通过事件干预 agent 内部行为。

在我们的架构中，工具自己直接通过 WebSocket 推送消息，不依赖 stream events 提取内容。
`typing` 状态可以在调用 `Runner.run()` 之前直接发送，不需要流式事件。

因此选更简单的 `Runner.run()`。

## 六、服务端编排逻辑（伪代码）

```python
while True:
    message = await inbox.get()        # 等待用户消息

    agent_input = message
    while True:                        # defer 循环
        result = await Runner.run(agent, agent_input, ...)

        if result.final_output 是 defer:
            seconds = 解析秒数
            await sleep(seconds)
            发送 status: online

            new_messages = 清空 inbox
            if new_messages:
                agent_input = "用户说了: ..." + 拼接消息
            else:
                agent_input = "没有新消息，你可以主动说点什么或结束"
            continue                   # 再跑一轮 agent

        else:                          # end_of_turn
            break                      # 回到外层等用户
```

## 七、后续规划（本期不实现）

### 双 Agent 架构拆分

当前单 agent 同时承担两个职责：陪伴对话 + 流程决策（何时暂缓、何时结束、是否主动说话）。
后续可拆分为两个 agent，分离关注点：

```
编排 Agent（系统视角，知道 inbox、defer 机制）
    ├── 接收系统信号："用户说了xxx" / "没有新消息"
    ├── 做流程决策：该说话？等一等？结束？
    ├── 调用 → 对话 Agent（as_tool）
    └── 调用 → defer_reply / end_of_turn

对话 Agent（用户视角，只管聊天）
    ├── 纯粹的陪伴人设，不掺杂系统指令
    └── 返回聊天内容给编排 Agent
```

拆分的好处：
- 对话 agent 的 prompt 更纯粹，不需要混入"没有新消息你可以主动说话"之类的系统指令
- 编排 agent 可以独立演进决策逻辑（比如加入情感分析、记忆检索后再决定说什么）
- 各自可以用不同的模型（编排用小模型快速决策，对话用大模型保证质量）

### 其他

- [ ] 用户背景设定（年龄、兴趣、关系等）
- [ ] agent 人设/性格设定
- [ ] 记忆系统接入（记住聊过的内容）
- [ ] 基于记忆 + 人设决定是否主动发起对话
- [ ] `end_of_turn` 后长时间无消息，agent 主动关心
- [ ] 消息持久化 + 离线投递（用户断开时 agent 生成的消息存库，重连时投递）
