# Memory 压缩

每轮对话结束后,检查自上次压缩以来累计的"有意义消息"数(user 发言 + `send_message` 工具调用);达到 `MEMORY_COMPRESS_EVERY`(默认 100)就后台异步调 LLM,基于上次摘要增量更新 anna / user / shared 三维摘要,写入 md。成功后把指针 `last_compressed_at_index` 推到决策时刻的 history 末尾,下轮 `load_for_llm` 自动读取每维度最新的那份注入 system prompt。

## 涉及代码

- `core/memory.py` — `COMPRESS_EVERY` / `MEMORY_RECENT_K` / `MEMORY_SUMMARY_MODEL` 配置
- `EXTRACTION_PROMPT`(首次全量) / `INCREMENTAL_PROMPT`(增量更新)
- `count_meaningful()` — 过滤噪声,只计 user + send_message
- `load_latest_summary()` — 每维度独立找最新 md
- `maybe_compress()` — 用指针 + 阈值判定是否派发
- `_compress(history_path, start_idx, end_idx)` — 后台 LLM + 空维度跳过 + 成功推进指针

## 产物目录

- `history/anna/<ts>.md`
- `history/user/<ts>.md`
- `history/shared/<ts>.md`

## 调用位置

- `cli.py:81` — CLI 每轮结束后
- `wechat.py:167` — worker 每轮结束后

## 相关文档

- [../memory-compression.md](../memory-compression.md)（详细说明）
