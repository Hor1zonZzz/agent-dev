# Trace WebUI

本机只读的 Trace 观察台，用来查看微信主通道以及 planner / Hermes / memory compression 产生的 run、timeline 和 artifact。

## 涉及代码

- `webui/app.py` — FastAPI 路由、Jinja 页面、SSE 端点、`uvicorn` 启动入口
- `webui/views.py` — `TraceRepository` 到页面 view model 的转换、timeline 配对、artifact 预览
- `webui/templates/*.html` — `runs` / `run_detail` / `artifact_preview` 页面
- `webui/static/app.css` / `webui/static/app.js` — 本地调试样式和自动刷新
- `tests/test_webui.py` — WebUI API / 页面 / SSE / artifact preview 回归测试

## 启动方式

```bash
uv run python -m webui.app
```

## 页面与接口

- 页面：`/traces` / `/traces/{run_id}` / `/artifacts/preview`
- API：`/api/runs` / `/api/runs/{run_id}` / `/api/artifacts/preview`
- SSE：`/api/stream/runs` / `/api/stream/runs/{run_id}`

## 默认配置

- `TRACE_WEB_HOST=127.0.0.1`
- `TRACE_WEB_PORT=8000`
- `TRACE_WEB_RELOAD=0`
- `TRACE_WEB_POLL_SECONDS=1.0`
- `TRACE_WEB_SSE_PING=1.0`
- `TRACE_WEB_PREVIEW_CHARS=4000`

## 约束

- 只读，不承接聊天，不替代 `wechat.py`
- 只允许预览 `history/` 目录下的 `plan` / `diary` / `memory_summary` / `history` 文本 artifact
- 首页以 `run` 为第一观察单位，默认按时间倒序展示
