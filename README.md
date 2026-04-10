# agent-dev

基于 OpenAI Agents SDK 的陪伴聊天 Agent，支持 CLI 和微信 ClawBot 两种交互方式。

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

### 3. 运行 CLI

```bash
uv run python cli.py
```

### 4. 微信 ClawBot

```bash
# 首次：扫码绑定微信
uv run python wechat.py setup

# 启动消息监听
uv run python wechat.py
```
