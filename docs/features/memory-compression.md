# Memory 压缩

跟踪 `history/<stem>.meta.json` 里的 `last_compressed_at_index` 指针,自该指针之后累计的"有意义消息"数(user 发言 + `send_message` 工具调用)达到 `MEMORY_COMPRESS_EVERY`(默认 100),或双方都静默 `MEMORY_IDLE_COMPRESS_MINUTES`(默认 60)分钟且有未压缩内容,就后台异步调 LLM,基于上次摘要增量更新 anna / user / shared 三维摘要,写入 md。成功后把指针推到决策时刻的 history 末尾,下轮 `load_for_llm` 自动读取每维度最新的那份注入 system prompt。

## 触发条件(OR)

- **buffer_full**:重度聊天兜底,累积 ≥ `COMPRESS_EVERY` 条有意义消息
- **idle**:`max(last_activity_at, last_anna_message_at)` 距今 ≥ `IDLE_COMPRESS_MINUTES` 分钟

两条都要求 `count_meaningful(new_slice) > 0`,指针到 history 末尾时直接短路返回,不会重复压缩已压过的段。

## 涉及代码

- `core/memory.py` — `COMPRESS_EVERY` / `IDLE_COMPRESS_MINUTES` / `WATCHDOG_INTERVAL_SECONDS` / `RECENT_K` / `SUMMARY_MODEL` 配置
- `EXTRACTION_PROMPT`(首次全量) / `INCREMENTAL_PROMPT`(增量更新)
- `count_meaningful()` — 过滤噪声,只计 user + send_message
- `_latest_activity()` — 取两侧活动时间的最大值判断 idle
- `load_latest_summary()` — 每维度独立找最新 md
- `maybe_compress()` — 指针 + buffer_full/idle 双重判定
- `_compress(history_path, start_idx, end_idx)` — 后台 LLM + 空维度跳过 + 成功推进指针
- `compression_watchdog(history_dir)` — 定时扫目录,触发 idle 分支

## 产物目录

- `history/anna/<ts>.md`
- `history/user/<ts>.md`
- `history/shared/<ts>.md`

## 调用位置

- `wechat.py` worker — 每轮对话结束后调 `maybe_compress`(inline)
- `wechat.py:main()` — 起 `compression_watchdog` 协程,每 `WATCHDOG_INTERVAL_SECONDS`(默认 300)扫 `history/wechat/*.json`
- `cli.py` — 每轮结束后调 `maybe_compress`(CLI 场景无 watchdog,静默即退出)

## 失败重试

`_compress` 失败不推进指针,下次 worker/watchdog 扫到仍会重试。LLM 限流或网络抖动可自愈;长期失败需查 loguru 日志。
