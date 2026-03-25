# 日志参考

## 关键字段

- **`run #N`** — 当前这一轮对话中第 N 次调用 `Runner.run()`。每次 `defer_reply` 退出后重新进入 agent 循环，计数加 1。每轮对话（用户发一条消息触发）从 `#1` 开始。
- **`N run(s)`** — 这一轮对话从开始到 `end_of_turn` 总共调用了几次 `Runner.run()`。

## 日志流程示例

```
用户发送 "你给我讲个故事吧"

Agent run #1 start | input=你给我讲个故事吧       ← 第 1 次 run，输入是用户消息
  send_message | 当然可以呀～                      ← 工具调用：发消息
  send_message | 我给你讲一个小狐狸找月亮的故事。
  defer_reply | 1s                                 ← 工具调用：暂缓
Agent run #1 end | output=defer:1                  ← run 结束，输出是 defer 信号
Defer triggered | waiting 1s                       ← 服务端等待 1 秒

Agent run #2 start | input=You are back after...   ← 第 2 次 run，输入是系统提示
  send_message | 很久以前，有一只小狐狸...
  send_message | 每到晚上，它都会抬头看月亮...
  defer_reply | 1s
Agent run #2 end | output=defer:1
Defer triggered | waiting 1s

Agent run #3 start | input=You are back after...   ← 第 3 次 run
  send_message | 小狐狸特别想把月亮带回家...
  send_message | 它跑啊跑，先去问了猫头鹰...
  defer_reply | 1s
Agent run #3 end | output=defer:1
Defer triggered | waiting 1s

Agent run #4 start | input=You are back after...   ← 第 4 次 run
  send_message | 小狐狸又问了小兔子...
  send_message | 小狐狸想了想，决定不把月亮带走了...
  Injecting 1 inbox message(s) into LLM input      ← call_model_input_filter 检测到用户新消息并注入
  send_message | 嗯，我在。                         ← agent 看到新消息后回应
  end_of_turn                                       ← 本轮结束
Agent run #4 end | output=end_of_turn
Turn ended after 4 run(s)                           ← 这一轮总共跑了 4 次 Runner.run()
```

## 日志来源

| 日志内容 | 来源文件 |
|---|---|
| `Agent run #N start/end` | `server.py` — WebSocket 编排循环 |
| `Defer triggered` | `server.py` — defer 分支 |
| `Turn ended after N run(s)` | `server.py` — end_of_turn 分支 |
| `send_message` | `tools/chat_tools.py` |
| `defer_reply` | `tools/chat_tools.py` |
| `end_of_turn` | `tools/chat_tools.py` |
| `Injecting N inbox message(s)` | `context_policy.py` — `call_model_input_filter` |
| `WebSocket connected` | `server.py` — 连接建立 |
