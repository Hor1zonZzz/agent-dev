# 工具系统

`Tool` 抽象（pydantic 参数模型 → OpenAI function schema → 执行器）。内置三个工具：`send_message`、`end_turn`、`edit_prompt`。

## 涉及代码

- `core/tool.py:15-56` — `Tool` 基类（`to_openai()` / `execute()`）
- `tools/__init__.py:1-5` — 统一导出
- `tools/send_message.py:10-28` — 发送回复给用户
- `tools/end_turn.py:10-23` — 结束当前 run（在 `agent.stop_at` 中注册）
- `tools/edit_prompt.py:15-55` — 修改 prompts 下的 markdown 文件
