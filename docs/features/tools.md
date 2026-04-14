# 工具系统

`Tool` 抽象（pydantic 参数模型 → OpenAI function schema → 执行器）。当前工具集：`send_message`、`end_turn`、`recall_day`、`save_plan`。

## 涉及代码

- `core/tool.py:15-56` — `Tool` 基类（`to_openai()` / `execute()`）
- `core/tools/__init__.py` — 聊天类工具统一导出
- `core/tools/send_message.py:10-28` — 发送回复给用户
- `core/tools/end_turn.py:10-23` — 结束当前 run（在 `agent.stop_at` 中注册）
- `core/tools/recall_day.py` — 查往日日记（见 diary 功能文档）
- `hermes/plan.py` 底部 — `save_plan` 工具（放在 hermes 下避免 core→hermes 反向依赖，见 planner 文档）
