---
name: agents-sdk-gotchas
description: |
  Hard-won gotchas and compatibility notes for developing with the OpenAI Agents SDK
  (openai-agents-python), especially when using alternative API providers like OpenRouter.
  Trigger this skill whenever the user is: writing or debugging Agents SDK code, asking about
  session/memory/callback APIs, using a non-OpenAI base URL and something doesn't work, confused
  by SDK behavior that contradicts the docs, exploring RunConfig options like session_input_callback
  or call_model_input_filter, setting up tracing or observability, working with tool_use_behavior
  or stop_at_tool_names, wrapping agents as tools with as_tool(), processing stream events and
  raw_item access, or asking "why doesn't X work" in an Agents SDK context. Even if the user
  doesn't mention "gotcha" explicitly — if they're working with the Agents SDK and the question
  touches sessions, providers, agent output, tool behavior, or undocumented behavior, consult
  this skill.
---

# OpenAI Agents SDK — Gotchas

A living knowledge base of pitfalls discovered while building with the Agents SDK. Some are
provider-specific (OpenRouter, etc.), others bite you regardless of backend. Add new entries as
gotchas are discovered.

---

## Provider Compatibility (OpenRouter / Non-OpenAI Endpoints)

The Agents SDK is built around OpenAI's Responses API. When the backend isn't OpenAI, some
features break in non-obvious ways. These gotchas apply whenever a non-OpenAI `base_url` is
configured.

### Tracing exports are hardcoded to OpenAI's endpoint

**You'll hit this when:** you set up tracing, everything looks configured correctly, but no
traces appear — no errors either.

The tracing system is architecturally independent from the model provider. It ignores your
`base_url` entirely. `BackendSpanExporter` (in `agents/tracing/processors.py`) hardcodes:

```python
_OPENAI_TRACING_INGEST_ENDPOINT = "https://api.openai.com/v1/traces/ingest"
```

With an OpenRouter API key, auth against this OpenAI endpoint fails silently. There's no env var
override. The confusing part is that spans are created and processed locally — it's only the
export step that quietly drops them.

**Workarounds (pick one):**

1. **Disable tracing** if you don't need it:
   ```python
   from agents.tracing import set_tracing_disabled
   set_tracing_disabled(True)
   ```

2. **External instrumentation** — `openinference-instrumentation-openai-agents` with Arize
   Phoenix gives full visibility regardless of provider.

3. **Custom `TracingProcessor`** — register via `add_trace_processor()`. See the
   `TracingProcessor` interface in `agents/tracing/processor_interface.py` for the abstract
   base and a docstring example.

### Hosted tools raise `UserError`, not silently fail

**You'll hit this when:** you copy working OpenAI code that uses `WebSearchTool` or
`FileSearchTool`, swap the base_url to OpenRouter, and get an immediate crash.

`WebSearchTool`, `FileSearchTool`, `CodeInterpreterTool`, `ImageGenerationTool`, and
`HostedMCPTool` are server-side tools that execute on OpenAI's infrastructure — they're not
model capabilities, they're Responses API features. The execution loop works like: model emits
a tool call → OpenAI's server runs it → result feeds back into the conversation. That loop
doesn't exist on alternative providers.

If the SDK falls back to the ChatCompletions path (common with non-OpenAI providers), you get:

```python
raise UserError(
    "Hosted tools are not supported with the ChatCompletions API. "
    f"Got tool type: {type(tool)}, tool: {tool}"
)
```

Even providers that support the Responses API format can't run these tools — the execution
happens server-side at OpenAI, not at the model provider.

**Workaround:** Implement equivalents as `@function_tool`s. For web search, use an external API
(SerpAPI, Tavily, etc.). For code execution, use a sandboxed local interpreter.

### Server-managed state and compaction are unavailable

**You'll hit this when:** you try `conversation_id`, `previous_response_id`,
`auto_previous_response_id`, or `OpenAIResponsesCompactionAwareSession` on OpenRouter.

These features all rely on OpenAI storing and managing conversation state server-side. On
alternative providers there's no server-side state, so these parameters are silently ignored.

Use client-side `Session` objects (`SQLiteSession`, etc.) for persistence, and handle context
window management yourself through `session_input_callback` or `call_model_input_filter`.

---

## Session & Memory

These gotchas apply regardless of provider — they're about the SDK's session abstraction itself.

### Session items are atomic events, not conversation turns

**You'll hit this when:** you write a `session_input_callback` that assumes alternating
user/assistant messages, and it produces garbled or broken output.

A single user-assistant exchange produces multiple items in the session store:

```python
[
    {"role": "user", "content": "What's the weather in Beijing?"},
    {"type": "function_call", "name": "get_weather", "arguments": '{"city": "Beijing"}', ...},
    {"type": "function_call_output", "call_id": "...", "output": '{"temp": 28}'},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "28C, sunny."}]},
]
```

The item list is a flat sequence of atomic events — user messages, function calls, function
outputs, assistant messages, reasoning items, etc. If your callback naively grabs "every other
item" or counts items to estimate turn boundaries, it will break. Group by logical turns instead
(e.g., scan for `role: "user"` items as turn boundaries).

### Choosing between `session_input_callback` and `call_model_input_filter`

**You'll hit this when:** your summaries aren't persisting across runs, or your "temporary"
truncation is overwriting real session history.

Both hooks modify model input, but at different pipeline stages with different persistence
semantics:

```
Runner.run() starts
  |
  +-- session_input_callback(history, new_input) --> merged items
  |     Affects: model input AND session persistence
  |
  |   ... agent loop (may run multiple turns) ...
  |
  +-- call_model_input_filter(CallModelData) --> ModelInputData
        Affects: this model call only, session untouched
```

Choose based on whether the transformation should be remembered:

- **`session_input_callback`** — for transformations that should persist: summarizing old
  messages, compressing memory, custom merge logic. The returned items get written back to the
  session store, so next run sees the summarized version.

- **`call_model_input_filter`** — for transient adjustments: token-budget trimming, PII
  redaction, dynamic system prompt injection. The session keeps the full unmodified history.

### `session_input_callback` deep-copies inputs for safety

```python
SessionInputCallback = Callable[
    [list[TResponseInputItem], list[TResponseInputItem]],  # (history_items, new_items)
    MaybeAwaitable[list[TResponseInputItem]],               # -> combined items
]
```

The SDK deep-copies both lists before passing them to your callback, so in-place mutations won't
corrupt the original session data. The return value is automatically diffed against the originals
to determine which items are "new" and need persisting — you don't need to track this yourself.

### `SessionSettings(limit=N)` cuts by item count, not by turn — orphaned tool calls crash the API

**You'll hit this when:** you set `SessionSettings(limit=6)` (or any small number), the agent
makes a tool call, and a few turns later the API returns:

```
No tool call found for function call output with call_id call_xxx.
```

`SessionSettings.limit` maps directly to SQL `ORDER BY id DESC LIMIT N`. It has no awareness of
conversation structure. If the cut falls between a `function_call` and its `function_call_output`,
the output is kept but the call is gone — the API rejects this as invalid input.

The SDK does have `drop_orphan_function_calls()` (in `run_internal/items.py`) as a safety net,
which removes call items that lack matching outputs. But this only covers one direction (orphan
calls without outputs). If the **output** is kept and the **call** is dropped, the orphan output
still reaches the API and triggers the error.

**Fix:** Don't rely on `SessionSettings(limit=N)` alone for context management. Use
`session_input_callback` to prune by logical turns instead:

```python
MAX_TURNS = 3  # each turn = user msg + tool calls + assistant reply

def _split_turns(items):
    turns = []
    for item in items:
        if isinstance(item, dict) and item.get("role") == "user":
            turns.append([item])
        elif turns:
            turns[-1].append(item)
    return turns

def session_input_callback(history, new_input):
    turns = _split_turns(history)
    kept = turns[-MAX_TURNS:] if len(turns) > MAX_TURNS else turns
    return [item for turn in kept for item in turn] + new_input
```

Set `SessionSettings(limit=MAX_TURNS * 10)` (or some generous upper bound) so the SQL layer
fetches enough raw items for the callback to work with, and let the callback handle the actual
pruning logic.

### `SessionSettings` vs `session_input_callback` — different layers, different jobs

**You'll hit this when:** you're confused about which one to use, or you set both and get
unexpected behavior.

They operate at different stages of the pipeline:

| | `SessionSettings(limit=N)` | `session_input_callback` |
|---|---|---|
| **Where** | SQL layer (`session.get_items()`) | Python layer, after items are fetched |
| **What it does** | Caps how many raw items are read from SQLite | Transforms/filters items before sending to model |
| **Turn-aware** | No — flat item count | Yes — you control the logic |
| **Persistence** | N/A (read-only) | Returned items affect what gets persisted |

In practice, use `SessionSettings` as a coarse upper bound to avoid loading thousands of items
from the DB, and use `session_input_callback` for the actual context window management logic
(turn-based pruning, summarization, etc.).

---

## Agent Output & Tool Use Behavior

These gotchas relate to how the SDK determines final output and how `tool_use_behavior` interacts
with the run loop.

### Understanding the final output decision flow

**You'll hit this when:** you're confused about why the agent keeps looping, or why it stops
unexpectedly, or what `result.final_output` actually contains.

Each time the model returns a response, the SDK evaluates what to do next in this order:

1. **Interruptions** — any tool needs approval? → pause
2. **Handoffs** — model triggered a handoff? → transfer to another agent
3. **`tool_use_behavior` check** — should tool results become the final output?
   - `"run_llm_again"` (default): never — tool results are fed back to the model
   - `"stop_on_first_tool"`: first tool's return value = `final_output`
   - `{"stop_at_tool_names": ["tool_name"]}`: named tool's return value = `final_output`
4. **No tool calls in response** → the model's text output is the final output
5. **Tools were called** (and step 3 didn't stop) → `NextStepRunAgain()`, loop back with tool
   results so the model can continue reasoning

The key subtlety: step 3 checks whether **already-executed tool results** should be the answer.
Step 5 checks whether the model **produced any tool calls at all** — if it did, the results need
to be fed back. These are different questions, which is why both exist.

### `stop_at_tool_names` — the tool's return value becomes `final_output`

**You'll hit this when:** you use `tool_use_behavior={"stop_at_tool_names": ["end_of_turn"]}` and
`result.final_output` contains the tool's return value, not the text the model generated.

When a named tool is called, the SDK sets `final_output` to that tool's return value (the string
returned by your `@function_tool` function). If the tool returns an empty string, `final_output`
will be empty — which may trigger an "Agent returned an empty response" check in your server code.

```python
# BAD — final_output will be ""
@function_tool
def end_of_turn() -> str:
    return ""

# GOOD — final_output will be "end_of_turn"
@function_tool
def end_of_turn() -> str:
    return "end_of_turn"
```

If you're using a tool-based interaction model (e.g., `response_to_user` for output,
`end_of_turn` to signal completion), don't rely on `result.final_output` for the actual response
content. Capture `response_to_user` tool outputs from stream events instead.

### Stream event item types have inconsistent access patterns

**You'll hit this when:** you process `RunItemStreamEvent`s and access `raw_item` fields, but
`getattr` works for one event type and `dict.get()` works for another.

When handling `run_item_stream_event`:
- **`tool_called`** events: `raw_item` is a **Pydantic model** (`ResponseFunctionToolCall`).
  Use `getattr(raw, "call_id", None)` and `getattr(raw, "name", None)`.
- **`tool_output`** events: `raw_item` is a **TypedDict** (`FunctionCallOutput`).
  Use `raw.get("call_id")` and `raw.get("output")`.

This is because the SDK wraps model outputs (Pydantic) differently from locally-constructed tool
results (TypedDict). To be safe, handle both:

```python
def safe_get(raw, field):
    if isinstance(raw, dict):
        return raw.get(field)
    return getattr(raw, field, None)
```

---

## Agent-as-Tool (`as_tool()`)

### Default `as_tool()` input schema leaks a useless description to the model

**You'll hit this when:** you check the tool schema in traces (e.g., Phoenix) and see
`"description": "Default input schema for agent-as-tool calls."` in the parameters object.

When you call `agent.as_tool()` without a custom `parameters` argument, the SDK uses
`AgentAsToolInput` — a Pydantic model with a single `input: str` field. Pydantic automatically
converts the class docstring into the JSON Schema `description` field. This description is sent
to the model as part of the tool definition:

```json
{
  "name": "recall_memory",
  "description": "Your tool_description here",
  "parameters": {
    "description": "Default input schema for agent-as-tool calls.",
    "properties": { "input": { "type": "string" } },
    "required": ["input"]
  }
}
```

The `parameters.description` is unhelpful but harmless. The model primarily uses the top-level
`tool_description` you provide. If you want to give the model better parameter-level guidance,
pass a custom Pydantic model:

```python
from pydantic import BaseModel, Field

class MemoryQuery(BaseModel):
    """Search the user's memory store."""
    input: str = Field(description="Natural language query to search memories")

agent.as_tool(
    tool_name="recall_memory",
    tool_description="Look up user facts and preferences",
    parameters=MemoryQuery,
)
```

---

## API Gaps & Undocumented Behavior

### `call_model_input_filter` lacks official examples

**You'll hit this when:** you try to find docs or examples for this hook and come up empty.

As of v0.12.x, `call_model_input_filter` is defined in `RunConfig` with a docstring but no
official runnable example. The only snippet in docs:

```python
def drop_old_messages(data: CallModelData[None]) -> ModelInputData:
    trimmed = data.model_data.input[-5:]
    return ModelInputData(input=trimmed, instructions=data.model_data.instructions)
```

Read the SDK source (`agents/run_config.py`, `agents/run_internal/session_persistence.py`) to
understand exactly how it integrates into the run pipeline.

---

## Maintaining This Document

Add new gotchas under the appropriate section, or create a new section if none fits. Each entry
needs: a descriptive heading, a "You'll hit this when" line so the reader can pattern-match their
situation, an explanation of the underlying mechanism (not just symptoms), and the workaround.
Include code snippets where they clarify.
