# Learnings from `rag_krish`

Source: [reference/rag_krish](../../reference/rag_krish/) — by far the richest reference project reviewed so far. It's a sprawling, production-leaning playground that implements **a full multi-format RAG pipeline** plus **nine distinct LangGraph agent architectures** (prompt chaining, parallelization, orchestrator-worker, multi-agent network/supervisor, single-purpose middleware agent, deep/plan-and-delegate agent, knowledge-graph RAG, long-term/auto memory, and a flagship ReAct chat agent with three self-correction loops), wrapped in Streamlit UIs, Docker/Prometheus/Neo4j infra, and a distinctive **README-driven test suite**. Unlike the three small course projects reviewed earlier, this one reads like a real internal engineering playground — worth mining for both good patterns and cautionary flaws.

Read via three parallel deep-dive explorations covering [agent_core/](../../reference/rag_krish/agent_core/), [rag/](../../reference/rag_krish/rag/), and the top-level apps/tests/infra.

---

## 1. Project shape

```
rag_krish/
  rag/                  # format-agnostic ingestion + retrieval library
    config.py, core.py, loaders.py, manifest.py, retrieval.py, splitting.py, text_utils.py
  agent_core/            # one module per LangGraph architecture pattern
    graph.py             # flagship ReAct chat agent (corrective RAG + hallucination + reflection)
    state.py, tools.py, memory.py, moderation.py, checkpointing.py, observability.py
    multi_agent_graphs.py, orchestrator_worker_graph.py, parallelization_graph.py,
    prompt_chaining_graph.py, single_purpose_agent_graph.py, deep_agent_graph.py,
    knowledge_graph_graph.py, auto_memory_graph.py
    skills/<name>/SKILL.md   # plugin-style domain guidance for sub-agents
  rag_app.py, *_app.py    # one thin CLI entry point per pattern/graph
  streamlit_app.py, agent_streamlit_app.py, multi_agent_streamlit_app.py
  tests/                 # README-driven integration tests + PII unit test
  data/, topics/, index/  # ingested content + per-topic FAISS indexes + manifest cache
  Dockerfile, docker-compose.yml, monitoring/, neo4j/
  Readme.md, Agentic_Readme.md   # also serve as the test-question source of truth
```

Each `*_app.py` is a thin runnable facade over a `build_*` function in `agent_core/`; most demos are deliberately **not** wired into the main RAG UI — they're independent, swappable playgrounds for one architecture each. This "one pattern, one module, one app, one test file" structure is itself a reusable convention for a teaching/reference repo.

---

## 2. The flagship agent: three complementary self-correction loops ([agent_core/graph.py](../../reference/rag_krish/agent_core/graph.py))

This is the most sophisticated pattern in the repo and directly extends the three course projects already reviewed. `build_chat_agent(checkpointer=None)` wires:

```
chatbot ──(tool_calls?)──► tools ──► grade_tool_results ──(bad?)──► rewrite ──► chatbot
   │                                      │
   │                                (good)▼
   └──(final answer)──► check_hallucination ──(ungrounded?)──► chatbot (retry)
                                 │(grounded)
                                 ▼
                              reflect ──(incomplete?)──► chatbot (retry)
                                 │(complete)
                                 ▼
                                END
```

- **Corrective RAG** (`grade_tool_results` + `rewrite`): grades whether tool results are relevant/sufficient; if not, reformulates the question and retries — directly analogous to agentic-rag's `grade_documents`/websearch-fallback pattern, but applied generically to *any* tool result, not just vectorstore docs.
- **Hallucination check** (`check_hallucination`): grades whether the final answer is grounded in *this turn's* tool results before accepting it.
- **Self-reflection** (`reflect`): grades whether the (now-grounded) answer actually, fully addresses the question.
- All three loops are **capped at one retry each** via counters (`rewrite_count`, `hallucination_count`, `reflect_count`) plus a separate `tool_round_count` (6-round cap) — this is the fix for the uncapped-retry weakness flagged in the agentic-rag learnings doc.
- Structured-output Pydantic graders (`_RelevanceGrade`, `_HallucinationGrade`, `_AnswerAdequacy` with `Literal["yes","no"]` + a `feedback` field) make every decision point typed and validated, same discipline as agentic-rag.
- **Weakness**: none of the four counters are reset in the graph itself, and with a persistent checkpointer they can leak across conversation turns on the same thread, silently disabling retries after the first "bad" turn. **Lesson: any per-turn retry/loop counter stored in checkpointed state must be explicitly reset at the start of each new turn**, not just initialized once.
- **Weakness**: the 6-round tool cap still forces a best-effort answer rather than surfacing "I couldn't find a good answer" — same trade-off as the hard iteration caps seen in the reflection-agent and deep-agent patterns.

---

## 3. RAG ingestion/retrieval library ([rag/](../../reference/rag_krish/rag/)) — production-grade patterns beyond the course projects

This is a much more mature ingestion pipeline than `ingestion.py` in the agentic-rag course project (which just re-embedded everything every run).

### a) Manifest-based incremental indexing — avoid re-embedding unchanged files
```python
# rag/manifest.py — chunk_id ties a chunk to its source + normalized text
def chunk_id(source: str, chunk_text: str) -> str:
    normalized = " ".join(chunk_text.split()).strip()
    return hashlib.sha256(f"{source}::{normalized}".encode("utf-8")).hexdigest()
```
- The manifest (`index/manifest.json`) records, per source file: `mtime` (nanoseconds), `size`, `chunk_ids`, and a whole-file `content_hash`.
- A top-level `ingest_signature` (`"recursive:800:120:text-embedding-3-small"` = splitter:chunk_size:chunk_overlap:embedding_model) triggers a **full rebuild** if any of those config values change — the index is always consistent with how it was built, never silently stale.
- Otherwise, `update_index()` diffs current files against the manifest by mtime+size, re-embeds only changed/added sources, and **reuses existing vectors** for unchanged ones. It even detects renames via a content-hash match between a deleted and an added path.
- **This is the single most valuable idea in the whole repo for your `routing/` project**: any FAISS/Chroma-backed index that gets rebuilt on a schedule or on-demand should use a manifest like this instead of blind full re-ingestion, especially once the corpus grows.
- **Flagged weakness**: mtime+size change detection can miss an edit that preserves both (rare but possible); rename detection depends on extracted *document* content, not raw bytes, so extraction differences can break it.

### b) Pluggable splitter strategies, selected by one factory
```python
# rag/splitting.py
if splitter_type == "semantic":
    # Splits on sentence-embedding similarity breakpoints instead of a fixed
    # size, so chunk_size/chunk_overlap are not used in this mode.
    return SemanticChunker(embeddings)
```
`recursive` / `character` / `token` / `semantic` all live behind one `build_splitter()` function, validated against an allow-list in `config.py`. Each chunk's metadata records `chunk_index` and `splitter_type` — handy for debugging which strategy produced which retrieved chunk.

### c) Hybrid retrieval = vector + BM25 via `EnsembleRetriever`
```python
# rag/retrieval.py
documents = list(vector_store.docstore._dict.values())
bm25_retriever = BM25Retriever.from_documents(documents)
bm25_retriever.k = k
vector_retriever = vector_store.as_retriever(search_kwargs={"k": k})
return EnsembleRetriever(retrievers=[vector_retriever, bm25_retriever], weights=[0.7, 0.3])
```
Three retrieval modes (`similarity`, `mmr`, `hybrid`) are picked per-query from the UI with **no index rebuild required** — only the splitter/embedding-model choice forces a rebuild, because only those change the vectors themselves. Optional cross-encoder reranking (fetch 10 → `ContextualCompressionRetriever`/`CrossEncoderReranker` → top 4) is layered independently on top.
- **Flagged weakness**: rebuilding BM25 from `vector_store.docstore._dict` (a private LangChain attribute) on every retriever construction couples the code to FAISS internals and redoes the BM25 build each time.

### d) Query expansion as a pre-retrieval LLM rewrite
```python
def expand_query(llm, question: str) -> str:
    """Rewrite a short/ambiguous question... adding synonyms, technical terms, and useful context."""
    response = llm.invoke(prompt)
    return response.content
```
Optional, opt-in (`query_enhancement="expansion"`), unstructured (no validation/fallback) — simpler than agentic-rag's structured router/graders, appropriate since this is a one-shot rewrite rather than a branch decision.

### e) Format-agnostic multi-loader design ([rag/loaders.py](../../reference/rag_krish/rag/loaders.py))
One function per format (txt, pdf, docx, json, jsonl, sqlite/db, csv, xlsx), all normalizing into `langchain_core.documents.Document(page_content=..., metadata=...)`, combined in a single `load_documents()`. Notable sub-patterns:
- PDFs/DOCX get a minimum-character-length filter (`MIN_PAGE_CHARS`) to drop near-empty pages.
- JSON root lists → one Document per record; root objects → list-fields become records, scalar fields become a summary record.
- SQLite loader generates a **schema document** plus **row documents** per table — makes structured DB content retrievable by plain-text RAG without writing SQL-aware retrieval logic.
- **Flagged weakness (worth fixing if reused)**: SQLite table names are interpolated directly into SQL (`PRAGMA table_info({table_name})`, `SELECT * FROM {table_name}`) with no identifier quoting — fragile/unsafe for untrusted DB files.

### f) Central config with validated allow-lists
`rag/config.py` centralizes paths and allowed (splitter, embedding model, retrieval mode, query-enhancement) tuples; `MultiFormatRAG.__init__()` validates constructor args against these allow-lists rather than trusting caller input — cheap, effective guard against silently-wrong configuration (e.g., a typo'd splitter name falling through to default behavior unnoticed).

---

## 4. Other agent architecture patterns worth knowing

| Pattern | Module | Core idea |
|---|---|---|
| **Sequential prompt chaining** | [prompt_chaining_graph.py](../../reference/rag_krish/agent_core/prompt_chaining_graph.py) | Fixed 5-step pipeline `gather_facts → draft → fact_check → improve → format`, each step constrained to only use previously-gathered facts. Simplest possible multi-step pattern; no branching at all. |
| **Parallelization (fan-out/fan-in)** | [parallelization_graph.py](../../reference/rag_krish/agent_core/parallelization_graph.py) | Three independent summarizer nodes started directly from `START` (multiple start edges = concurrent execution in LangGraph), converging on one aggregator. |
| **Orchestrator-worker (dynamic fan-out)** | [orchestrator_worker_graph.py](../../reference/rag_krish/agent_core/orchestrator_worker_graph.py) | An LLM-generated `QuestionPlan` (2-4 sub-questions) is dispatched via LangGraph's `Send()` API — a *variable* number of worker instances, not a fixed set of nodes. Worker findings aggregate into `Annotated[List[dict], add]`. This is the key technique for "split a compound question into N parallel sub-tasks where N isn't known until runtime." |
| **Multi-agent network (handoff)** | [multi_agent_graphs.py](../../reference/rag_krish/agent_core/multi_agent_graphs.py) `build_network_agent()` | Two `create_react_agent`s (researcher → writer) hand off via `Command`, with a `"FINAL ANSWER"` substring marking completion — simple but fragile (magic-string protocol, no iteration cap). |
| **Multi-agent supervisor** | same file, `build_supervisor_agent()` | A supervisor node routes to `knowledge_agent`/`business_agent`/`FINISH` using a structured `Literal` Pydantic route — same router-via-structured-output idea as agentic-rag's `RouteQuery`, applied to agent selection instead of datasource selection. |
| **Single-purpose agent w/ middleware** | [single_purpose_agent_graph.py](../../reference/rag_krish/agent_core/single_purpose_agent_graph.py) | Uses the newer `create_agent` (not `StateGraph` directly) with **typed runtime context** (`ResearchContext`), `@wrap_model_call` (tier-based model params), `@dynamic_prompt` (tier-specific system prompt), `@wrap_tool_call` (centralized tool error handling), and `ToolStrategy(ResearchResponse)` for structured final output. This is the most "framework-idiomatic" modern pattern in the repo — worth studying if adopting newer LangGraph/LangChain agent middleware APIs. |
| **Deep/plan-and-delegate agent** | [deep_agent_graph.py](../../reference/rag_krish/agent_core/deep_agent_graph.py) | `plan → (work_on_task → think)* → write_report`. An LLM-generated `TodoPlan` assigns each task to a named sub-agent persona (`rag-researcher` or `web-researcher`), each with its **own restricted tool set** and a **skill file** loaded into its prompt (see §5). Findings accumulate in an in-memory virtual filesystem (`files` dict) rather than a shared conversation — keeps each sub-task's context isolated. |
| **Knowledge-graph RAG** | [knowledge_graph_graph.py](../../reference/rag_krish/agent_core/knowledge_graph_graph.py) | Not a compiled graph — a Neo4j-backed retrieval utility. Combines structured graph-neighborhood lookups (full-text + fuzzy Lucene `OR` queries over a shared `__Entity__` label) with vector search over document chunks, feeding both into one prompt. Good reference for "graph RAG" if a routing/smarthome project ever needs entity-relationship reasoning alongside document retrieval. |
| **Auto/long-term memory** | [auto_memory_graph.py](../../reference/rag_krish/agent_core/auto_memory_graph.py), [memory.py](../../reference/rag_krish/agent_core/memory.py) | Two memory designs: (1) **automatic** `retrieve_memories → chatbot → extract_memories` using LangGraph's `InMemoryStore` namespaced `(user_id, "memories")` — no model-driven tool calls needed; (2) **tool-driven** `remember`/`recall` tools backed by a persistent per-user FAISS index (`LongTermMemory`), used by the flagship agent. The tool-driven version is durable (disk-backed); the automatic version is process-local only (`InMemoryStore`) — pick based on whether memory must survive a restart. |

---

## 5. The `skills/` plugin convention — directly relevant to how *this agent* works

```
agent_core/skills/
  rag-researcher/SKILL.md
  web-researcher/SKILL.md
```
Each `SKILL.md` is reusable, domain-specific *workflow guidance* (which tool to prefer, when to escalate to another tool, what not to fabricate) that a sub-agent loads into its prompt at runtime (`_load_skill()` in `deep_agent_graph.py`), rather than being hard-coded into the Python prompt string. This mirrors — and is explicitly inspired by — the exact `SKILL.md` convention used by this session's own `skill` tool. Lesson for any multi-persona agent: **separate "which tool/domain to use and how" (markdown, editable without touching code) from the graph-wiring Python**, so domain guidance can be tuned without redeploying.

- Flagged weakness: guidance is prompt text only — nothing in code enforces it, so a sub-agent can still ignore its skill file's rules (e.g., call the wrong tool or fail to cross-check sources).

---

## 6. Testing: README-driven test generation (the most unusual/valuable pattern here)

Both `Readme.md` and `Agentic_Readme.md` contain a human-readable **"Test Questions"** section (`- "question" — \`expected_file\``, or grouped under `**\`tool_name\`**` headings). The test suite *parses the README itself* and turns each bullet into a `pytest.mark.parametrize` case:

```python
# tests/test_readme_questions.py:19-24
QUESTION_LINE_PATTERN = re.compile(r'^- "(?P<question>[^"]+)" — `(?P<file_name>[^`]+)`', re.MULTILINE)

def _load_readme_questions() -> list[tuple[str, str]]:
    text = README_PATH.read_text(encoding="utf-8")
    return QUESTION_LINE_PATTERN.findall(text)
```
- Each test invokes the **real** agent/RAG pipeline (no mocks) and asserts the expected source file was cited and the answer isn't a non-answer.
- The agentic variant also runs an **LLM-as-judge** check against a hard-coded `REFERENCE_ANSWERS` dict, and a guard test fails if any README question is missing its reference answer.
- A guard test (`assert len(questions) > 0` style) catches silent parser breakage (e.g., a Markdown formatting change that causes zero cases to be collected) — essential whenever tests are generated from a non-code source of truth.
- **This means the human-facing documentation and the test suite can never drift apart** — add a bullet to the README's test-question list, and it's automatically a new test case, no test file edits needed.
- Flagged weakness: brittle to exact Markdown formatting (heading text, bullet punctuation, section delimiters); mitigated only by the zero-case guard, not eliminated.

Separately, [test_memory_pii_redaction.py](../../reference/rag_krish/tests/test_memory_pii_redaction.py) unit-tests the pure `_redact_pii()` helper directly (no API calls) — a good reminder that **pure helper functions buried inside an LLM-calling module should still get fast, deterministic, non-API unit tests**, same lesson as agentic-rag's isolated chain tests.

`pytest.ini` disables the auto-loaded LangSmith pytest plugin (`-p no:langsmith`) — worth remembering if LangChain/LangSmith test runs hang or slow down unexpectedly in your own test config.

---

## 7. Observability & infra patterns

- **Prometheus via LangChain callback handler** ([observability.py](../../reference/rag_krish/agent_core/observability.py)): a `MetricsLoggingHandler` hooks `on_tool_start/on_tool_end`/LLM callbacks to record durations/errors — instrumentation added once at the callback layer instead of scattered through every node/tool. Flagged weakness: a couple of declared counters (`QUERIES_TOTAL`, `RESPONSE_LATENCY`) are never actually updated — a reminder to verify metrics are wired end-to-end, not just declared.
- **SQLite checkpointing** ([checkpointing.py](../../reference/rag_krish/agent_core/checkpointing.py)): `build_sqlite_checkpointer()` gives durable, file-backed conversation history for a single-process Streamlit app — a lighter-weight alternative to a full Postgres-backed checkpointer when you don't need multi-process sharing.
- **Moderation as a pre-flight helper, not a graph node**: `moderate_input()` wraps OpenAI's moderation endpoint and **fails open** (`(False, [])`) on any exception — a deliberate availability-over-safety trade-off worth being explicit about if reused.
- **Docker/monitoring separation**: only the flagship Streamlit agent is containerized (root `Dockerfile`/`docker-compose.yml`); Prometheus (`monitoring/`) and Neo4j (`neo4j/`) run as **separate, optional** compose stacks, scraping/connecting to the host app rather than being bundled — keeps the "always-on" footprint minimal (relevant given your stated preference to run MLflow only on-demand, not as a background service — this repo applies the same philosophy to its monitoring stack).
- `FAISS.load_local(..., allow_dangerous_deserialization=True)` appears in multiple places — a reminder that FAISS pickle loading should only ever point at indexes your own pipeline built.

---

## 8. Cross-cutting weaknesses worth remembering (so as not to repeat them)

1. **Retry/loop counters in checkpointed state need explicit per-turn reset** — otherwise they leak across conversation turns (flagship agent).
2. **Hard iteration caps silently produce a best-effort answer** rather than surfacing "I couldn't verify this" — true in the flagship agent, the deep agent, and the network multi-agent handoff.
3. **Magic-string protocols** (`"FINAL ANSWER"` substring, `"NONE" in extraction.upper()`) are fragile completion/sentinel signals — prefer structured output (`Literal`/Pydantic) for *any* machine-checked decision, as the repo itself does everywhere else.
4. **Change detection via mtime+size (not content hash) can miss edits**, and reusing private library internals (`vector_store.docstore._dict`) for hybrid search couples you to implementation details that can break on upgrade.
5. **Fail-open safety checks** (moderation) and **unvalidated LLM rewrites** (query expansion) are reasonable trade-offs for a demo but should be called out explicitly if carried into production.
6. **Importing an app module can have side effects** (observability app starts a metrics server at import time) — keep side effects inside `if __name__ == "__main__":` or explicit `init()` calls so modules stay safely importable (e.g., by tests).

---

## 9. Ideas directly applicable to `routing/` and `smarthome-csr/`

1. **Adopt the manifest-based incremental indexing pattern** for any vector index in `routing/` that's rebuilt from files — avoids re-embedding unchanged content and detects config drift (splitter/embedding-model changes) automatically.
2. **README-driven test questions**: if `routing/` or `smarthome-csr/` has user-facing docs listing example queries/scenarios, parse them into parametrized tests the same way — keeps docs and tests from drifting, and turns "add an example to the README" into "add a test case" for free.
3. **Orchestrator-worker via `Send()`** is the right tool whenever a routing task needs to fan out to a *variable* number of sub-queries/sub-agents determined at runtime (e.g., splitting a multi-intent customer message into per-intent workers).
4. **SKILL.md-style domain guidance files** for any sub-agent/persona in `smarthome-csr/`, kept separate from the Python graph wiring.
5. **Three-loop self-correction** (corrective retrieval + hallucination check + completeness/reflection check, each capped at one retry, with explicit per-turn counter resets) as the gold-standard reliability pattern to adopt for any customer-facing answer generation.
6. **Centralized, validated config with allow-lists** (`rag/config.py` style) for any pipeline with multiple pluggable strategies (splitters, retrieval modes, routing strategies) — fail fast on invalid config rather than silently falling back.
7. **Separate "always-on" containerized app from "optional/on-demand" monitoring and auxiliary-service stacks** — matches the user's stated preference for on-demand rather than always-running observability infrastructure (e.g., MLflow).
