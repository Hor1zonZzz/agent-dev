# 记忆提交策略：滑动窗口 + 话题检测

底层驱动：**OpenViking**（embedded mode）

## 核心思路

不逐轮 commit，而是基于话题边界做语义分块提交。通过滑动窗口积累消息，LLM 检测话题转折点，在转折处切分并 commit，保证每次提交的记忆语义完整。

## 组件

### 1. 消息缓存

存放所有未 commit 的消息，对应一个 OpenViking session。

```
buffer = [m1(user), m2(assistant), m3(user), m4(assistant), ...]
```

- 每轮对话产生 2 条消息（user + assistant）
- 缓存中的消息已通过 `ov.add_message()` 写入当前 session，但未 commit

### 2. 轮次计数器

- 每积累 **5 轮**（10 条消息）触发一次 LLM check
- 初始 check 后，若无转折，每再积累 5 轮再次 check
- 最多扩容 **4 次**（即最多 check 5 次，覆盖 25 轮 / 50 条消息）
- 达到上限后强制 commit 全部缓存

```
check_count = 0
MAX_EXPANSIONS = 4  # 最多扩容次数

每 5 轮:
    check_count += 1
    if check_count > MAX_EXPANSIONS + 1:
        强制 commit 全部
    else:
        LLM check → 判断是否有转折
```

### 3. 话题检测 LLM

输入：缓存中的全部消息（从第一条开始，不截断）

输出：
- `{"pivot": null}` — 无转折，继续积累
- `{"pivot": N}` — 第 N 条 user message 开始出现话题转折

## 流程

```
用户发消息 → assistant 回复 → 写入缓存 + session
                                    ↓
                            当前轮数 % 5 == 0？
                           /                \
                         否                   是
                         ↓                    ↓
                      继续等待          LLM check 整个缓存
                                        /            \
                                   无转折           有转折(pivot=N)
                                      ↓                ↓
                              check_count             commit 缓存中
                              > 上限？               pivot 之前的消息
                             /       \                    ↓
                           是         否            开新 session
                           ↓          ↓             保留 pivot 及之后
                     强制 commit   继续积累          的消息到新缓存
                        全部                        重置 check_count
```

## 示例

```
轮次 1-5:  用户聊 Python 开发话题
           → 第 5 轮触发 check
           → LLM 判断：无转折
           → 继续

轮次 6-10: 用户继续聊 Python，第 9 轮突然问 AI Agent
           → 第 10 轮触发 check
           → LLM 判断：pivot = 9（第 9 轮 user message 开始转折）
           → commit 轮次 1-8 的消息（16 条）
           → 新 session，缓存保留轮次 9-10 的消息（4 条）
           → check_count 重置为 0
```

## OpenViking 映射

| 操作 | OpenViking API |
|------|---------------|
| 初始化 session | `ov.create_session()` |
| 写入消息 | `ov.add_message(sid, role, content)` |
| 提交记忆 | `ov.commit_session(sid)` |
| 开新 session | `ov.create_session()` + 重新 add 剩余消息 |
| 检索记忆 | `ov.search(query, session_id=sid)` 或 `ov.find(query)` |

## 话题检测 LLM prompt 设计

```
你是一个话题边界检测器。给定一段多轮对话，判断是否存在话题转折。

规则：
- 如果整段对话围绕同一主题，返回 {"pivot": null}
- 如果某条 user message 开始了一个明显不同的话题，返回 {"pivot": N}，
  N 是该 user message 在对话中的序号（从 1 开始，只计 user message）

只输出 JSON，不要解释。
```
