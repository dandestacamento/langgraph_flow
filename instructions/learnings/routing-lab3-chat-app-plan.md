# Turning `routing_lab3/` into a chat application - migration plan

This is the forward-looking plan for evolving `routing_lab3/` (a working copy created
specifically for this effort, since it's a major enough modification to warrant its own copy
rather than building it on top of `routing_lab2/`) from a single-shot routing-accuracy evaluation
harness into an actual multi-turn chat application, per the user's stated end goal (the app "will
eventually be a chat application - I'm just creating an app to test different functionalities").
Unlike `instructions/learnings/routing-lab2-learnings.md` (which recorded a *completed* P1/P2
implementation in `routing_lab2/`), this document is a plan for work **not yet started**, in a
separate copy of the project.

---

## 1. Where things stand today

- **`RoutingState`** (`app/state.py`) is a single-question, single-shot `TypedDict` - no
  `messages` key, no `thread_id`, no checkpointer. Every `graph.invoke(initial_state(question))`
  call is one independent question with zero memory of any prior turn.
- **`app/graph.py`'s `build_graph()`** is the 10-level routing/retrieval/tool/multi-hop/recovery
  pipeline this whole project is built around, calibrated against a 228-row ground truth
  (`datasets/routing_ground_truth.jsonl`) across Levels 1-10, with per-level pytest suites holding
  it to specific accuracy thresholds.
- **`dashboard/streamlit_app.py`** is a testing/evaluation UI (ask-a-question tab, level-by-level
  accuracy tab), not a conversational product - and shouldn't need to become one; see §4.
- **A working conversational pattern already exists in this repo**, in `smarthome-csr/`, and should
  be reused rather than reinvented (see §2).

**The key constraint this plan is built around**: `RoutingState`'s single-question pipeline is
heavily tested and calibrated (228 ground-truth rows, 10 pytest files, documented accuracy
numbers). Any change here risks the same kind of regression this project has spent ten levels
avoiding. So the guiding principle is: **wrap the existing pipeline with a new conversational
layer; don't rewrite the pipeline itself.**

---

## 2. Reuse the in-repo precedent: `smarthome-csr`'s conversation pattern

`smarthome-csr/graph/state.py`'s `CSRState` already solves most of this problem, in this same
repo, already working:

```python
# smarthome-csr/graph/state.py
conversation_history: Annotated[list[dict], operator.add]
```

- A custom per-turn history accumulator (simpler than LangGraph's stock `messages`/`add_messages`,
  tailored to the project's own needs) - appended to once per turn, never overwritten.
- Fields like `order_id` persist across turns "for free," via ordinary LangGraph partial-return
  merge semantics (a node only changes a field by including that key in its returned dict) - the
  same mechanism `RoutingState`'s per-topic dicts already rely on.
- `smarthome-csr/app.py` already wires up the other two pieces a chat app needs:

  ```python
  @st.cache_resource
  def get_graph():
      return build_graph(checkpointer=InMemorySaver())
  ```

  plus a `thread_id` (via `uuid`) generated once per browser session and passed on every
  `graph.invoke()`/`graph.stream()` call.

**Plan: adapt this exact pattern for `routing_lab3`**, rather than inventing a new one. This
de-risks the whole effort - it's not a new idea, it's copying something already proven to work in
this repo.

---

## 3. Proposed architecture: wrap, don't rewrite

```
                 ┌─────────────────────────────────────────────┐
                 │  NEW: chat/conversation layer                │
                 │  - thread_id + checkpointer (persistence)    │
                 │  - conversation_history (per-turn log)       │
                 │  - "condense" step: chat history + latest    │
                 │    user message -> one self-contained        │
                 │    question                                  │
                 └───────────────────┬───────────────────────────┘
                                     │ self-contained question
                                     ▼
                 ┌─────────────────────────────────────────────┐
                 │  UNCHANGED: app/graph.py build_graph()        │
                 │  (complexity_router -> ... -> synthesis_agent)│
                 │  - still single-question, still the exact     │
                 │    same 10-level pipeline, zero modifications │
                 └───────────────────┬───────────────────────────┘
                                     │ final_answer + rich state
                                     │ (selected_topics, retrieved_passages,
                                     │  tool_results, hop_results, execution_log)
                                     ▼
                 ┌─────────────────────────────────────────────┐
                 │  NEW: chat layer appends AI turn to           │
                 │  conversation_history, exposes rich state      │
                 │  for the frontend (generative UI later)        │
                 └─────────────────────────────────────────────┘
```

### 3.1 The "condense" step (new, and the main design risk)

The hard part of any conversational RAG/routing app is: a follow-up like *"is it covered under
warranty?"* or *"what about the washing machine instead?"* is not a self-contained question - it
only makes sense given prior turns. Since `topic_router`/`subtopic_router`/`chapter_selector`/
`rag_retriever` all expect a self-contained question (and are calibrated against ground-truth rows
that are all self-contained), the cleanest fix is a **new, small, structured-output LLM call** that
runs *before* the existing pipeline:

```python
# New: app/chat/condense.py (sketch)
class CondensedQuestion(BaseModel):
    self_contained_question: str = Field(
        description="The user's latest message, rewritten as a fully self-contained "
        "question that doesn't require the conversation history to understand."
    )

def condense_question(conversation_history: list[dict], latest_message: str) -> str:
    ...
```

This mirrors a pattern already in this codebase (`app/agents/multihop_agent.py`'s `_extract_value`
- a small, single-purpose structured-output call between pipeline stages), so it's not a new kind
of component, just a new instance of one.

**This condensing step needs its own accuracy metric and test cases** - same rigor as every other
router/classifier in this project (`topic_router`, `subtopic_router`, etc. all have dedicated
ground truth + pytest coverage). See §5.

### 3.2 Where the new code lives

- `app/chat/state.py` - new `ChatState` TypedDict: `thread_id`, `conversation_history` (reducer,
  copying `smarthome-csr`'s pattern), plus whatever subset of `RoutingState`'s rich per-turn output
  the frontend needs to keep around (citations, routing decisions) for generative UI later.
- `app/chat/condense.py` - the condensing LLM call (§3.1).
- `app/chat/graph.py` - a new `build_chat_graph(checkpointer=None)`, structurally: `condense ->
  [invoke existing build_graph() as a sub-call, exactly like multihop_agent.py already does] ->
  record_turn -> END`. Reuses `app.graph.build_graph()` unmodified, the same way
  `multihop_agent.execute_multihop()` already recursively invokes it for hop sub-questions -
  there's already a proven in-repo pattern for "call the existing single-question pipeline from a
  new outer node," not just a theoretical plan.
- `dashboard/streamlit_app.py` stays as-is for now (see §4) - a new, separate `scripts/chat_cli.py`
  or a new Streamlit tab is the cheapest way to exercise `build_chat_graph()` early (see §6 Phase 0).

---

## 4. The evaluation dashboard and the chat app are two different surfaces - keep them separate

`routing_lab3`'s existing Streamlit dashboard (ask tab + evaluation tab) tests the **stateless,
single-question pipeline** against the 228-row ground truth - that's still exactly the right tool
for that job (data tables, per-level accuracy, architecture comparison), and nothing about adding
a chat layer should change it. The chat app is a **new, additive surface** built on top of
`build_chat_graph()`, not a replacement for the evaluation dashboard. Don't let "making it a chat
app" turn into "ripping out the evaluation tooling" - they answer different questions (*is the
routing pipeline accurate?* vs. *does the conversation feel good?*) and should keep using whatever
tool is best suited to each (Streamlit/data-dashboard-style for the former, a real chat UI for the
latter).

---

## 5. New testing needs (same evidence-based discipline as everything else in this project)

1. **A new multi-turn ground-truth dataset** (e.g. `datasets/chat_ground_truth.jsonl`) - short
   conversations (2-3 turns) where a later turn is a genuine follow-up requiring context from an
   earlier one, modeled on the existing `routing_ground_truth.jsonl`'s per-level JSONL convention.
2. **A condensing-accuracy metric and test file** (e.g. `tests/test_chat_condensing.py`) - does
   `condense_question()` correctly resolve "is it covered under warranty?" to "is the WM-900's
   warranty..." given the prior turn established WM-900? This is exactly the kind of thing this
   project always builds a dedicated metric class for (see `app/evaluation/routing_metrics.py`'s
   seven existing result classes) - a `CondensingResult` dataclass, scored by whether the resolved
   question's extracted entity/topic matches an expected value, fits the same mold.
3. **Zero-regression requirement on the existing single-question suite**: since `build_graph()`
   itself is untouched, the existing 228-row/10-level pytest suite must keep passing unchanged
   throughout - this is the same bar every change in this project (including the P1/P2 work in
   `routing-lab2-learnings.md`) has been held to, and the wrap-don't-rewrite design in §3 is
   specifically chosen to make that an easy bar to clear.

---

## 6. Phased rollout

- **Phase 0 (cheap validation, do this first)**: build `app/chat/` (state, condense, graph) and
  exercise it from a minimal CLI script or a new Streamlit chat-style tab - *not* a new frontend
  framework yet. The goal is validating the conversational graph shape and the condensing step
  work correctly, before investing in any new frontend stack at all. Matches this project's
  consistent "prove it works before building more infrastructure around it" pattern (e.g. how P1's
  hybrid retrieval was benchmarked before being wired into anything user-facing).
- **Phase 1**: once Phase 0's condensing accuracy and conversation behavior are validated, stand up
  **Agent Chat UI** (open-source, official LangChain Next.js template) pointed at a LangGraph
  server/API serving `build_chat_graph()` - the fastest path to a real chat interface, since it's
  built specifically around LangGraph's streaming/state conventions.
- **Phase 2**: migrate to **CopilotKit** once ready to build real generative UI - rendering
  `retrieved_passages`/citations as rich cards, `selected_topics`/`selected_subtopics` as a routing
  breadcrumb, `tool_results` as structured widgets - which `routing_lab3`'s unusually rich per-turn
  state is well suited for (see the earlier conversation in this session for why).
- **Checkpointer**: start with `InMemorySaver` (matches `smarthome-csr`'s current choice, cheapest
  to build/test), graduate to a persistent backend (e.g. `SqliteSaver`, the same pattern
  `reference/rag_krish/agent_core/checkpointing.py` already demonstrates - see
  `instructions/learnings/rag-krish-learnings.md` §7) once the chat app needs to survive a process
  restart.

---

## 7. Open design decisions (flagging, not deciding unilaterally)

- **Does every follow-up need the condensing step, or only ones that look like follow-ups?**
  Running it on every turn is simpler and more robust (no "is this a follow-up?" classifier needed)
  but costs one extra LLM call per turn, every turn - consistent with how this project generally
  prefers a small always-on call over a brittle "should I even do this?" gate (see
  `complexity_router`'s cautionary tale in `routing-project-learnings.md` §11, item 3 - an
  always-on classifier whose output nothing uses is a known anti-pattern here; make sure this one's
  output *is* actually used, i.e. always feed the condensed question into `build_graph()`, never
  skip it).
- **How much conversation history does `condense_question()` need?** Full history vs. last N turns
  vs. a running summary - start simple (full history, these conversations are short) and revisit
  only if it becomes a real cost/latency problem, per this project's evidence-first culture.
- **Multi-hop/multi-topic questions across turns**: Level 9 (multi-hop) already recursively invokes
  `build_graph()` for sub-questions within a single turn - interaction between that and
  cross-turn follow-ups needs explicit test cases, not just assumed to work.

---

## 8. Will this be production-ready and open source when done?

**Open source: yes, fully.** Every piece of the proposed stack is open source and can be
self-hosted with no vendor lock-in: LangGraph itself (MIT), Agent Chat UI (MIT, the official
LangChain Next.js template), CopilotKit's core SDK/runtime (MIT - see the "open source vs.
Intelligence" distinction discussed earlier in this session; only the optional paid add-ons
sit outside the MIT-licensed core), and Streamlit (Apache 2.0) for the evaluation dashboard that
stays alongside it. Nothing in this plan requires a paid service to work.

**Production-ready: no, not from this plan alone - and that's worth being explicit about.** This
plan is scoped specifically to *the conversational AI logic* (condensing follow-ups, wrapping the
existing routing pipeline, wiring up an open-source chat frontend) - it deliberately does not
cover the separate body of work "production-ready" actually implies. Before treating the result of
this plan as production-ready, the following still need their own explicit design/implementation
(none of them are started by anything above):

- **Authentication & authorization** - who can use the chat app, multi-tenant data isolation if
  more than one customer/organization uses it. Nothing here today (the Streamlit dashboard and
  `smarthome-csr` are both single-user dev tools).
- **Durable, production-grade persistence** - §6 explicitly scopes the checkpointer as
  `InMemorySaver` first (conversation history lost on every restart), with "graduate to a
  persistent backend" noted but not designed - a real deployment needs that migration actually
  done (SQLite is fine for one process; Postgres/Redis for anything horizontally scaled).
- **Rate limiting & cost controls** - nothing stops a user from running up API costs; the
  project's `CachedEmbeddings`/SQLite LLM cache (`app/cache.py`) helps during *development*, not
  against a malicious/runaway user in production.
- **Security hardening beyond `sql_query.py`'s SELECT-only guard** - that guard (added earlier
  this session) covers one tool; a production chat app facing real users needs a broader look at
  prompt-injection resistance, output moderation (see `reference/rag_krish/agent_core/moderation.py`
  for an in-repo-adjacent pattern worth porting - not yet done here), and abuse handling generally.
- **Observability/alerting at production scale** - this project's MLflow tracing is explicitly
  "on-demand, not always-on" (matches the user's own stated preference) - a real deployment needs
  always-on logging, error alerting, and latency/cost dashboards, not a tracer you start manually.
- **Scaling & deployment infrastructure** - horizontal scaling, load testing, a real CI/CD pipeline,
  secrets management for API keys outside a local `.env` file - none of this exists yet for any
  project in this repo.
- **Data retention/privacy policy** for stored conversation history, once it's persisted somewhere
  real.

**Bottom line**: following this plan gets you a genuinely working, fully open-source, self-hostable
*prototype* chat application with a real conversational UI - a legitimate and valuable milestone,
and a correct foundation to build on. It does not, by itself, get you something you'd put in front
of real customers without the additional production-hardening work listed above, which is a
separate, substantial effort of its own and should be scoped as its own follow-up plan once this
one is validated.

---

## 9. Suggested immediate next step

Build Phase 0: `app/chat/state.py` + `app/chat/condense.py` + `app/chat/graph.py`, plus a handful
of hand-written multi-turn conversations run through a CLI script to sanity-check the condensing
step and conversation flow - before writing any ground-truth dataset, test file, or touching the
frontend at all. This is the cheapest possible way to find out whether the wrap-don't-rewrite
design in §3 actually works end to end.
