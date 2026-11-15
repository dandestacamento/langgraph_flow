# Learnings from `routing_lab/` (self-review)

Source: [routing_lab/](../../routing_lab/) — this is **our own project** (the "Routing Accuracy Lab"), not a third-party reference. This document is a technical self-review of its own architecture, written the same way as the other `instructions/learnings/*.md` files, so it can be read alongside them: what the project already does well, what it borrowed (consciously or not) from the patterns seen in [agentic-rag](./agentic-rag-learnings.md), [ReAct agent](./react-agent-learnings.md), [reflection agent](./reflection-agent-learnings.md), and [rag_krish](./rag-krish-learnings.md), and what gaps remain.

Read via three parallel deep-dives covering [app/graph.py + agents/ + architectures/ + routers/](../../routing_lab/app/), [app/rag/ + app/tools/ + knowledge_base/ + datasets/](../../routing_lab/app/rag/), and [app/evaluation/ + app/observability/ + tests/ + scripts/ + dashboard/](../../routing_lab/app/evaluation/).

---

## 1. Project purpose

A LangGraph "Routing Accuracy Lab": route a question across six knowledge domains (appliances, azure_cloud, customer_support, data_engineering, finance, python) through topic → subtopic → chapter routing, then retrieve and answer — with the project's explicit focus on **measuring routing accuracy itself** (not just final-answer quality), across 10 graduated difficulty "levels" (basic topic routing → subtopic → chapter → RAG retrieval → ambiguity/clarification → multi-chapter evidence → multi-topic fan-out → tool selection → multi-hop reasoning → error recovery). Two simplified comparison architectures (A: flat LLM router, B: hierarchical router) let the full production graph (informally "C") be benchmarked against simpler baselines.

---

## 2. Graph architecture ([app/graph.py](../../routing_lab/app/graph.py), [app/state.py](../../routing_lab/app/state.py))

```
START → complexity_router
  → multihop_router → multihop_agent → END                 (genuine dependent hops)
  → topic_router
      → clarification_agent → END                            (ambiguous question)
      → subtopic_router → chapter_selector → rag_retriever → tool_router
          → Send-fan-out to 1..N topic agents → synthesis_agent → END
```

- **`Send`-based fan-out for multi-topic questions**: `route_to_agents()` returns one `Send(_TOPIC_AGENT_NODES[topic], state)` per selected topic — same dynamic-fan-out technique flagged as valuable in `rag_krish`'s orchestrator-worker graph, applied here to multi-domain questions instead of LLM-planned sub-questions.
- **Reducer-backed parallel-safe state**: `merge_dicts()` (`state.py`) lets each parallel topic-agent branch write its own key into `agent_responses` without clobbering siblings — the dict-merge reducer equivalent of `rag_krish`'s `Annotated[List[dict], add]` list-append reducer for orchestrator-worker findings.
- **Per-topic question isolation**: `get_topic_question()` restates the sub-portion of a compound question relevant to each topic before that topic's agent runs, so one topic's agent doesn't see irrelevant parts of a multi-domain question. This is a sharper, more targeted version of the "fresh message history per sub-task" idea seen in `rag_krish`'s deep-agent pattern.
- **Clarification as its own terminal branch**: ambiguous questions route straight to `clarification_agent → END`, bypassing agents and synthesis entirely — a cleaner, simpler version of the "ask a clarifying question" need that `rag_krish`'s skill files gesture at only in prose guidance.
- **Multihop reuses the whole graph recursively**: `multihop_agent.py` locally imports `build_graph()` (to dodge a circular import) and **invokes the full graph twice** — once per hop — substituting the first hop's extracted answer into the second hop's question template, then synthesizing. `is_hop_subquestion=True` prevents runaway recursion (hop sub-invocations skip the multihop check themselves). This is a more elegant reuse-the-same-pipeline approach than `rag_krish`'s supervisor/network multi-agent handoff, which required ad hoc `"FINAL ANSWER"` string sentinels.
- **Architectures A and B are separate, smaller comparison graphs**, not alternate branches of the main graph — they share only the single-topic classifier (`architectures/_shared.py`) with the full pipeline, isolating "routing topology" as the sole comparison variable. This is a deliberate, well-controlled experiment design: good practice when comparing architectures, worth remembering for any future A/B architecture comparison.

### Weaknesses flagged
- **Complexity classifier always runs** even though its output doesn't currently select a distinct path in the main graph (except skipping the multihop check for hop sub-questions) — an LLM call on every request whose result is mostly unused today. Either wire it into an actual branch decision or remove it to save latency/cost.
- **Synthesis prompt doesn't fully handle tool citations**: the multi-topic synthesis prompt documents/preserves chapter-ID citations but doesn't explicitly handle `tool:<name>` citations the way the multihop synthesis prompt does — an inconsistency to fix if tool-backed multi-topic answers need citation preservation too.
- **Dynamically-constrained structured output falls back silently**: `chapter_selector.py`/`subtopic_router.py` build Pydantic models with `json_schema_extra={"enum": [...]}`, and a membership-check fallback defaults to the *first* option if the model returns something invalid — this can mask a malformed LLM response as if it were a deliberate low-confidence choice. Worth logging/flagging when the fallback actually triggers.
- **Architecture B's "hierarchical" chapter selection doesn't scope retrieval to that chapter** (by design, per code comments) — naming it "hierarchical router" could be mistaken for chapter-filtered retrieval; the comparison still uses subtopic-scoped retrieval like the main graph.

---

## 3. Domain agents ([app/agents/](../../routing_lab/app/agents/))

The six domain agent files (`appliance_agent.py`, `azure_agent.py`, `customer_support_agent.py`, `data_engineering_agent.py`, `finance_agent.py`, `python_agent.py`) are **one-line wrappers**: each `run(state)` just calls `run_topic_agent("<topic>", state)` in `_shared.py`. All substantive logic — prompt construction, citation handling, tool-result incorporation, retry-on-failure — lives in one shared module.

- **Template-based multiplicity**: six domains, one implementation — the same "one shared engine, N thin per-domain façades" discipline recommended in the rag_krish learnings doc (§1, "one pattern one module"), but taken a level further: here even the façades are nearly identical, differing only in the topic string passed through.
- **Citations appended in code, not trusted to the model**: `_generate_answer()` builds citations deterministically from retrieved-passage metadata rather than asking the LLM to cite correctly — directly avoids the citation-fabrication risk flagged in multiple other learnings docs (agentic-rag's ungrounded generation, rag_krish's hallucination grader).
- **One bounded retry on tool/retrieval failure** (`_retry_tool()`, Level 10 "error recovery"): if a tool call fails, the agent attempts a structured-output correction of the tool input, broadens retrieval to the whole topic (not just the subtopic), and regenerates the answer once. This is a single-attempt version of the capped self-correction loops celebrated in both the agentic-rag and rag_krish learnings docs — same retry-cap discipline, applied to tool/retrieval failure specifically rather than hallucination/relevance grading.

This pattern — shared node logic + thin per-domain name-only wrappers + deterministic citation assembly + one bounded recovery retry — is arguably the project's strongest, most reusable architectural idea.

---

## 4. Routers ([app/routers/](../../routing_lab/app/routers/))

Every router uses `temperature=0` structured-output LLM calls (Pydantic models, `Literal` types) — consistent with the "every decision point should be typed" discipline seen across all the other reference projects:

| Router | Decides | Notable technique |
|---|---|---|
| `topic_router.py` | 1+ of 6 topics, ambiguity flag, per-topic question restatement | returns a **list of fixed-shape items** instead of `dict[str,str]` because free-form object keys aren't reliably schema-constrainable — a concrete, documented workaround worth remembering when structured output needs a variable-keyed mapping |
| `subtopic_router.py` | one subtopic per selected topic | **dynamically builds** a Pydantic model constrained to that topic's configured subtopic list — structured output schemas generated at runtime from config, not hand-written per domain |
| `chapter_selector.py` | one chapter within the chosen subtopic | same dynamic-constrained-schema technique, over chapter IDs; recorded for evaluation even though retrieval doesn't filter down to just that chapter |
| `complexity_router.py` | simple / intermediate / complex | classification exists but (per §2) doesn't yet drive branching in the main graph |
| `multihop_router.py` | is this a genuine 2-hop dependent question? plus a hop plan | prompt explicitly distinguishes *sequential dependency* (hop 2's subject is unknown until hop 1 resolves) from merely *compound* questions answerable independently — a precise, non-obvious distinction worth preserving in any future multi-hop classifier |
| `tool_router.py` | calculator / sql_query / metadata_lookup / none, per topic | executes the chosen tool immediately inside the router step and stores the result; converts exceptions to error strings rather than raising |

**Dynamically-constrained structured output** (building a `Literal`/enum Pydantic schema from live config rather than a static class) is the single most novel technique here relative to all four other reference projects reviewed — none of them needed runtime-variable valid-answer sets for their routers.

---

## 5. RAG pipeline ([app/rag/](../../routing_lab/app/rag/)) — contrast with rag_krish

This is a **much simpler** RAG pipeline than `rag_krish`'s, and comparing them directly is instructive:

| | `routing_lab/app/rag/` | `rag_krish/rag/` |
|---|---|---|
| Formats ingested | Markdown chapters only (YAML front-matter + H1 + prose); CSV/JSON/TXT exist as supporting fixtures but aren't passed through general RAG ingestion | txt, pdf, docx, json, jsonl, sqlite, csv, xlsx — all through RAG |
| Chunking | one strategy: split on blank-line paragraph boundaries, no size/overlap target | four pluggable strategies (recursive/character/token/semantic) |
| Index rebuild | **full rebuild every run** (`build_index.py` deletes all existing IDs then re-adds), despite having deterministic chunk IDs (`document_id:chapter_id:chunk_index`) that *could* support incremental diffing | manifest-based incremental indexing (mtime+size+content-hash diffing, rebuild only on ingest-signature change) |
| Retrieval modes | similarity only (`similarity_search_with_score`, Chroma L2 distance), filtered by topic/optionally subtopic | similarity / mmr / hybrid (BM25 + vector via `EnsembleRetriever`), optional cross-encoder reranking |
| Reranking | `reranking.py` is an explicit `NotImplementedError` stub | implemented (`ContextualCompressionRetriever`/`CrossEncoderReranker`) |
| Store | one shared Chroma collection, topic/subtopic as metadata filters | per-topic FAISS indexes (in `rag_krish`'s agent tools) or one shared store, depending on app |

**This is the clearest actionable gap to borrow from `rag_krish`'s learnings**: `routing_lab/`'s own chunk-ID scheme (`document_id:chapter_id:chunk_index`) already has everything needed to do manifest-based incremental rebuild (§3 of the rag_krish learnings doc) instead of delete-and-rebuild-everything on every `build_index.py` run — this would matter once the knowledge base grows past today's 57 chapters. Hybrid retrieval and reranking are also implemented and battle-tested in `rag_krish` and could be ported if answer quality (not just routing accuracy) becomes a higher priority.

---

## 6. Tools ([app/tools/](../../routing_lab/app/tools/))

None of the four tools use LangChain's `@tool` decorator — they're plain Python functions invoked directly from `tool_router.py` after structured-output selection, rather than being bound to an LLM via `bind_tools`/`ToolNode` (contrast with the ReAct-agent and rag_krish flagship-agent patterns, which let the model itself decide to call a tool). This is a **deliberate control-flow difference**: here, tool *selection* is itself a graded routing decision (evaluated for accuracy as "Level 8"), not something delegated to the model's own tool-calling judgment.

- `calculator.py`: parses expressions with Python's `ast` module and evaluates only numeric literals + `+ - * /` + unary sign — explicitly avoids `eval`/`exec`. A clean, minimal-attack-surface pattern worth reusing anywhere a "calculator tool" is needed.
- `sql_query.py`: scopes a SQL query to one CSV loaded into an **in-memory SQLite table** per topic/subtopic — but then calls `connection.execute(query)` with the LLM-supplied query **directly, with no `SELECT`-only validation**. Since the attack surface is a single in-memory, process-local, non-persistent table built from the project's own CSV, the blast radius is small, but this is the one place in the reviewed codebase where "SQL built from LLM output executed directly" appears — worth adding an explicit read-only/allowlist check (e.g., reject non-`SELECT` statements) even though the current risk is low, both as defense-in-depth and because `rag_krish`'s loaders flagged the identical unquoted-SQL-interpolation pattern as a weakness.
- `document_search.py` is an **intentional stub** (`NotImplementedError`) — the docstring explains automatic RAG retrieval is considered sufficient for this project's test cases, so an explicit "search documents" tool was never built. A clear, documented scope decision rather than an oversight.

---

## 7. Evaluation ([app/evaluation/](../../routing_lab/app/evaluation/)) — the project's standout strength

Three metric modules are all **deterministic** (no LLM-as-judge anywhere), which is a notable contrast to `rag_krish`'s agentic test suite (which used an LLM judge against `REFERENCE_ANSWERS`):

- `routing_metrics.py`: exact-set topic-match precision/recall/F1, plus dedicated scorers for subtopic, chapter, clarify-vs-answer, tool choice (including "correctly chose no tool"), multi-hop detection, and recovery decisions.
- `retrieval_metrics.py`: Recall@K by exact chapter-ID membership; a separate `MultiChapterRetrievalResult` requires *all* expected chapters for full credit plus a partial-coverage fraction.
- `answer_metrics.py`: `answer_correctness()` = fraction of expected fact-strings found as case-insensitive substrings; `groundedness()` = lexical-overlap proxy, not entailment — both modules' docstrings are explicit that these are **lightweight proxies, not semantic judges**.

This is a deliberate, well-documented trade-off: cheap, fast, deterministic, reproducible metrics over slower/costlier/noisier LLM-judged ones, appropriate for a project whose stated focus is *routing* accuracy rather than answer quality. Worth remembering as the opposite end of the spectrum from rag_krish's LLM-as-judge approach — **pick the evaluation style to match what's actually being measured**, don't default to LLM-judging everything.

### Weaknesses flagged
- **`run_evaluations.py`'s usage text claims "all levels"** but the implementation only scores Levels 1–3 (topic/subtopic/chapter) — a real scope/documentation mismatch to fix.
- **README has a stale/contradictory claim** ("All 10 levels complete" stated early, contradicted by a later note that Level 10 was only "scaffolded," itself apparently superseded by later sections describing Level 10 as implemented/tested) — worth reconciling so the README doesn't mislead readers about project status.
- **Dashboard evaluation tab only covers Levels 1–3** (explicitly marked "early version" in its own docstring) — same gap as `run_evaluations.py`; both should be extended to cover Levels 4–10 using the same metric classes already used by `run_batch_tests.py`.
- **`compare_architectures.py`'s "LLM call count" is inferred from node names + positive duration** — a useful cost proxy, but not authoritative; don't over-trust it for real token/cost accounting (use the batch runner's actual token/cost callback data instead, which is already collected elsewhere in `run_batch_tests.py`).

---

## 8. Testing ([tests/](../../routing_lab/tests/)) — dataset-driven, like rag_krish's README-driven tests, but cleaner

`routing_lab/tests/` is **dataset-driven and parametrized from `datasets/routing_ground_truth.jsonl`** (loaded via `conftest.py`'s `load_ground_truth(level=None)`), with one test file per difficulty level (Level 1 basic routing → Level 10 error recovery). This is structurally the same idea as `rag_krish`'s README-driven test questions (§6 of that learnings doc: parse a human-curated source of truth into parametrized pytest cases) — but **more robust**, because JSONL with explicit typed fields (`id`, `level`, `question`, expected topic/subtopic/chapter, notes) is far less brittle to reparse than regex-matching Markdown bullet formatting. **This is a concrete improvement worth recognizing and keeping**: if `rag_krish`'s README-parsing pattern is ever adopted elsewhere, prefer a structured file (JSONL/JSON) over parsing prose Markdown, exactly as this project already does.

- Session-scoped fixtures (`compiled_graph` built once per session; an autouse fixture builds the Chroma index only if missing) keep the suite fast without sacrificing realism — same "build the expensive thing once" discipline as `rag_krish`'s session-scoped `rag` fixture.
- `test_error_recovery.py` has both dataset-driven cases *and* hand-constructed direct tests that force rare failure modes (wrong-subtopic retrieval, malformed SQL input) — a good complement, since recovery/error paths are inherently hard to trigger reliably from end-to-end dataset cases alone. This mirrors the `test_memory_pii_redaction.py` lesson from rag_krish: **pure/deterministic failure-path logic deserves direct, non-end-to-end unit tests**, not just integration coverage.
- `test_architecture_comparison.py` deliberately uses a small, hand-picked subset (one case per topic) rather than the full ground truth — appropriate for a comparison test whose job is topology sanity-checking, not statistical power.

### Weakness flagged
- Parametrized per-case tests plus separate summary/aggregate tests both re-invoke the same cases — redundant graph invocations (mitigated, not eliminated, by the LLM response cache) that also mean recorded "latency" in these tests is cache-skewed and shouldn't be read as real production latency (the project's own `compare_architectures.py` README caveat already acknowledges this for its own runs).

---

## 9. Observability ([app/observability/](../../routing_lab/app/observability/))

- **MLflow is optional and on-demand**: `enable_mlflow_tracing_if_available()` probes the tracking server's host/port reachability with a short socket timeout before enabling `mlflow.langchain.autolog()`; scripts/dashboard silently skip tracing if the server isn't up. This matches the user's own stated preference (and the project's `start_mlflow.ps1`/`stop_mlflow.ps1` scripts) of running MLflow only while actively testing, never as an always-on background service — and is a cleaner implementation of the same "optional, separately-launched observability" philosophy flagged as a strength in rag_krish's Prometheus/Neo4j compose separation.
- **Execution logging is structured and queryable after the fact**: `execution_logger.py` provides `get_node_sequence()`, `get_log_for_node()`, `total_duration_ms()` over a list of `{node, action, output, duration_ms}` entries that graph nodes append to during execution — this is the same "free architecture documentation" idea as `draw_mermaid_png`/`print_ascii()` in the course projects, but for *runtime* behavior instead of static graph topology.
- **Graph visualization has a graceful text fallback**: `graph_visualizer.py` attempts PNG rendering via Mermaid and returns `(None, source)` on failure instead of raising — more defensive than the course projects' unconditional `draw_mermaid_png()` calls, which would simply crash on a missing dependency.

---

## 10. Cross-project comparison summary

| Concern | `routing_lab/` (this project) | Best-in-class elsewhere |
|---|---|---|
| Multi-domain fan-out | `Send`-based, reducer-merged state | rag_krish orchestrator-worker (`Send` + `add` reducer) — same technique |
| Tool selection | graded routing decision, not model-driven | ReAct agent / rag_krish flagship agent: model decides via `bind_tools` |
| Self-correction | one bounded retry on tool/retrieval failure | rag_krish flagship agent: three distinct capped loops (relevance, hallucination, completeness) |
| Index rebuild | full rebuild every run | rag_krish: manifest-based incremental rebuild — **adopt this** |
| Retrieval modes | similarity only | rag_krish: similarity/mmr/hybrid + reranking — **candidate to adopt if answer quality becomes a priority** |
| Test-case source of truth | structured JSONL, parametrized | rag_krish: README prose, regex-parsed — `routing_lab/`'s approach is *more* robust, worth exporting back |
| Evaluation philosophy | deterministic substring/overlap metrics | rag_krish: LLM-as-judge — different tools for different goals (routing accuracy vs. answer quality) |
| Observability | on-demand MLflow autolog + structured execution log | rag_krish: Prometheus counters via callback handler — comparable "instrument once centrally" discipline |

---

## 11. Top actionable takeaways for this project

1. **Add manifest-based incremental indexing** to `scripts/build_index.py` (chunk IDs already exist; just need mtime/hash tracking + an ingest-signature check) — the single highest-value gap relative to `rag_krish`.
2. **Reconcile the README's contradictory Level 10 status claims**, and extend `run_evaluations.py` and the Streamlit dashboard's evaluation tab to cover Levels 4–10 using the metric classes `run_batch_tests.py` already exercises — closing the "all levels" documentation/implementation gap.
3. **Decide and wire up `complexity_router`'s purpose** (either make it drive an actual branch, or remove the always-on LLM call).
4. **Add an explicit read-only/`SELECT`-only guard** to `sql_query.py` before executing LLM-supplied SQL, even though current risk is low — cheap defense-in-depth, consistent with the identical weakness flagged in rag_krish's SQLite loader.
5. **Align the standard synthesis prompt's citation handling with the multihop synthesis prompt's** so tool-result citations survive multi-topic synthesis consistently.
6. Consider **hybrid retrieval + reranking** (porting rag_krish's `EnsembleRetriever`/cross-encoder pattern) if/when answer quality — not just routing accuracy — becomes a project priority.
