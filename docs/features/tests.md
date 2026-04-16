# 测试

`pytest` + `asyncio.run()` 风格（未用 pytest-asyncio）。

## 文件

- `tests/test_memory.py` — Memory 压缩 & history persistence
  - `count_meaningful` / `append_to_history` / `load_for_llm` / `load_latest_summary` / `maybe_compress` / `_compress` 全流程
- `tests/test_trace.py` — NDJSON / `TraceRepository`
- `tests/test_loop_trace.py` — `core.loop.run()` 的 trace 行为
- `tests/test_session_runner.py` — `ChatSessionRunner`
- `tests/test_trace_artifacts.py` — `plan.saved` / `diary.appended` / `memory.compression_*`
- `tests/test_scheduler_trace.py` — scheduler 级 trace 事件
- `tests/test_prompt_build.py` — Prompt 组装
- `tests/test_reasoner_response.py` — LLM reasoning_content 字段处理
- `tests/test_wechat_dispatch.py` — 并发 dispatch（见 [concurrent-dispatch.md](concurrent-dispatch.md)）

## 运行

```bash
# 全部单元测试（默认跳过 integration）
uv run python -m pytest -v

# 显式跑 integration
uv run python -m pytest -m integration -v

# 单文件
uv run python -m pytest tests/test_wechat_dispatch.py -v
```
