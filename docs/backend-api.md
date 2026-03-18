# 后端接口文档

当前后端是一个基于 FastAPI 的单会话聊天服务，入口文件为 [server.py](/Users/baai314/workspace/agent-dev/server.py)。

启动命令：

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

## 约束

- 当前版本只支持一个活动会话。
- 服务启动时会创建一个服务端 `session_id`。
- 客户端首次请求可以不传 `session_id`，服务端会在 SSE 的 `session` 事件中返回它。
- 后续请求如果传入不同的 `session_id`，服务端会返回 `409 Conflict`。
- 聊天接口是 SSE 流式返回，不提供普通 JSON 聊天接口。

## `GET /health`

用途：
返回服务存活状态和当前运行时基础信息。

响应示例：

```json
{
  "status": "ok",
  "model": "openai/gpt-5.4-mini",
  "session_id": "fd2dbf33-f480-41e2-84ef-3a3fd6bdaf87",
  "active_servers": 1
}
```

字段说明：

- `status`: 固定为 `ok`
- `model`: 当前使用的模型名
- `session_id`: 当前服务唯一活动会话 id
- `active_servers`: 已连接的 MCP server 数量

## `POST /chat/stream`

用途：
发送一条用户消息，并通过 SSE 流式接收 agent 回复。

请求头：

```http
Content-Type: application/json
```

请求体：

```json
{
  "message": "你好",
  "session_id": null
}
```

字段说明：

- `message`: 必填，非空字符串
- `session_id`: 可选。首次请求可不传或传 `null`；后续请求应传服务端返回的值

成功响应头：

```http
Content-Type: text/event-stream; charset=utf-8
```

SSE 事件类型：

### `session`

首次进入流时返回当前会话 id。

示例：

```text
event: session
data: {"session_id":"fd2dbf33-f480-41e2-84ef-3a3fd6bdaf87"}
```

### `delta`

模型输出的文本增量。前端应按顺序拼接 `text`。

示例：

```text
event: delta
data: {"text":"OK"}
```

### `done`

流式响应结束时返回完整结果。

示例：

```text
event: done
data: {"session_id":"fd2dbf33-f480-41e2-84ef-3a3fd6bdaf87","final_output":"OK"}
```

字段说明：

- `session_id`: 当前会话 id
- `final_output`: 完整回复文本

### `error`

服务端处理流时出现异常时返回。

示例：

```text
event: error
data: {"detail":"Agent returned an empty response"}
```

## 错误响应

### `409 Conflict`

触发条件：
请求中的 `session_id` 与当前服务唯一活动会话不一致。

示例：

```json
{
  "detail": "This server only supports one active session. Reuse the issued session_id."
}
```

### `422 Unprocessable Entity`

触发条件：
请求体缺少 `message`，或者 `message` 为空字符串。

## 前端接入建议

浏览器端推荐使用 `fetch` 读取 SSE 响应体，按空行切分事件块，再解析：

- `event: session` 时保存 `session_id`
- `event: delta` 时把 `text` 追加到当前消息
- `event: done` 时用 `final_output` 作为最终结果落盘
- `event: error` 时中止当前消息并提示错误

最小请求示例：

```bash
curl -N \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/chat/stream \
  -d '{"message":"Reply with exactly the word OK.","session_id":null}'
```
