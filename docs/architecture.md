# 系统架构

## 概述

基于 OpenAI Agents SDK 的陪伴聊天 Agent，通过 WebSocket 实时通信，使用双 Agent 架构分离流程决策与角色扮演。

技术栈：FastAPI + OpenAI Agents SDK + WebSocket + Arize Phoenix（可选 tracing）

## 双 Agent 架构

```
用户 ←── WebSocket ──→ server.py（编排循环）
                            │
                      Orchestrator Agent
                       （流程决策层）
                      ┌─────┼─────┐
                      │     │     │
                    chat  defer  end_of_turn
                      │
                Conversation Agent
                  （角色扮演层）
                      │
                  send_message → WebSocket → 用户
```

### Orchestrator（`agnts/orchestrator.py`）

职责：决定什么时候让角色说话、暂缓、还是结束。自己不直接跟用户说话。

模型：`ORCHESTRATOR_MODEL`（环境变量，默认 `gpt-5.4-mini`）

工具：
- `chat` — 调用 Conversation Agent 让角色回复用户
- `defer_reply` — 暂停 N 秒后重新唤醒（`stop_at_tool_names`）
- `end_of_turn` — 本轮结束，等用户下次发消息（`stop_at_tool_names`）

标准流程：收到用户消息 → `chat` → `defer_reply(2~5s)` → 回来后看情况继续 `chat` 或 `end_of_turn`。

### Conversation Agent（`agnts/conversation.py`）

职责：纯角色扮演，只管怎么说话。从 `personas/*.yaml` 加载人设指令。

模型：`OPENAI_MODEL`（环境变量，默认 `gpt-5.4-mini`）

工具：
- `send_message` — 通过 WebSocket 发送一条消息气泡给用户（附带 persona guardrail）

Conversation Agent 被 Orchestrator 的 `chat` 工具内部调用（`Runner.run`），不是 handoff。

## 核心模块

```
server.py              FastAPI 入口，WebSocket 编排循环
agnts/
  orchestrator.py      Orchestrator Agent 定义 + chat 工具
  conversation.py      Conversation Agent 定义，加载 persona
core/
  context.py           AgentContext — 运行时共享状态（WebSocket、inbox、recent_messages）
  context_policy.py    call_model_input_filter — 在每次 LLM 调用前注入 inbox 中的新用户消息
  hooks.py             CompanionHooks — RunHooks 实现，推送 typing 状态 + 日志
  tracing.py           Arize Phoenix OpenTelemetry tracing 初始化
tools/
  chat.py              send_message / defer_reply / end_of_turn
  guardrails.py        persona_check — 用独立 LLM 检测角色是否"穿帮"
personas/              YAML 格式的角色人设定义
mcp_servers/           MCP server 注册（当前有 deepwiki，未启用）
ui/                    前端聊天界面（HTML + CSS + JS）
config/                配置模块（当前为空）
data/                  运行时数据（Viking 记忆存储、向量库）
```

## 编排循环（`server.py`）

```
[WebSocket 连接建立]
  │
  ├── reader task：持续读取用户消息放入 inbox
  │
  └── 主循环：
       │
       ├── 等待 inbox 中的用户消息
       │
       └── defer 循环：
            │
            ├── Runner.run(Orchestrator, input, context, session, hooks)
            │
            ├── 输出是 "defer:N"？
            │   ├── 是 → sleep N 秒 → 发送 status: online → 继续 defer 循环
            │   └── 否 → 本轮结束，回到等待用户消息
            │
            └── inbox 中的新消息由 call_model_input_filter 自动注入
```

关键设计：
- `defer_reply` 不在工具内部 sleep，而是返回秒数交给服务端外部定时器
- 用户消息注入通过 `call_model_input_filter`（`core/context_policy.py`）在每次 LLM 调用前自动完成，不需要显式检查 inbox
- Session 使用 `SQLiteSession` + `OpenAIResponsesCompactionSession`，存储在 `chat.db`

## 日志

使用 loguru，日志格式采用树状缩进：

```
┌─ Agent START | Orchestrator              ← CompanionHooks.on_agent_start
│  Tool START  | Orchestrator.chat         ← CompanionHooks.on_tool_start
│  chat tool → Muse input: 3 items         ← chat 工具内部
│  Tool END    | Orchestrator.chat         ← CompanionHooks.on_tool_end
│  Tool START  | Orchestrator.defer_reply
│  Tool END    | Orchestrator.defer_reply
└─ Agent END   | Orchestrator → defer:3    ← CompanionHooks.on_agent_end
── Defer | 3s, checking inbox after sleep  ← server.py 编排循环
══ Turn ended after 2 run(s)               ← server.py 编排循环
```

日志来源：

| 日志 | 来源 |
|---|---|
| `Agent START/END`、`Tool START/END` | `core/hooks.py` — `CompanionHooks` |
| `chat tool → Muse input` | `agnts/orchestrator.py` — `chat` 工具 |
| `Orchestrator run #N`、`Defer`、`Turn ended` | `server.py` — 编排循环 |
| `Injecting N inbox message(s)` | `core/context_policy.py` — `call_model_input_filter` |

## Tracing

可选功能，通过 Arize Phoenix 提供 OpenTelemetry tracing。

启动 Phoenix UI：
```bash
uv run phoenix serve    # 默认 http://localhost:6006
```

初始化代码在 `core/tracing.py`，使用 `OpenAIAgentsInstrumentor` 自动追踪 Agents SDK 调用。

## 配置

环境变量（`.env`）：

| 变量 | 用途 | 默认值 |
|---|---|---|
| `OPENAI_API_KEY` | API 密钥 | — |
| `OPENAI_BASE_URL` | API 基地址（用于兼容 OpenRouter 等） | — |
| `OPENAI_MODEL` | Conversation Agent 模型 | `gpt-5.4-mini` |
| `ORCHESTRATOR_MODEL` | Orchestrator Agent 模型 | `gpt-5.4-mini` |
