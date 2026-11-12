# LangGraph Routing Accuracy Lab

A LangGraph application for testing, visualizing, and measuring **routing
accuracy** - not answer quality - across six knowledge-base topics,
subtopics, chapters, and specialist agents. See
[`instructions/Langgraph_routing/`](../instructions/Langgraph_routing) for
the full design rationale; this README covers what's actually built and
how to run it.

## Status: Level 3 complete ✅

Per the staged implementation plan
([`7_to_8_routing_configuration.md`](../instructions/Langgraph_routing/7_to_8_routing_configuration.md),
section 9), levels are built and verified one at a time.

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
- Full regression (Levels 1+2+3 together, 84 tests) re-verified after
  wiring `chapter_selector` into the graph.

Levels 4-10 (RAG retrieval, ambiguous questions, multi-chapter evidence,
multi-topic parallel routing, tool selection, multi-hop reasoning, error
recovery) are **scaffolded but not yet implemented** - see the
`NotImplementedError` stubs in `app/rag/` (except the chapter-metadata
parsing in `ingestion.py`, now implemented), `app/tools/`, and
`app/routers/tool_router.py`, each pointing at the level that builds it.

## Architecture (current)

```
START -> complexity_router -> topic_router -> subtopic_router ->
chapter_selector -> {one agent per selected topic, via Send fan-out}
-> synthesis_agent -> END
```

- **`complexity_router`**: classifies simple/intermediate/complex (recorded,
  not yet branched on - no scenario needs the branch until later levels).
- **`topic_router`**: classifies into one or more of
  `appliances | azure_cloud | data_engineering | python | finance | customer_support`.
- **`subtopic_router`**: narrows each selected topic down to one of its own
  subtopics (e.g. `appliances` -> `washing_machines`), via a dynamically
  constrained structured-output call per topic.
- **`chapter_selector`**: narrows each (topic, subtopic) pair down to a
  specific `chapter_id`, using real chapter titles *and* a short content
  preview parsed from `knowledge_base/` by `app/rag/ingestion.py` - titles
  alone were not enough signal (see the Level 3 finding above). Neither
  the subtopic nor the chapter choice is yet consumed by the topic agents
  themselves - Level 4's RAG retrieval is where that choice starts
  narrowing what evidence an agent actually sees.
- **Topic agents**: one per topic, answer directly from the LLM's own
  knowledge plus a topic-scoped system prompt (no retrieval yet - that's
  Level 4).
- **`synthesis_agent`**: pass-through for the single-topic case; will do
  real multi-topic merging once Level 7 exists to test it.

Run `python -m app.main "<question>"` to see this end to end, or open the
Streamlit dashboard for a rendered graph diagram.

## Project layout

```
routing/
├── app/                   # LangGraph application code
│   ├── routers/           # complexity, topic, subtopic, chapter_selector (done); tool_router (stub)
│   ├── agents/             # one agent per topic + synthesis_agent
│   ├── rag/                # ingestion.py (chapter metadata - done); chunking/embeddings/retrieval/reranking (Level 4 stubs)
│   ├── tools/              # document_search/calculator/sql_query/metadata_lookup (Level 8 stubs)
│   ├── evaluation/          # routing_metrics (done); retrieval_metrics, answer_metrics (stubs)
│   └── observability/      # mlflow_tracing, graph_visualizer, execution_logger
├── knowledge_base/         # 57 Markdown chapters + CSV/JSON/TXT, across 6 topics / 19 subtopics
├── datasets/                # routing_ground_truth.jsonl (L1: 24, L2: 19, L3: 38 questions)
├── tests/                   # test_basic_routing.py (L1), test_subtopic_routing.py (L2), test_chapter_routing.py (L3)
├── dashboard/                # Streamlit app (level selector covers L1-L3)
├── scripts/                  # generate_knowledge_base.py (done), build_index.py / run_evaluations.py
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

# Ask a single question through the graph
..\.venv\Scripts\python.exe -m app.main "What is a Python decorator?"

# Run the Level 1 + Level 2 + Level 3 pytest suites (takes 15-20 minutes - real LLM calls)
..\.venv\Scripts\python.exe -m pytest tests\ -v

# Run the same evaluation without pytest, with per-question pass/fail output
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 1
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 2
..\.venv\Scripts\python.exe scripts\run_evaluations.py --level 3

# Launch the dashboard (Evaluation tab has a Level 1/2/3 selector)
..\.venv\Scripts\python.exe -m streamlit run dashboard\streamlit_app.py
```

MLflow tracing is **on-demand only** - run `..\start_mlflow.ps1` from the
repo root before testing if you want traces, then `..\stop_mlflow.ps1`
when done. Nothing here starts MLflow automatically; the dashboard and
`app/main.py` silently skip tracing if the server isn't reachable.

## Next step

Implement Level 4 (RAG retrieval): implement `app/rag/chunking.py`,
`embeddings.py`, and `retrieval.py`, build a Chroma index over every
chapter via `scripts/build_index.py`, wire actual retrieved passages into
the topic agents (replacing their current "answer from the LLM's own
knowledge" behavior with grounded, cited answers), extend
`datasets/retrieval_ground_truth.jsonl` and `answer_ground_truth.jsonl`
with Level 4 cases, implement `app/evaluation/retrieval_metrics.py` and
`answer_metrics.py` (Retrieval Recall@K, answer correctness,
groundedness), and add `tests/test_rag_retrieval.py` before moving on to
Level 5 (ambiguous questions).
