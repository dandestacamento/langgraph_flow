# Learnings from `langgraph-course-project-ReAct-agent`

Source: [reference/langgraph-course-project-ReAct-agent](../../reference/langgraph-course-project-ReAct-agent/) — Eden Marco's LangGraph course project implementing the **ReAct pattern** (Reason → Act → observe → Reason again) as a minimal two-node graph.

---

## 1. What the project does (big picture)

The agent answers a question ("what is the weather in sf? List it and then Triple it") by looping between reasoning and tool execution:

1. **agent_reason**: LLM (with tools bound) reads the message history and either answers directly or emits `tool_calls`.
2. **should_continue** (conditional edge): if the last message has `tool_calls` → go to **act**; otherwise → END.
3. **act**: LangGraph's prebuilt `ToolNode` executes the tool calls and appends `ToolMessage` results.
4. Edge back to **agent_reason** — the loop repeats until the LLM stops calling tools.

```
__start__ ──► agent_reason ──(tool_calls?)──► act ──► agent_reason
                   │
                   └──(no tool_calls)──► END
```

This is the canonical **agent loop** — the same engine behind `create_react_agent`, written out by hand in ~40 lines.

---

## 2. Key patterns worth copying

### MessagesState instead of a custom TypedDict
```python
flow = StateGraph(MessagesState)
```
- `MessagesState` is a built-in state with a single `messages` key using an **append reducer** (`add_messages`): nodes return `{"messages": [response]}` and LangGraph *appends* rather than overwrites.
- Contrast with the agentic-rag project, which used a flat custom `GraphState` with overwrite semantics. Rule of thumb: **conversation-style agents → MessagesState; pipeline-style flows → custom TypedDict**.

### Prebuilt ToolNode — don't hand-roll tool dispatch
```python
tool_node = ToolNode(tools)
```
One line replaces manual "parse tool_calls → look up tool → invoke → wrap in ToolMessage" plumbing, including parallel execution of multiple tool calls and error wrapping.

### bind_tools + tool_calls as the loop condition
```python
llm = ChatOpenAI(model="gpt-4o-mini").bind_tools(tools)

def should_continue(state: dict) -> str:
    if not state["messages"][LAST].tool_calls:
        return END
    return ACT
```
- `bind_tools(tools)` makes the model emit structured `tool_calls` — the presence/absence of `tool_calls` on the **last message** *is* the control flow. No router chain, no structured-output grader needed for this pattern.
- `LAST = -1` named constant is a nice readability touch over bare `-1`.

### @tool decorator for custom tools
```python
@tool
def triple(num: float) -> float:
    """:param num: a number to triple ..."""
    return 3 * float(num)
```
- The docstring + type hints become the tool schema the LLM sees — **the docstring is the prompt**. Mixing a prebuilt tool (`TavilySearch`) with custom `@tool` functions in one list is seamless.

### System message injected per-call, not stored in state
```python
response = llm.invoke([{"role": "system", "content": SYSTEM_MESSAGE}, *state["messages"]])
```
The system prompt is prepended at invoke time rather than persisted in `messages` — keeps state clean and lets you change the system prompt without migrating state.

### Same hygiene as the other course projects
- Node names as constants (`AGENT_REASON`, `ACT`).
- `END` used directly as a branch key in the conditional-edge mapping.
- `app.get_graph().draw_mermaid_png(output_file_path="graph.png")` to auto-render the architecture (the README even embeds the mermaid source).
- Thin `main.py` entry point; `load_dotenv()` before importing anything that reads env vars.

---

## 3. ReAct loop vs. agentic-rag's explicit pipeline (when to use which)

| | ReAct agent (this project) | Agentic RAG |
|---|---|---|
| Control flow | **LLM-driven**: model decides which tool, when, and when to stop | **Graph-driven**: fixed nodes, LLM only picks branches via graders |
| State | `MessagesState` (append) | Custom TypedDict (overwrite) |
| Branch mechanism | presence of `tool_calls` | structured-output Pydantic graders |
| Good for | open-ended tasks, variable tool sequences, multi-step tool chaining | predictable pipelines needing quality gates (grading, verification) |
| Risk | unbounded loops, unpredictable paths | rigidity, more LLM calls per answer |

The test prompt ("get weather, then triple it") deliberately forces **sequential multi-tool reasoning** — a good smoke-test prompt pattern for verifying the loop actually iterates.

---

## 4. Weaknesses / things to do better

- **No loop cap in the graph**: nothing stops the model from calling tools forever (LangGraph's default `recursion_limit=25` is the only safety net). In production, pass `config={"recursion_limit": N}` deliberately or track an iteration counter in state with a graceful fallback.
- **No tests** (unlike agentic-rag's chain tests). The conditional function `should_continue` and custom tools are trivially unit-testable — do that.
- `should_continue(state: dict)` is untyped — should be `MessagesState` for consistency with the nodes.
- `nodes.py` declares return type `MessagesState` but returns a partial dict — fine at runtime (LangGraph merges), but `Dict[str, Any]` (as agentic-rag used) is the honest annotation.
- `load_dotenv()` is called in three files (main, nodes, react) — harmless but redundant; one call at the entry point suffices if imports happen after it.
- `triple` does `3 * float(num)` even though `num: float` is already coerced by the schema — redundant cast.

---

## 5. Ideas applicable to `routing_lab/` and `smarthome-csr/`

1. **Use ToolNode + bind_tools** for any agent that picks among tools (e.g., smart-home device actions): let `tool_calls` drive the act/finish decision instead of writing a custom dispatcher.
2. **MessagesState with append semantics** for conversational CSR flows — the full dialogue history is the state, no manual history bookkeeping.
3. **Hybrid architecture**: embed this ReAct loop *as a node* inside a larger graded pipeline — e.g., a routing graph (agentic-rag style) that routes a request to a ReAct sub-agent, then grades its output before responding.
4. **Multi-step smoke-test prompts** ("do X, then do Y with the result") to verify tool-chaining actually loops.
5. **Set an explicit recursion limit** on any invoke of a looping graph.
