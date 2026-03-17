# Stateless Multimodal Chat API

一个面向生产重构的最小聊天服务：

- 对外只暴露 HTTP API
- 服务端不保存会话
- 多轮对话通过客户端每次提交完整 `messages` 历史实现
- 输入只支持文字和图片
- 底层使用 OpenAI 官方 Python SDK 的 `Responses API`

## Why

这个项目刻意不暴露 `session_id`。

如果你要“无状态 API”，最直接、最稳定的做法是：

1. 客户端自己维护对话历史
2. 每次请求把完整 `messages` 发给服务端
3. 服务端只负责校验、转发给模型、返回回复

这样不会把会话耦合进你的服务端，也不会引入额外的 SQLite、session 管理和脏状态问题。

## Setup

复制 `.env.example` 到 `.env`，至少配置：

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4
```

可选配置见 `.env.example`。

安装依赖：

```bash
uv sync
```

启动服务：

```bash
uv run chatbot-api
```

或：

```bash
uv run uvicorn chatbot_api.main:app --host 0.0.0.0 --port 8000
```

## API

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
```

聊天接口：

```bash
curl http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": [
          { "type": "text", "text": "用一句话介绍你自己" }
        ]
      }
    ]
  }'
```

返回示例：

```json
{
  "id": "resp_123",
  "model": "gpt-5.4",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "我是一个可以处理文字和图片输入的聊天助手。"
      }
    ]
  },
  "usage": {
    "input_tokens": 42,
    "output_tokens": 18,
    "total_tokens": 60
  }
}
```

## Multiturn

服务端无状态，所以多轮对话时客户端需要带上历史消息：

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "我准备去东京旅行" }
      ]
    },
    {
      "role": "assistant",
      "content": [
        { "type": "text", "text": "你更关注吃、住还是行程安排？" }
      ]
    },
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "先帮我做一个3天行程" }
      ]
    }
  ]
}
```

## Images

图片通过 `image_url` 传入，支持：

- 普通图片 URL
- `data:` URL（base64）

示例：

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "描述这张图片" },
        {
          "type": "image",
          "image_url": "https://example.com/image.png",
          "detail": "auto"
        }
      ]
    }
  ]
}
```

## Project Layout

```text
chatbot_api/
  config.py
  main.py
  schemas.py
  service.py
tests/
```

## Notes

- 默认 `OPENAI_STORE=false`，避免把应用状态存到 OpenAI。
- 默认模型是 `gpt-5.4`。如果你的账号或成本策略不适合，可以直接改环境变量。
- 这个项目故意不引入数据库、Agent 框架或工具编排层，先把“稳定聊天 API”做干净。
