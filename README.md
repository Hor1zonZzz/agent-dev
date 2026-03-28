# agent-dev

基于 OpenAI Agents SDK 的陪伴聊天 Agent，双 Agent 架构（Orchestrator + Conversation），WebSocket 实时通信。

## Quick Start

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置

```bash
cp .env.example .env
```

编辑 `.env`，填入 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`（如使用 OpenRouter）。

### 3. 启动 tracing（可选）

```bash
uv run phoenix serve
```

Arize Phoenix tracing UI，默认 `http://localhost:6006`。

### 4. 运行

```bash
uv run uvicorn server:app --reload
```

服务默认监听 `http://localhost:8000`，Web 聊天界面从 `ui/` 自动提供。

## 文档

- [系统架构](docs/architecture.md) — 双 Agent 架构、核心循环、模块职责
- [WebSocket API](docs/websocket-api.md) — 通信协议参考
- [Persona 系统](docs/persona-guide.md) — 角色人设配置与 Guardrail 机制
