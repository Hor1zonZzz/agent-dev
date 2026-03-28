# WebSocket API

连接地址：`ws://localhost:8000/ws`

每个 WebSocket 连接创建一个独立的会话（`session_id`），支持多个并发连接。

## 客户端 → 服务端

```json
{"message": "你好"}
```

唯一的消息格式，`message` 为非空字符串。

## 服务端 → 客户端

### `session` — 连接建立

```json
{"type": "session", "session_id": "a1b2c3d4..."}
```

WebSocket 连接建立后立即发送，`session_id` 是 hex 格式的 UUID。

### `message` — Agent 消息气泡

```json
{"type": "message", "text": "怎么了？"}
```

Agent 通过 `send_message` 工具发送的每条消息。一次回复可能产生多条 `message`，模拟真人分条发微信的节奏。

### `status` — Agent 状态变化

```json
{"type": "status", "status": "typing"}
```

状态值：

| status | 含义 | 触发时机 |
|---|---|---|
| `typing` | Agent 正在思考 | Orchestrator Agent 开始运行 |
| `away` | 暂缓回复中 | `defer_reply` 工具被调用 |
| `online` | 回来了 | defer 等待结束 |

## `GET /health`

HTTP 健康检查接口。

```json
{
  "status": "ok",
  "model": "gpt-5.4-mini",
  "active_servers": 0
}
```

- `model` — Conversation Agent 使用的模型
- `active_servers` — 已连接的 MCP server 数量

## 典型交互时序

```
客户端                         服务端
  │                              │
  │◄──── session ────────────────│  连接建立
  │                              │
  │───── message ───────────────►│  用户发消息
  │                              │
  │◄──── status: typing ─────────│  Orchestrator 开始
  │◄──── message ────────────────│  Agent 回复第 1 条
  │◄──── message ────────────────│  Agent 回复第 2 条
  │◄──── status: away ───────────│  defer_reply，暂缓
  │                              │  （等待 N 秒）
  │◄──── status: online ─────────│  回来了
  │◄──── status: typing ─────────│  继续思考
  │◄──── message ────────────────│  Agent 主动说了一句
  │                              │  end_of_turn，等待用户
  │                              │
```
