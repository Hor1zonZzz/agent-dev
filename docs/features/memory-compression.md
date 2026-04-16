# Memory 压缩

跟踪 `history/<stem>.meta.json` 里的 `last_compressed_at_index` 指针，自该指针之后累计的“有意义消息”数（user 发言 + `send_message` 工具调用）达到 `MEMORY_COMPRESS_EVERY`（默认 100），或双方都静默 `MEMORY_IDLE_COMPRESS_MINUTES`（默认 60）分钟且有未压缩内容，就后台异步调 LLM，基于上次摘要增量更新 anna / user / shared 三维摘要，写入 md。压缩过程现在也会写 trace：`memory.compression_started` / `memory.compression_finished` / `memory.compression_failed`。

## 触发条件(OR)

- **buffer_full**:重度聊天兜底,累积 ≥ `COMPRESS_EVERY` 条有意义消息
- **idle**:`max(last_activity_at, last_anna_message_at)` 距今 ≥ `IDLE_COMPRESS_MINUTES` 分钟

两条都要求 `count_meaningful(new_slice) > 0`,指针到 history 末尾时直接短路返回,不会重复压缩已压过的段。

## 涉及代码

- `core/memory.py` — 配置、提示词、压缩触发和 `_compress()`
- `core/meta.py` — `last_compressed_at_index` 及活动时间读取
- `core/trace.py` — memory trace / artifact trace

## 产物目录

- `history/anna/<ts>.md`
- `history/user/<ts>.md`
- `history/shared/<ts>.md`

## 调用位置

- `core/session.py` — 每轮 chat run 结束后调 `maybe_compress()`
- `wechat.py:main()` — 起 `compression_watchdog()` 协程，每 `WATCHDOG_INTERVAL_SECONDS`（默认 300）扫 `history/wechat/*.json`

## 失败重试

`_compress` 失败不推进指针,下次 worker/watchdog 扫到仍会重试。LLM 限流或网络抖动可自愈;长期失败需查 loguru 日志。
