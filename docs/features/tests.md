# 测试

`pytest` + `asyncio.run()` 风格（未用 pytest-asyncio）。

## 文件

- `tests/test_memory.py` — Memory 压缩 & history persistence
  - `count_meaningful` / `append_to_history` / `load_for_llm` / `load_latest_summary` / `maybe_compress` / `_compress` 全流程
- `tests/test_prompt_build.py` — Prompt 组装
- `tests/test_reasoner_response.py` — LLM reasoning_content 字段处理
- `tests/test_wechat_dispatch.py` — 并发 dispatch（见 [concurrent-dispatch.md](concurrent-dispatch.md)）

## 运行

```bash
# 全部单元测试（不含 integration）
uv run python -m pytest tests/ -v

# 单文件
uv run python -m pytest tests/test_wechat_dispatch.py -v
```
