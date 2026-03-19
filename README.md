# agent-dev

Stateless multimodal chat API built on the OpenAI Responses API.

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure

```bash
cp ov.conf.example ov.conf
```

Edit `ov.conf`, fill in your API keys.

### 3. Start tracing (optional)

```bash
uv run phoenix serve
```

Starts the Arize Phoenix tracing UI, default at `http://localhost:6006`.

### 4. Run

```bash
uv run uvicorn server:app --reload
```

The server listens on `http://localhost:8000`. The web chat UI is served automatically from `ui/`.
