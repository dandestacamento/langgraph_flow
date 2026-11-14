# Learnings from `langgraph-course-project-reflection-agent`

Source: [reference/langgraph-course-project-reflection-agent](../../reference/langgraph-course-project-reflection-agent/langgraph-course-project-reflection-agent/) — Eden Marco's LangGraph course project implementing the **Reflection** pattern: a generator and a critic LLM arguing with each other until the output is "good enough" (or a fixed iteration budget runs out). Example use case: iteratively improving a tweet.

---

## 1. What the project does (big picture)

```
__start__ ──► generate ──(len(messages) <= 6)──► reflect ──► generate ──► ... ──► END
```

1. **generate**: writes (or revises) a tweet based on the full message history so far.
2. **reflect**: critiques the latest tweet, returning specific, actionable feedback.
3. The critique is appended to the message list and fed back into `generate` as if it were user input.
4. Loop continues until the message list exceeds a length threshold (6 messages ≈ 3 generate/reflect rounds), then terminates.

This is the simplest possible **self-improvement loop**: two prompts, one shared message list, one length-based stop condition. No tools, no retrieval, no structured output — just two adversarial/cooperative chat roles iterating.

---

## 2. Key patterns worth copying

### `MessageGraph` — a graph that *is* a message list
```python
from langgraph.graph import MessageGraph
builder = MessageGraph()
```
- Unlike `StateGraph(MessagesState)` (dict with a `messages` key) or a custom `TypedDict`, `MessageGraph`'s entire state *is* `List[BaseMessage]`. Nodes receive the list directly and return messages to append.
- Simplest possible state shape for a pure back-and-forth dialogue between two roles — no key lookups (`state["messages"]`), just `state` itself.
- Trade-off vs `MessagesState`: `MessageGraph` can't carry any side-channel data (no `web_search` flag, no `documents` list) — purely a chat transcript. Use it only when the whole problem *is* a conversation.

### Role-reversal trick: critique becomes a `HumanMessage`
```python
def reflection_node(messages):
    res = reflect_chain.invoke({"messages": messages})
    return [HumanMessage(content=res.content)]
```
The reflection LLM's critique (an AI-ish message) is deliberately wrapped as a `HumanMessage` before being appended. This makes the next `generate` call see the critique as if a user asked for a revision — exploiting the chat format rather than needing special "critique" message types or custom prompt branches. Simple and effective pattern: **wrap feedback as a user turn so the next role naturally responds to it.**

### Two independent prompts/chains sharing one message history
```python
generate_chain = generation_prompt | llm
reflect_chain = reflection_prompt | llm
```
Both prompts use `MessagesPlaceholder(variable_name="messages")` to inject the same running history, but each has a **different system prompt** establishing a different persona/goal (writer vs. grader). One shared transcript, two distinct "lenses" applied to it — much lighter weight than the chains/nodes split in the agentic-rag project, appropriate for this simpler two-role loop.

### Length-based termination instead of LLM-graded termination
```python
def should_continue(state: List[BaseMessage]):
    if len(state) > 6:
        return END
    return REFLECT
```
Contrast with agentic-rag's hallucination/answer graders (LLM-judged stop condition) or the ReAct agent's `tool_calls` presence check. Here, stopping is a **cheap structural heuristic** (message count) rather than another LLM call — fine for a bounded "polish this N times" task, but it stops after a fixed number of rounds regardless of whether quality has actually converged.

### Graph introspection without rendering a PNG
```python
print(graph.get_graph().draw_mermaid())
graph.get_graph().print_ascii()
```
Unlike the other two course projects (which call `draw_mermaid_png(...)`), this one prints the Mermaid source and an ASCII diagram directly to the console — useful when you don't want a file artifact or a graphviz/mermaid-cli dependency, just a quick visual sanity check at import time.

---

## 3. Comparison across the three course projects reviewed so far

| | Reflection agent | ReAct agent | Agentic RAG |
|---|---|---|---|
| State | `MessageGraph` (bare message list) | `MessagesState` (dict w/ messages key, append) | custom `TypedDict` (overwrite) |
| Loop driver | message-count threshold | presence of `tool_calls` | LLM graders (structured output) |
| Roles | 2 fixed personas (generator, critic) sharing a transcript | 1 LLM + tools | router + 2 node chains + 2 grader chains |
| External actions | none (pure LLM dialogue) | tool calls (web search, custom tool) | vectorstore retrieval + web search |
| Good for | polish/critique tasks with a bounded budget | open-ended tool-using tasks | gated pipelines needing quality/grounding checks |

Together these three form a spectrum from "loop until budget exhausted" → "loop until model stops acting" → "loop until model-graded quality passes," each appropriate to a different kind of problem.

---

## 4. Weaknesses / things to do better

- **Fixed iteration cap with no quality check**: stopping at `len(state) > 6` means the loop always runs the same number of rounds whether the 1st revision was already great or the 6th is still bad. Pair this with agentic-rag's grader pattern (e.g., stop early if a "tweet quality" grader says "good") for a smarter budget.
- **No tests at all** — the two chains (`generate_chain`, `reflect_chain`) are trivially testable in isolation (like agentic-rag's `test_chains.py`): feed a bad tweet, assert the critique mentions something specific; feed critique + original, assert the regenerated tweet differs.
- **`generation_node`/`reflection_node` type hints are loose** (`Sequence[BaseMessage]` vs `List[BaseMessage]` inconsistently) — minor, but worth tightening for consistency.
- **No system-level validation** that the critique actually gets incorporated — the loop blindly trusts that appending a `HumanMessage` critique will steer the next generation; no check that revision count increases quality (same risk as above).
- **Default `ChatOpenAI()`** (no `temperature=0`) — fine for creative tweet generation, but note this is the opposite choice from agentic-rag's graders, which pinned `temperature=0` for deterministic yes/no decisions. Match temperature to the task: creative generation benefits from default/higher temperature, graders benefit from `0`.

---

## 5. Ideas applicable to `routing/` and `smarthome-csr/`

1. **Reflection as a quality-improvement node**: wrap any single-shot generation step (e.g., a customer-facing reply) with a generate→reflect→regenerate loop before returning the final answer, especially for user-facing copy (notifications, summaries, routed responses).
2. **Role-reversal trick**: when feeding model-generated feedback back into another model call, format it as the role the *recipient* expects (e.g., as a `HumanMessage`) rather than inventing new message types or system-prompt branches.
3. **Combine with agentic-rag's grading pattern**: use an LLM-graded stop condition ("is this response good enough?") instead of/alongside a fixed iteration cap, to avoid wasted rounds or premature cutoff.
4. **`MessageGraph` for pure dialogue sub-flows**: if a routing/CSR task needs a short internal back-and-forth (e.g., clarify intent with itself before responding), a bare `MessageGraph` sub-graph is lighter weight than a full custom `TypedDict` state.
5. **Console `print_ascii()` for quick architecture sanity checks** during development, reserving `draw_mermaid_png` for final documentation artifacts.
