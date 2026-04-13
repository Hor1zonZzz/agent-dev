# Memory 压缩

history token 超过阈值时，后台异步调 LLM 生成结构化摘要（anna / user / shared 三维），写入 md 文件；下轮 `load_for_llm` 自动读取最新摘要注入 system prompt。

## 涉及代码

- `core/memory.py:19-21` — 阈值配置（`MEMORY_TOKEN_THRESHOLD` / `MEMORY_RECENT_K` / `MEMORY_SUMMARY_MODEL`）
- `core/memory.py:31-77` — 提取 prompt 模板
- `core/memory.py:79-82` — `estimate_tokens()`
- `core/memory.py:84-113` — `load_latest_summary()` 组合最新摘要
- `core/memory.py:147-165` — `maybe_compress()` 阈值检查 + 后台派发
- `core/memory.py:168-190` — `_compress()` 后台 LLM 调用 + 落盘
- `core/memory.py:196-232` — 摘要解析与分维度写盘

## 产物目录

- `history/anna/<ts>.md`
- `history/user/<ts>.md`
- `history/shared/<ts>.md`

## 调用位置

- `cli.py:81` — CLI 每轮结束后
- `wechat.py:167` — worker 每轮结束后

## 相关文档

- [../memory-compression.md](../memory-compression.md)（详细说明）
