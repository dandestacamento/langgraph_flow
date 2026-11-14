# Learnings from `langgraph-course-project-agentic-rag`

Source: [reference/langgraph-course-project-agentic-rag](../../reference/langgraph-course-project-agentic-rag/) — Eden Marco's LangGraph course project implementing **Adaptive RAG + Self-RAG + Corrective RAG** patterns in a single graph.

---

## 1. What the project does (big picture)

A question comes in and the graph:

1. **Routes** it (LLM router) to either the **vectorstore** (RAG) or **web search** (Tavily).
2. If RAG: **retrieves** docs, then **grades each document** for relevance.
3. If any doc is irrelevant → falls back to **web search** to supplement context (Corrective RAG).
4. **Generates** an answer, then **grades the generation** twice (Self-RAG):
   - Hallucination check: is the answer grounded in the documents?
   - Answer check: does it actually address the question?
5. Loops back (regenerate or re-search) until the answer is "useful", then ends.

```
route_question ──► websearch ──► generate ──► END (useful)
      │                ▲             │ ▲
      ▼                │             ▼ │ (not supported → retry generate)
   retrieve ──► grade_documents ─────┘ (not useful → websearch)
```

---

## 2. Project structure conventions worth copying

```
graph/
  consts.py          # node-name string constants
  state.py           # GraphState TypedDict
  graph.py           # wiring: nodes, edges, conditional edges, compile
  nodes/             # one file per node, re-exported via __init__.py
    retrieve.py, grade_documents.py, generate.py, web_search.py
  chains/            # one file per LLM chain (prompt | llm | parser)
    router.py, retrieval_grader.py, hallucination_grader.py,
    answer_grader.py, generation.py
    tests/test_chains.py
ingestion.py         # offline: load → split → embed → persist Chroma
main.py              # thin entry point: load_dotenv() then app.invoke()
```

Key ideas:

- **Separate "chains" from "nodes"**: chains are pure LLM pipelines (prompt + structured output), nodes are graph-state adapters that call chains. Chains can then be unit-tested in isolation without running the graph.
- **Node names as constants** (`consts.py`): `RETRIEVE = "retrieve"` etc. — avoids typo bugs since LangGraph edges are addressed by string name.
- **Nodes return partial state dicts** (`Dict[str, Any]`), not full state. LangGraph merges them into `GraphState`.
- **Ingestion is decoupled from runtime**: the `Chroma.from_documents(...)` build code is commented out; at runtime the persisted store (`persist_directory="./.chroma"`) is just reopened as a retriever. Embed once, query many times.

---

## 3. Structured output for every decision point

Every grading/routing decision uses `llm.with_structured_output(PydanticModel)` so control flow is driven by typed fields, never by parsing free text:

```python
class RouteQuery(BaseModel):
    datasource: Literal["vectorstore", "websearch"] = Field(...)

question_router = route_prompt | llm.with_structured_output(RouteQuery)
```

- `Literal[...]` constrains the router to valid branch names.
- Graders return a `binary_score` (`bool` for hallucination/answer graders, `"yes"/"no"` str for retrieval grader — the bool version is cleaner; the string version requires `grade.lower() == "yes"` comparisons).
- `temperature=0` on all grader/router LLMs for deterministic decisions.
- The Field `description` doubles as instruction to the model — keep it precise.

---

## 4. LangGraph wiring patterns

- **Conditional entry point**: `workflow.set_conditional_entry_point(route_question, {WEBSEARCH: WEBSEARCH, RETRIEVE: RETRIEVE})` — routing happens *before* any node runs. The mapping dict maps *returned values* → *node names*.
- **Conditional edges with multi-way mapping**:

  ```python
  workflow.add_conditional_edges(
      GENERATE,
      grade_generation_grounded_in_documents_and_question,
      {"not supported": GENERATE,   # self-loop: regenerate
       "useful": END,
       "not useful": WEBSEARCH},    # escalate: fetch more context
  )
  ```

  Branch keys can be human-readable labels ("useful"), not just node names.
- **Self-correction loops** are just conditional edges pointing back at earlier nodes (GENERATE → GENERATE, GENERATE → WEBSEARCH → GENERATE).
- **Graph visualization**: `app.get_graph().draw_mermaid_png(output_file_path="graph.png")` at compile time — free architecture documentation that stays in sync with code.
- Decision functions print `---DECISION: ...---` banners — crude but effective tracing when you don't have LangSmith/MLflow attached.

## 5. State design

```python
class GraphState(TypedDict):
    question: str
    generation: str
    web_search: bool      # flag set by grader, read by conditional edge
    documents: List[str]
```

- Keep state **minimal and flat**; only what downstream nodes/edges need.
- The `web_search: bool` flag pattern: a node (grade_documents) records a *decision input*, and a separate lightweight edge function (`decide_to_generate`) reads it to pick the branch. Node = does work + annotates state; edge function = pure branch selection.
- `grade_documents` also **filters** state: irrelevant docs are dropped so generation only sees graded-relevant context.

## 6. Testing approach

[test_chains.py](../../reference/langgraph-course-project-agentic-rag/graph/chains/tests/test_chains.py) tests each chain independently of the graph, with **paired positive/negative cases**:

- relevant doc → `binary_score == "yes"`; off-topic question ("how to make pizza") → `"no"`
- grounded generation → hallucination grader passes; fabricated text → fails
- on-topic question routes to `vectorstore`; off-topic routes to `websearch`

Lesson: when LLM calls drive control flow, test the *deciders* directly with contrastive examples — much faster to debug than end-to-end graph runs.

## 7. Weaknesses / things to do better in our projects

- **`web_search.py` has a latent bug**: `documents` may be referenced before assignment when the router sends a query straight to web search (the `if "documents" in state:` guard doesn't initialize it on the else path). Lesson: initialize optional state keys explicitly, or use `state.get("documents") or []`.
- **Dead wiring**: `workflow.set_entry_point(RETRIEVE)` is called right after `set_conditional_entry_point(...)`, overriding/conflicting with it; `add_edge(GENERATE, END)` coexists with the conditional edge from GENERATE. Lesson: a graph diagram render helps catch contradictory edges.
- **No retry cap**: the `not supported → GENERATE` loop can cycle forever if generation never grounds. In production, add a retry counter in state (or `recursion_limit`) with a graceful fallback.
- **Per-document grading is N sequential LLM calls** — expensive and slow. Consider batching (`.batch()`), one call grading all docs, or a cheaper model for grading.
- Module-level singletons (`llm = ChatOpenAI(...)` at import time) make configuration/mocking harder; factory functions or dependency injection scale better.
- Web search results are collapsed into **one** `Document` (joined contents) — loses source attribution; keep per-result Documents with URL metadata if citations matter.

## 8. Ideas applicable to `routing/` and `smarthome-csr/`

1. **Conditional entry point** for intent routing — route before doing any work, using structured output with `Literal` branch names.
2. **Grade-then-fallback (Corrective) pattern**: after any retrieval/tool step, grade the output's usefulness and branch to an alternate source instead of answering from bad context.
3. **Post-generation verification (Self-RAG)**: hallucination + answer-quality graders as conditional edges after generation, with bounded retry loops.
4. **consts.py for node names** and **chains/ vs nodes/ separation** to keep graph wiring readable and chains unit-testable.
5. **Contrastive chain tests** (positive + negative example per decider) as the test backbone.
6. **Auto-render graph.png** on compile so the architecture diagram never drifts from the code.
