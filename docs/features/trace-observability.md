# Trace 可观测性

统一的执行轨迹系统：所有聊天 run、planner、Hermes 任务、scheduler 事件和 memory compression 都写入 `history/traces/YYYY-MM-DD.ndjson`。

## 涉及代码

- `core/trace.py` — `TraceEvent` / `RunMeta` / `TraceRecorder`
- `core/trace.py` — `NullTraceSink` / `FanoutTraceSink` / `NdjsonTraceSink` / `LoggerTraceSink`
- `core/trace.py` — `TraceRepository.list_runs()` / `get_run()`
- `core/loop.py` — 主循环 trace 发射点
- `core/session.py` — history artifact 事件
- `hermes/scheduler.py` / `hermes/plan.py` / `hermes/diary.py` / `core/memory.py` — scheduler / artifact / compression 事件

## 事件模型

- 固定字段：`event_id` / `run_id` / `seq` / `ts` / `run_kind` / `source` / `lane` / `type` / `status` / `summary` / `payload`
- `run_kind`：`cli_chat` / `wechat_chat` / `wechat_proactive` / `planner` / `hermes_task` / `hermes_slot` / `memory_compress`
- `lane`：`dispatch` / `runtime` / `llm` / `tool` / `scheduler` / `memory` / `artifact`

## 默认配置

- `TRACE_ENABLED=1`
- `TRACE_DIR=history/traces`
- `TRACE_MAX_PREVIEW_CHARS=200`

## 读侧

- `TraceRepository.list_runs(limit, run_kind=None, source=None, session_id=None, day=None)`
- `TraceRepository.get_run(run_id)`

读侧按天扫描 NDJSON、按 `run_id` 聚合，不做二级索引。
