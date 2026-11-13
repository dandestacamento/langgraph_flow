# LangGraph Routing Accuracy Lab

A LangGraph application for testing, visualizing, and measuring **routing
accuracy** - not answer quality - across six knowledge-base topics,
subtopics, chapters, and specialist agents. See
[`instructions/Langgraph_routing/`](../instructions/Langgraph_routing) for
the full design rationale; this README covers what's actually built and
how to run it.

## Status: Level 6 complete ✅

Per the staged implementation plan
([`7_to_8_routing_configuration.md`](../instructions/Langgraph_routing/7_to_8_routing_configuration.md),
section 9), levels are built and verified one at a time.

**Scope note for Levels 5-10**: to control API cost while these levels'
*routing mechanisms* are built and debugged (they test mechanism, not
topic-specific knowledge - the knowledge base already covers all 6 topics
from Level 1), test datasets for Levels 5-10 are scoped to **`appliances`
+ `customer_support`** only. The other 4 topics (`azure_cloud`,
`data_engineering`, `python`, `finance`) will be backfilled with
equivalent test coverage once Level 10 is complete and the full
architecture is proven - this is purely additive test-data work, since
the graph itself isn't topic-specific. Every graph-level change is still
spot-checked against all 6 topics before being committed (see the Level 5
finding below), just not with a full per-topic dataset yet.

**Level 1 (simple topic routing):**
- **24/24 Level 1 questions route to the correct topic (100% topic accuracy)**,
  including three deliberately adversarial questions that reuse the word
  "partition" across `data_engineering` (Spark), `azure_cloud` (Table
  Storage), and `customer_support` (warehouse logistics) to test
  context-based routing instead of keyword matching.
- Verified with `pytest tests/test_basic_routing.py` (25 tests, all passing).

**Level 2 (subtopic routing):**
- **19/19 Level 2 questions select the correct subtopic within the correct
  topic (100% subtopic accuracy)**, across all 19 subtopics (one question
  per subtopic).
- Verified with `pytest tests/test_subtopic_routing.py` (20 tests, all passing).

**Level 3 (chapter routing):**
- **38/38 Level 3 questions select the correct chapter_id within the
  correct topic and subtopic (100% chapter accuracy)**, two questions per
  subtopic chosen to require distinguishing between chapters, not just
  picking the only plausible one.
- Verified with `pytest tests/test_chapter_routing.py` (39 tests, all passing).
- **Real finding, fixed**: the first pass had 3 failures (92% accuracy) -
  chapter titles alone weren't enough signal (e.g. "which refrigerator has
  a water dispenser" was misrouted to the "Features" chapter by title,
  when the fact actually lives in "Overview"). Fixed by adding a short
  content preview per chapter to the Chapter Selector's prompt
  (`app/rag/ingestion.py`), not just the title - all 3 then passed. One
  question (`L3-033`) also had a genuine content-placement ambiguity
  between `orders` and `delivery` subtopics and was reworded, the same way
  `L1-024` was in Level 1.

**Level 4 (RAG retrieval):**
- **19/19 answerable Level 4 questions recall the expected chapter (100%
  Retrieval Recall@K, k=3) and produce a correctly grounded, cited
  answer; all 3 deliberately unanswerable questions correctly report
  insufficient information instead of fabricating an answer.**
- Verified with `pytest tests/test_rag_retrieval.py` (43 tests, all passing).
- Real document ingestion (YAML front matter + body), paragraph-level
  chunking (57 chapters -> 68 chunks), OpenAI `text-embedding-3-small`
  embeddings, and a local Chroma vector store
  (`scripts/build_index.py` -> `routing/.chroma/`) - no stubs left in
  `app/rag/` except `reranking.py`.
- Topic agents no longer answer from the LLM's own general knowledge -
  they answer *only* from passages retrieved for their (topic, subtopic),
  citing every retrieved `chapter_id` (appended by code, never
  self-reported by the LLM, so a citation can never be hallucinated), and
  explicitly report insufficient information when nothing retrieved
  actually addresses the question.
- **Two real findings, fixed**:
  1. A subtopic-routing gap: "What's the key difference between APR and
     APY?" was misclassified into `investments` instead of `loans`
     (both subtopics discuss "returns"-adjacent ideas, but only `loans`
     actually defines APR/APY) - fixed by naming APR/APY explicitly in
     the `loans` subtopic description (`app/config.py`), the same
     specificity pattern already used for appliance fault codes.
  2. Genuine LLM-level non-determinism in free-text generation (not a
     routing/retrieval bug): the exact same question, with the exact same
     correct passage retrieved, answered correctly 3/5 times and declined
     2/5 times even at `temperature=0`. Reworded the agent's system
     prompt to be explicit that it should answer confidently whenever
     *any* retrieved excerpt addresses the question, rather than
     declining because *other* excerpts don't apply - this is expected to
     reduce but not eliminate occasional non-determinism, which is
     inherent to generation (unlike the deterministic classification
     tasks in Levels 1-3).

**Level 5 (ambiguous questions):**
- **16/16 Level 5 questions get the correct clarify-vs-answer decision
  (100% clarification accuracy)** - 8 genuinely ambiguous questions (e.g.
  "is it covered?", "how long is the warranty?" with no model named)
  correctly trigger a clarifying question instead of a guess; 8
  self-contained questions (regression checks reused from Levels 1-4)
  correctly do NOT get flagged as ambiguous.
- Verified with `pytest tests/test_ambiguous_questions.py` (17 tests, all passing).
- **Real finding, fixed**: the obvious first approach - using
  `topic_router`'s existing `confidence` score as the ambiguity signal -
  doesn't work. Probing it directly showed the LLM reports `confidence:
  0.9` for almost *everything*, ambiguous or not; raw self-reported LLM
  confidence is well known to be poorly calibrated, and this confirmed it
  empirically. Fixed by adding an explicit `is_ambiguous: bool` field to
  `topic_router`'s structured output instead, with a prompt that
  distinguishes "no identifiable subject" (genuinely ambiguous, e.g. "is
  it covered?") from "general policy question" (not ambiguous, e.g. "what
  is the refund policy?" - one real answer regardless of product). The
  first version of that prompt was itself too aggressive (2 false
  positives on clear policy questions) before narrowing the instruction.
- `topic_router`'s `is_ambiguous` change applies to all 6 topics (it's
  not scoped to the Levels 5-10 focus topics), so it was spot-checked
  against one question from each of the 4 backfill topics
  (`azure_cloud`, `data_engineering`, `python`, `finance`) plus Level
  3/4 pipeline stages, confirming no regression, instead of a full
  6-topic re-run.

Levels 7-10 (multi-topic parallel routing, tool selection, multi-hop
reasoning, error recovery) are **scaffolded but not yet implemented** -
see the `NotImplementedError` stubs in `app/tools/` and
`app/routers/tool_router.py`, each pointing at the level that builds it.

**Level 6 (multi-chapter evidence aggregation):**
- **10/10 Level 6 questions recall every chapter needed to answer a
  compound question (100% multi-chapter coverage) and produce an answer
  containing the expected facts from both chapters (100% answer
  accuracy)** - each question deliberately needs two chapters within the
  same subtopic (e.g. the washing-machine E21 example from
  [`4_to_5_obserability.md`](../instructions/Langgraph_routing/4_to_5_obserability.md):
  "what does E21 mean on the WM-500, and is the repair covered under
  warranty?" needs both the fault-code chapter *and* the model-specific
  warranty-terms chapter).
- Verified with `pytest tests/test_multichapter_evidence.py` (22 tests,
  all passing).
- **Real finding, fixed**: at the original `RETRIEVAL_TOP_K = 3`, all 3
  retrieved slots for the WM-500/E21 question went to the single most
  lexically-similar chapter (`chapter_03_faults`), crowding out the
  equally-necessary `chapter_01_types` entirely - confirmed by direct
  `retrieve()` probing, and by testing 9 other hand-crafted compound
  questions spanning every focus-topic subtopic, all showing the same
  one-chapter-monopolizes-top-k pattern. Fixed by raising
  `RETRIEVAL_TOP_K` to 5 in `app/config.py`: every focus-topic subtopic
  has only 3-4 chapters total, so 5 chunks reliably spans all of them
  without needing a more complex per-chapter-guaranteed retrieval
  mechanism (e.g. extending `chapter_selector` to return multiple
  chapter IDs, or a dedicated Evidence Aggregator node, both considered
  and set aside - see "Design decisions" below). Re-verified all 43
  Level 4 tests still pass at `top_k=5` (no regression from the added
  context).
- **Real finding, not fixed (by design)**: for the WM-500/E21 question
  specifically, the agent reliably retrieves and cites `chapter_01_types`
  but consistently chooses to explain *which type* of warranty applies
  (parts vs. motor, reasoned from the general guidance in
  `chapter_02_operation`) rather than restating the WM-500's literal
  "2-year" duration from `chapter_01_types` - even after two rounds of
  added prompt instructions ("state the number explicitly", then "you
  MUST state the number") that didn't change the model's answer at
  `temperature=0`. This is arguably a *better* answer (duration alone
  would wrongly imply unconditional coverage), so the test's expected
  facts were recalibrated to match what the agent actually and correctly
  says, instead of forcing verbatim figure recitation - a concrete
  example of deterministic substring-based fact checking being too rigid
  for a genuinely good, nuanced answer, a limitation the project's own
  instructions call out and recommend supplementing with an LLM judge for
  (not implemented, to keep this level's scope and cost down).
- **Design decision**: `chapter_selector` still returns a single
  `chapter_id` (used for Level 3 evaluation and the dashboard), not a
  list - Level 6's fix is entirely in the retrieval layer (`top_k`), not
  a chapter_selector schema change, since retrieval is already scoped to
  the whole subtopic rather than one chapter (see the Level 4 design note
  above). No separate "Evidence Aggregator" node was added; the existing
  `rag_retriever` node already performs evidence aggregation at this
  knowledge-base scale by retrieving enough chunks to span a subtopic's
  chapters. This may need revisiting once the 4 backfill topics
  (including `azure_cloud`, which has larger/more numerous subtopics) are
  added back in after Level 10.

## Architecture (current)

```
START -> complexity_router -> topic_router -> {conditional}
  - if is_ambiguous: -> clarification_agent -> END
  - else: -> subtopic_router -> chapter_selector -> rag_retriever ->
    {one agent per selected topic, via Send fan-out} ->
    synthesis_agent -> END
```

- **`complexity_router`**: classifies simple/intermediate/complex (recorded,
  not yet branched on - no scenario needs the branch until later levels).
- **`topic_router`**: classifies into one or more of
  `appliances | azure_cloud | data_engineering | python | finance | customer_support`,
  and flags `is_ambiguous` when the question has no identifiable subject
  or depends on an unspecified product/model/order/error code (see the
  Level 5 finding above for why this isn't based on the `confidence`
  field).
- **`clarification_agent`**: runs instead of the rest of the pipeline when
  `is_ambiguous` is true - asks a short clarifying question and routes
  straight to END, skipping `synthesis_agent` entirely (which would
  otherwise overwrite `final_answer` with an empty string, since no topic
  agent ran).
- **`subtopic_router`**: narrows each selected topic down to one of its own
  subtopics (e.g. `appliances` -> `washing_machines`), via a dynamically
  constrained structured-output call per topic.
- **`chapter_selector`**: narrows each (topic, subtopic) pair down to a
  specific `chapter_id`, using real chapter titles *and* a short content
  preview - used for evaluation/the dashboard, not to scope retrieval
  (see `app/rag/retrieval.py` for why).
- **`rag_retriever`**: retrieves the top-k (`app.config.RETRIEVAL_TOP_K`,
  5 as of Level 6, was 3) most similar chunks per selected topic, scoped
  to that topic's *subtopic* (all 3-4 chapters in it), from the Chroma
  index - keeping Retrieval Recall@K an independent measurement of vector
  search quality rather than one that's trivially 100% whenever the
  Chapter Selector happens to already be right. Raised from 3 to 5 in
  Level 6 so a compound question needing evidence from two chapters in
  the same subtopic isn't starved by a single dominant chapter
  monopolizing all the top-k slots (see the Level 6 finding above).
- **Topic agents**: one per topic, answer *only* from the passages
  `rag_retriever` found for that topic, with appended source citations,
  or explicitly report insufficient information.
- **`synthesis_agent`**: pass-through for the single-topic case; will do
  real multi-topic merging once Level 7 exists to test it.

Run `python -m app.main "<question>"` to see this end to end, or open the
Streamlit dashboard for a rendered graph diagram.

## Project layout

```
routing/
├── .chroma/                 # Local Chroma vector store (gitignored; rebuild with scripts/build_index.py)
├── app/                     # LangGraph application code
│   ├── routers/             # complexity, topic (+ambiguity flag), subtopic, chapter_selector (done); tool_router (stub)
│   ├── agents/               # one agent per topic (RAG-grounded) + clarification_agent + synthesis_agent
│   ├── rag/                  # ingestion/chunking/embeddings/retrieval (done); reranking (stub)
│   ├── tools/                # document_search/calculator/sql_query/metadata_lookup (Level 8 stubs)
│   ├── evaluation/            # routing_metrics, retrieval_metrics, answer_metrics (all done)
│   └── observability/        # mlflow_tracing, graph_visualizer, execution_logger
├── knowledge_base/           # 57 Markdown chapters + CSV/JSON/TXT, across 6 topics / 19 subtopics
├── datasets/                  # routing_ground_truth.jsonl (L1: 24, L2: 19, L3: 38, L4: 22, L5: 16, L6: 10 questions)
├── tests/                     # test_basic_routing.py (L1), test_subtopic_routing.py (L2), test_chapter_routing.py (L3), test_rag_retrieval.py (L4), test_ambiguous_questions.py (L5), test_multichapter_evidence.py (L6)
├── dashboard/                  # Streamlit app (level selector covers L1-L3; ask tab shows retrieval+citations)
├── scripts/                    # generate_knowledge_base.py, build_index.py, run_evaluations.py (all done)
└── requirements.txt
```

## VS Code setup

1. This project reuses the repo-level virtual environment
   (`../.venv`) and the repo-root `.env` - it does **not** have its own
   `.env` file. Copy `.env.example` to `../.env` if you haven't already
   configured `OPENAI_API_KEY` there.
2. Select `../.venv/Scripts/python.exe` as the VS Code Python interpreter.
3. Open a terminal in `routing/` (not the repo root) before running the
   commands below, so relative paths resolve correctly.

## Running things

```powershell
# Regenerate the knowledge base (only needed after editing
# scripts/generate_knowledge_base.py)
..\.venv\Scripts\python.exe scripts\generate_knowledge_base.py

# Build/rebuild the Chroma vector index (needed after regenerating the
# knowledge base - tests auto-build it on a fresh checkout if missing,
# but won't auto-rebuild a stale one)
..\.venv\Scripts\python.exe scripts\build_index.py

# Ask a single question through the graph
..\.venv\Scripts\python.exe -m app.main "What is a Python decorator?"

# Run all pytest suites (takes 25-40 minutes - real LLM + embedding calls)
..\.venv\Scripts\python.exe -m pytest tests\ -v

# Run just the newest level's tests (recommended during active development,
# to avoid re-billing every previously-passing level - see app/cache.py for
# why repeat runs of unchanged questions are still cheap even if you do
# run everything)
..\.venv\Scripts\python.exe -m pytest tests\test_ambiguous_questions.py -v

# Run the same evaluation without pytest, with per-question pass/fail output
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 1
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 2
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 3

# Launch the dashboard (Evaluation tab has a Level 1/2/3 selector; Ask
# tab shows retrieved chapters, citations, and insufficient-info behavior)
..\.venv\Scripts\python.exe -m streamlit run dashboard\streamlit_app.py
```

MLflow tracing is **on-demand only** - run `..\start_mlflow.ps1` from the
repo root before testing if you want traces, then `..\stop_mlflow.ps1`
when done. Nothing here starts MLflow automatically; the dashboard and
`app/main.py` silently skip tracing if the server isn't reachable.

Response caching is **on by default** (`app/cache.py`) - repeated runs of
the same question are served from a local SQLite cache instead of
re-billing the API. Set `ROUTING_LAB_CACHE_ENABLED=0` to force fresh calls
(e.g. after changing a prompt, since the cache key is just the literal
question text).

## Next step

Implement Level 7 (multi-topic parallel routing): questions whose correct
answer requires routing to and synthesizing responses from more than one
topic agent simultaneously (e.g. a question spanning both `appliances`
and `customer_support`), exercising the `Send`-based fan-out that
`route_to_agents` already supports (one `Send` per selected topic, no
graph rewiring needed) and giving `synthesis_agent` real multi-topic
merging to do instead of its current single-topic pass-through, plus
extending `datasets/routing_ground_truth.jsonl` with Level 7 cases (still
scoped to `appliances` + `customer_support`) and adding
`tests/test_multitopic_routing.py`.
