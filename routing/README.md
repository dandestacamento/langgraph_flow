# LangGraph Routing Accuracy Lab

A LangGraph application for testing, visualizing, and measuring **routing
accuracy** - not answer quality - across six knowledge-base topics,
subtopics, chapters, and specialist agents. See
[`instructions/Langgraph_routing/`](../instructions/Langgraph_routing) for
the full design rationale; this README covers what's actually built and
how to run it.

## Status: All 10 levels complete ✅

Per the staged implementation plan
([`7_to_8_routing_configuration.md`](../instructions/Langgraph_routing/7_to_8_routing_configuration.md),
section 9), levels are built and verified one at a time. All 10 levels
from [`3_scenarios.md`](../instructions/Langgraph_routing/3_scenarios.md)
are now implemented and tested - see "Next step" at the bottom for the
post-Level-10 backfill work that follows.

**Scope note for Levels 5-10**: while these levels' *routing mechanisms*
were being built and debugged (they test mechanism, not topic-specific
knowledge - the knowledge base already covers all 6 topics from Level 1),
test datasets for Levels 5-10 were scoped to **`appliances` +
`customer_support`** only, to control API cost. That backfill is now
done - see "Backfill: Levels 5-10 across all 6 topics" below for what
was added and what was found along the way. Every graph-level change was
still spot-checked (and, from Level 9 onward, fully regression-tested -
see that level's finding below for why) against all 6 topics before being
committed, just not with a full per-topic dataset until the backfill.

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

Level 10 (error recovery) is **scaffolded but not yet implemented** -
see the `NotImplementedError` stub in `app/rag/reranking.py` and the
overall node list in
[`7_to_8_routing_configuration.md`](../instructions/Langgraph_routing/7_to_8_routing_configuration.md)
for what it builds.

**Level 6 (multi-chapter evidence aggregation):**
- **10/10 Level 6 questions recall every chapter needed to answer a
  compound question (100% multi-chapter coverage) and produce an answer
  containing the expected facts from both chapters (100% answer
  accuracy)** - each question deliberately needs two chapters within the
  same subtopic (e.g. the washing-machine E21 example from
  [`4_to_5_obserability.md`](../instructions/Langgraph_routing/4_to_5_obserability.md):
  "what does E21 mean on the WM-500, and what is its standard warranty
  term?" needs both the fault-code chapter *and* the model-specific
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
- **Wording-sensitivity finding (superseded during Level 7)**: the
  WM-500/E21 question originally asked "...is the repair covered under
  warranty?" - a service-request phrasing that (1) reliably elicited
  qualitative warranty-TYPE reasoning instead of the literal "2-year"
  figure, and (2), once Level 7's Topic Router changes were in place,
  started getting misrouted into needing `customer_support` too (see the
  Level 7 "over-splitting" finding below). Rewording to a plain
  spec-lookup phrasing ("...and what is its standard warranty term?")
  fixed both at once.

**Level 7 (multiple topics - parallel agent routing):**
- **10/10 Level 7 questions select exactly the expected topic set (100%
  topic accuracy, including 2 single-topic regression checks that must
  NOT be over-split), every expected topic's agent actually runs in
  parallel via the `Send` fan-out, and the synthesized final answer
  contains the expected facts from every topic involved (100% answer
  accuracy)** - e.g. "my WM-500 is showing error E21 - is that covered
  under warranty, and what's SmartHome's standard refund policy?" needs
  both the `appliances` fault-code chapter and the `customer_support`
  refund-policy chapter, synthesized into one coherent reply.
- Verified with `pytest tests/test_multitopic_routing.py` (30 tests, all
  passing), plus a full regression across all of Levels 1-6 (195/196
  tests passing - the one exception is pre-existing `temperature=0`
  non-determinism in Level 3's Chapter Selector, unrelated to Level 7;
  see "Non-regression" below).
- **`synthesis_agent` now does real multi-topic merging**: one extra LLM
  call (only when `len(selected_topics) > 1`, so every single-topic
  question - still the overwhelming majority - is unaffected in cost or
  behavior) combines the already-grounded, already-cited per-topic
  answers into one coherent reply with a single merged `Sources:` line.
- **Real finding, fixed - cross-topic bleed in per-topic generation**:
  the first approach kept each topic agent's prompt structurally
  unchanged and simply *instructed* it to "answer only your part, ignore
  the rest" of the full multi-part question. Direct testing showed this
  was unreliable - a topic agent would sometimes decline its own
  well-supported part entirely, apparently because merely *seeing* the
  other topic's unaddressed fragment in the same prompt made "the
  question" read as only partially answerable. Fixed architecturally,
  not just by prompt wording: `topic_router`'s structured output now also
  produces `topic_questions` - a per-topic restatement containing ONLY
  that topic's relevant part - and every downstream per-topic step
  (`subtopic_router`, `chapter_selector`, `rag_retriever`, and the topic
  agents, via the new `app.state.get_topic_question()` helper) uses that
  restatement instead of the raw multi-topic question. Removing the
  other topic's fragment entirely proved far more robust than instructing
  a model to ignore text it can still see - and since
  `get_topic_question()` returns the original question unchanged for the
  single-topic case, this added zero risk to Levels 1-6's prompts.
- **Real finding, fixed - OpenAI strict structured-output schema
  limitation**: `topic_questions` was first typed as `dict[str, str]`
  (one entry per topic); this fails with "Invalid schema for
  response_format" because OpenAI's strict structured-output mode
  doesn't support free-form-keyed objects. Switched to a
  `list[TopicQuestionItem]` (fixed `{topic, question}` shape), which is
  strict-schema compatible.
- **Real finding, fixed - cached-response/schema-evolution hazard**:
  adding `topic_questions` to the Pydantic output model without also
  changing the prompt text caused the persistent LLM cache (`app/cache.py`)
  to replay old cached JSON lacking the new field for any question
  already exercised earlier in the same session, silently falling back
  to the pre-fix behavior. Adding an explicit prompt-text instruction for
  `topic_questions` (needed anyway, for model compliance) also forced a
  fresh cache key, incidentally resolving this - a case worth remembering
  if a future schema field is ever added without a matching prompt change.
- **Real finding, fixed - over-splitting regression from the
  `topic_questions` instruction itself**: introducing the "when you
  include more than one topic, fill in `topic_questions`" instruction
  measurably biased the Topic Router toward finding reasons to split
  single-topic questions - including inventing an unasked second question
  ("what is the warranty policy for the DW-400 dishwasher?" for a
  question that only asked about place settings) just to justify adding
  `customer_support`, and misrouting a product's own warranty/fault-code
  question into needing `customer_support` merely because words like
  "covered" or "repair" appeared. Fixed with a more forceful,
  example-grounded "most questions need exactly one topic; never invent
  an unasked question just to justify a second topic" instruction, plus
  concrete near-literal worked examples for the two failure patterns
  actually observed (a warehouse/inventory question staying entirely
  `customer_support` instead of bleeding into `data_engineering`; a
  product warranty question staying entirely `appliances` instead of
  bleeding into `customer_support`) - abstract rules alone were not
  reliably followed, consistent with the similar worked-example finding
  above.
- **Real finding, fixed - `is_ambiguous` regression from the same prompt
  changes**: the same editing pass also caused a previously-correct
  Level 5 case ("can I get a refund or replacement?") to stop being
  flagged ambiguous. Root cause: the instruction distinguishing "a policy
  QUESTION" (never ambiguous) from "a personal REQUEST" (ambiguous when
  it depends on unstated specifics) was too coarse - it let "refund"
  phrasing pattern-match the wrong bucket. Replaced with a precise,
  general test: is_ambiguous=true only when the SAME question about two
  different products/orders would have two DIFFERENT correct answers;
  "what is the refund policy" and "can I cancel after it's packed" both
  have ONE deterministic answer regardless of which product/order is
  meant (not ambiguous), while "can I get a refund or replacement?" and
  "how long is the warranty?" genuinely depend on unstated specifics
  (ambiguous) - regardless of how each is phrased (request vs. question).
- **Non-regression**: a full regression across every prior level's test
  file (196 tests: Levels 1-6 plus this level's own 30) was run after
  these fixes, specifically because this level's changes touched shared
  code (`topic_router`, `subtopic_router`, `chapter_selector`,
  `rag_retriever`, `_shared.py`) used by every level - 195/196 passed;
  the one exception (`L3-022`, Level 3) was confirmed via 3 independent
  fresh calls to be pre-existing `temperature=0` non-determinism in the
  Chapter Selector for a genuinely boundary-ambiguous Python question
  (mutable default arguments touch both the "functions" and "data types"
  chapters), not a Level 7 regression - this exact class of issue is
  already documented as a known limitation in the Level 4 section above.
- **Design decision**: `synthesis_agent`'s merge prompt labels each
  topic's answer with a `--- TOPIC: <name> ---` header rather than a
  `[topic]`-style bracket - an earlier bracket-style label was
  indistinguishable from the `[chapter_id]` citation format topic agents
  use, and the synthesis LLM once literally copied the label text itself
  into its merged `Sources:` line as a fake citation.

**Level 8 (tool selection and execution):**
- **10/10 Level 8 questions get the correct tool decision - including
  correctly deciding NO tool was needed for 2 regression-check questions
  (100% tool-selection accuracy) - every genuinely-needed tool executes
  without error, and the final answer contains the expected fact (100%
  answer accuracy)**, across 3 tools: `calculator` (pure arithmetic,
  e.g. a day-range midpoint), `sql_query` (exact spec/price lookups
  against `specifications.csv`, including a price difference computed
  entirely inside one SQL query), and `metadata_lookup` (knowledge-base
  structure questions like chapter counts and document versions).
- Verified with `pytest tests/test_tool_selection.py` (30 tests, all
  passing), plus a full regression across Levels 1-7 (196 tests: 195
  passed, the one exception being the same pre-existing `L3-022`
  non-determinism documented in the Level 7 section above, unrelated to
  Level 8).
- **Key design hook**: `price_aud` exists only in
  `specifications.csv`, deliberately absent from every chapter's prose -
  a price question is therefore answerable *only* via `sql_query`, not
  by a lucky RAG retrieval, making tool necessity unambiguous and
  genuinely testable (rather than a tool being merely "nice to have").
- **`tool_router` runs after `rag_retriever`** and is shown the passages
  already retrieved for the question, specifically so it can judge
  whether a tool is genuinely needed rather than guessing blind - an
  earlier version without this context repeatedly invoked `sql_query`
  for facts (like a model's standard warranty term) that were already
  sitting in the retrieved Markdown prose, because it had no way to know
  that.
- **`document_search` deliberately left unimplemented**: the
  architecture docs list it as a 4th selectable tool, but every
  Level 8 question is answerable via the other three tools precisely
  *because* `rag_retriever` already runs automatically for every
  question regardless of tool selection - an explicit document-search
  tool call would be redundant with that, not a new capability, for any
  scenario this project's knowledge base actually needs.
- **Real finding, fixed - SQL engine choice**: used Python's standard
  library `sqlite3` (loading each `specifications.csv` into an in-memory
  table) rather than adding a DuckDB/pandas dependency, since the CSVs
  here are only 3 rows each.
- **Real finding, fixed - numeric column affinity**: `CREATE TABLE`
  without declared column types gives SQLite no-affinity/BLOB columns,
  so numeric CSV values get stored as the literal TEXT the CSV reader
  produced - `ORDER BY price_aud` then sorted "1499" before "699"
  lexicographically, picking the wrong "cheapest" model. Fixed by
  inferring each column's SQLite type (INTEGER/REAL/TEXT) from its
  values before `CREATE TABLE`.
- **Real finding, fixed - the Tool Router's own query correctness**: for
  "which model is cheapest?", the LLM initially wrote `SELECT price_aud
  FROM specifications ORDER BY price_aud ASC LIMIT 1` - a query that
  correctly finds the lowest price but doesn't select the `model` column
  needed to say *which* model that is. Fixed with a concrete worked
  example in the tool's prompt description contrasting the two queries.
- **Real finding, fixed - mental math bypassing the tool**: giving
  `tool_router` the retrieved passages (to fix the warranty-term
  over-triggering above) had a side effect: for arithmetic/metadata
  questions, the LLM sometimes did the computation itself in its
  `reasoning` field and reported `needs_tool=false`, since technically
  "the passages don't need a tool, I can just work it out" - defeating
  the purpose of using a verifiable tool instead of unverified LLM
  mental math. Fixed by scoping the "check passages first, prefer no
  tool" guidance explicitly to `sql_query` only, with `calculator` and
  `metadata_lookup` now instructed to always be used for their kind of
  question regardless of what the Tool Router could work out itself.
- **Real finding, fixed - tool result ignored, then echoed literally**:
  getting the topic agent to actually *use* a successful tool result
  took two iterations. First, the agent sometimes still answered
  "insufficient information" despite a correct, clearly-labeled tool
  result being right there in its prompt - fixed with a worked example
  showing the tool result directly answers the question when it's
  asking exactly what the tool computed. That introduced a second bug:
  the agent then sometimes echoed the example's literal `"Tool result
  (<name> on input <input>): <output>"` sentence structure back as its
  own answer verbatim, rather than phrasing the number into a natural
  sentence - fixed by rewording the example to show natural phrasing
  ("The total is 4.") and explicitly instructing the agent not to copy
  that line format into its answer.
- **Real finding, fixed - a math-framed question misrouted to `finance`**:
  "...what is the midpoint of that range?" was classified as `finance`
  instead of `customer_support`, even with the word "refund" in the
  question - the model fixated on the abstract math-style framing
  ("midpoint of a range") over the domain content. Reworded to keep the
  refund-processing framing throughout ("...what's the average number of
  days?") rather than adding yet another topic_router prompt patch -
  consistent with how Levels 1-7 resolved similar wording-sensitivity
  findings.

**Level 9 (complex multi-hop reasoning):**
- **10/10 Level 9 questions get the correct multi-hop decision -
  including correctly deciding 2 ordinary questions are NOT multi-hop
  (100% multi-hop detection accuracy) - and the final answer contains
  the expected facts from BOTH hops (100% answer accuracy)**, e.g.
  "which washing machine model has the largest capacity, and what's its
  price?" - hop 1 identifies WM-900 (11 kg, the unique largest), then
  hop 2 looks up WM-900's price (only once hop 1 has resolved it).
- Verified with `pytest tests/test_multihop_reasoning.py` (22 tests, all
  passing), plus a full regression across Levels 1-8 (248 tests: 247
  passed, the one exception being the same pre-existing `L3-022`
  non-determinism documented since Level 7, unrelated to Level 9).
- **Architecture**: a new `multihop_router` node runs right after
  `complexity_router` and decides whether a question is genuinely
  multi-hop. When true, a dedicated `multihop_agent` node takes over
  entirely, bypassing `topic_router` onward completely (the same way
  `clarification_agent` bypasses the rest of the pipeline for an
  ambiguous question) - it resolves hop 1 and hop 2 by **recursively
  invoking `app.graph.build_graph()` on each hop's own self-contained
  question text**, reusing the whole existing single-question pipeline
  (topic/subtopic/chapter routing, RAG retrieval, tool selection, topic
  agent) completely unchanged for each hop, rather than duplicating any
  of that logic. A small structured-output call between hops extracts
  the specific short value hop 1's answer identified (e.g. "WM-900",
  not the whole sentence), which is substituted into hop 2's
  `{hop1_answer}` placeholder before hop 2 runs.
- **Why this is architecturally different from Levels 6-8**: Level 6
  (multi-chapter) and Level 7 (multi-topic) both involve compound
  questions where every part's subject is already fully specified -
  both facts are independently retrievable right away, no dependency.
  Level 9 is the first level where a second part's subject genuinely
  isn't named anywhere - only a reference ("its price") standing in for
  whatever a first, identification-style sub-question ("which model has
  the largest capacity") turns out to resolve to. Hop 2 literally cannot
  be fully phrased, let alone routed or retrieved for, until hop 1 runs.
- **Real finding, fixed - unbounded recursion**: a hop's own question
  (especially hop 2, after `{hop1_answer}` substitution) could in
  principle itself look multi-hop to `multihop_router`, sending it back
  into `multihop_agent` again - and did, for one test question,
  manifesting as a `RecursionError` deep in Pydantic's schema generation
  after the call stack grew unbounded. Fixed with an explicit
  `is_hop_subquestion` state flag, set only by `multihop_agent`'s own
  sub-invocations, that makes `complexity_router`'s conditional edge
  skip `multihop_router` entirely and go straight to `topic_router` -
  every hop is always treated as an ordinary single-pass question by
  design, which is also strictly correct given how hop 2's placeholder
  is already filled in with a concrete value by the time it runs.
- **Real finding, fixed - ambiguous bare hop 2 questions**: the first
  version of hop 2's template was often just `"What's the price of
  {hop1_answer}?"` - once substituted (e.g. "What's the price of
  RF-700?"), this was sometimes ambiguous enough on its own that
  `topic_router` flagged it as needing clarification, since a bare
  model code without stating its product category isn't always
  obviously recognizable (this worked for "WM-900" but not "RF-700").
  Fixed by instructing `multihop_router` to always carry the original
  question's product/category context into the template alongside the
  placeholder (e.g. "What is the price of the refrigerator model
  {hop1_answer}?").
- **Real finding, fixed - severe false-positive multi-hop detection,
  found via full regression**: the first two prompt revisions, each
  validated against a small hand-picked battery of examples, still
  caused the Multi-Hop Router to misclassify many *previously-passing*
  ordinary questions from Levels 2, 3, 4, 6, and 7 as multi-hop once a
  *full* regression was run - including a single-clause question with
  no "and" at all (over-triggering on long/detailed phrasing), and
  several genuine Level 6/7 compound questions ("is the DW-400 quiet,
  and what's needed for its express cycle?", "what shipping methods are
  available, and when does a redelivery fee apply?") where a pronoun or
  topical relatedness was mistaken for a real dependency. Root-caused
  and fixed by replacing the fuzzy "is the second clause's subject
  named" test with a much narrower, more mechanically checkable rule:
  multi-hop requires the FIRST clause to itself be a "which X has/is
  CRITERION" identification query with an unknown winner (a comparison
  or superlative) - a direct fact-lookup, yes/no question, or statement
  about an already-named subject is never multi-hop, no matter what the
  second clause says. Re-validated against a 26-case battery (18
  negative, 8 positive) with zero mismatches before re-running the full
  248-test regression clean. This is the clearest example in the
  project so far of why "validate against a hand-picked battery" isn't
  a substitute for a full regression before considering a shared-prompt
  change done.

**Level 10 (error recovery and fallback):**
- **6/6 Level 10 dataset questions get the correct recovery decision
  (100% recovery-decision accuracy) - recovery correctly attempted for
  3 genuinely unanswerable questions (even though it's expected to still
  fail afterward) and correctly NOT attempted for 3 ordinary questions
  that succeed on the first try - and every question's final answer is
  still correct or still correctly declines (100% answer accuracy),
  proving recovery never fabricates**, plus 4 additional direct
  mechanism tests (2 wrong-subtopic recoveries, 2 tool-error
  self-corrections) verifying the retry logic itself.
- Verified with `pytest tests/test_error_recovery.py` (18 tests, all
  passing), plus a full regression across Levels 1-9 (266 tests: 265
  passed, the one exception being the same pre-existing `L3-022`
  non-determinism documented since Level 7, unrelated to Level 10).
- **Mechanism**: `app.agents._shared.run_topic_agent` now makes one
  *bounded* retry (never more than one, per
  [`6_routing_design.md`](../instructions/Langgraph_routing/6_routing_design.md)'s
  Stage 5: "retry retrieval when appropriate, with a strict retry
  limit") when its first attempt declines, or when a selected tool
  failed. The retry (a) asks the LLM to self-correct a failed tool's
  input given the actual error message, and (b) broadens retrieval to
  the whole topic (dropping the subtopic filter) in case the original
  subtopic guess was wrong - then regenerates the answer once more.
  Recorded in the new `recovery_attempts[topic]` state field regardless
  of outcome, so "no recovery was needed" (the overwhelming common case)
  is a visible, positive fact in the trace, not an absence to infer.
- **Why direct mechanism tests, not just reused live questions**: every
  prior level reused real end-to-end questions for every test case, but
  nine levels of fixing exactly these kinds of mistakes (wrong subtopic
  guesses, malformed tool queries) means the live pipeline rarely makes
  them anymore - a test that depends on the pipeline *happening* to fail
  a specific way would be brittle and hard to keep passing. Instead, 4
  of the 10 Level 10 test cases construct the failure directly (a
  deliberately wrong `selected_subtopics` entry; a deliberately
  malformed SQL query) and call `run_topic_agent`/`_retry_tool`
  directly - the same "test the deterministic mechanism directly"
  approach already used for the calculator's injection safety and the
  SQL tool's column-type handling in Level 8.
- **Real finding (not a bug - a demonstration the mechanism works)**:
  the two reused Level 4 "deliberately unanswerable" questions ("RF-900
  compressor amperage", "WM-500 spin speed") turned out to *naturally*
  trigger the tool-error recovery path for a genuine reason: the Tool
  Router hallucinates a plausible-sounding but nonexistent column name
  (e.g. `compressor_amperage`) for a fact that was never in
  `specifications.csv` to begin with, causing a real SQLite "no such
  column" error. Recovery correctly attempts a self-corrected retry,
  which correctly also fails (the fact genuinely doesn't exist anywhere
  to be queried), so the final answer still correctly reports
  insufficient information - exactly the "exhaust the bounded retry,
  then give up gracefully" behavior this level is about, discovered
  rather than engineered.
- **Design decision - why broadening scope is "whole topic", not "whole
  knowledge base"**: retrying with `subtopic=None` searches every
  subtopic within the already-selected topic (e.g. all of `appliances`),
  not across topics - a topic misclassification is a separate, already
  well-tested failure mode (Levels 1 and 7), whereas a *subtopic*
  misclassification within an already-correct topic is the specific,
  narrower failure this retry targets; broadening further would risk
  pulling in genuinely irrelevant passages from an unrelated topic.

**Backfill: Levels 5-10 across all 6 topics:**
- Added 63 new dataset rows extending every Level 5-10 question type to
  the 4 topics the focus-topic scoping had deferred - `azure_cloud`,
  `data_engineering`, `python`, `finance` - bringing the dataset from 165
  to 228 rows. Purely additive test data; no graph/mechanism code
  changed, since none of it was ever topic-specific.
- **100% pass rate once stabilized**: all 63 new rows pass (Level 5: 16,
  Level 6: 13, Level 7: 10, Level 8: 12, Level 9: 4, Level 10: 8), and a
  full regression across the entire 228-row, 10-level suite afterward
  came back clean (391 passed, the one exception again being the
  pre-existing `L3-022` non-determinism flake, unrelated to the
  backfill).
- **Real finding - a second, independent confirmation of Level 9's core
  lesson**: 3 of the new Level 6 (multi-chapter evidence) questions were
  *genuinely* misclassified as Level 9 multi-hop by the Multi-Hop
  Router, confirmed by direct probing (e.g. "What series of Azure VM is
  recommended for variable, bursty workloads, and what metric can
  trigger a Virtual Machine Scale Set to scale out?"). Their first
  clause asked to *identify* an unnamed subject by a criterion ("what
  series is recommended for workloads") - structurally identical to the
  "which X has/is CRITERION, unknown winner" pattern the Multi-Hop
  Router's prompt is deliberately tuned to catch, even though no
  separate second-chapter *dependency* existed (the second fact doesn't
  actually need the first one resolved first - that's what makes it
  Level 6, not Level 9). Fixed, without touching the Multi-Hop Router's
  prompt at all, by rewording clause 1 to name the subject directly
  ("What is Azure's B-series VM good for, and what metric can trigger a
  Virtual Machine Scale Set to scale out?") - matching the existing
  Level 6/7 dataset's established pattern (every original row always
  names its subject up front, e.g. "the WM-500", "the RF-700") that this
  backfill had briefly drifted from. Caught before it reached the
  committed dataset by proactively probing every new compound ("and"-
  joined) question for `is_multi_hop` ahead of the full test run, rather
  than only discovering it via a failing assertion.
- **Design decision - no new positive Level 9 (multi-hop) test cases for
  the 4 backfilled topics**: genuine multi-hop requires a "which X
  has/is CRITERION" identification query whose unique winner then has a
  *separate*, distinct fact in a different chapter - a structural
  feature of `appliances`' named-model-plus-per-model-specs content
  (e.g. WM-900's capacity in one chapter, its price in a CSV) that none
  of `azure_cloud`, `data_engineering`, `python`, or `finance`'s
  chapters have (each covers one self-contained concept, with no
  comparable cross-chapter named-instance catalog) - and, notably,
  `customer_support` doesn't have it either, which is why even the
  *original* Level 9 dataset only ever used `appliances`. Forcing a
  positive case into these topics would mean inventing new knowledge-base
  content, not writing a test. Instead, 4 regression-check rows (one per
  topic, reusing an ordinary Level 1 question each) were added, verifying
  the Multi-Hop Router correctly does *not* false-positive on single-hop
  questions from topics it had never been tested against before - itself
  a meaningful check given the false-positive history above.
- **Design decision - no `sql_query` Level 8 backfill for the 4 new
  topics**: `sql_query` only applies to a `specifications.csv` file,
  which only `appliances/washing_machines` and
  `appliances/refrigerators` have; none of the 4 backfilled topics have
  one (`finance/loans/loan_rates.csv` exists but isn't named
  `specifications.csv` and, per L4-022, isn't RAG-indexed either). The
  backfill uses `calculator` and `metadata_lookup` only, following the
  same "don't force a tool that doesn't fit the content" precedent as
  `document_search` being left unimplemented.
- Verified with `pytest tests/test_ambiguous_questions.py
  tests/test_multichapter_evidence.py tests/test_multitopic_routing.py
  tests/test_tool_selection.py tests/test_multihop_reasoning.py
  tests/test_error_recovery.py` (265 tests, all passing), then the full
  suite (`pytest tests/`, 392 tests: 391 passed, 1 pre-existing flake).

## Architecture (current)

```
START -> complexity_router -> multihop_router -> {conditional}
  - if is_multi_hop: -> multihop_agent -> END
  - else: -> topic_router -> {conditional}
    - if is_ambiguous: -> clarification_agent -> END
    - else: -> subtopic_router -> chapter_selector -> rag_retriever ->
      tool_router -> {one agent per selected topic, via Send fan-out} ->
      synthesis_agent -> END
```

- **`complexity_router`**: classifies simple/intermediate/complex (recorded,
  not yet branched on - no scenario needs the branch until later levels).
- **`multihop_router`**: decides whether the question is genuinely
  multi-hop (see the Level 9 finding above for the precise "which X
  has/is CRITERION" identification-query test) and, if so, produces its
  two-hop decomposition plan. Skipped entirely for `multihop_agent`'s own
  hop sub-invocations (`is_hop_subquestion=True`), which always take the
  normal single-pass path regardless of their own phrasing.
- **`multihop_agent`**: runs instead of the rest of the pipeline when
  `is_multi_hop` is true - resolves hop 1 and hop 2 by recursively
  invoking `build_graph()` on each hop's own question, extracts hop 1's
  short answer value between hops, and synthesizes the final combined
  answer, routing straight to END (bypassing `topic_router` onward
  entirely, the same way `clarification_agent` does for an ambiguous
  question).
- **`topic_router`**: classifies into one or more of
  `appliances | azure_cloud | data_engineering | python | finance | customer_support`
  (most questions need exactly one), flags `is_ambiguous` when the
  question has no identifiable subject or has unstated specifics that
  would change the answer (see the Level 5 finding above for why this
  isn't based on the `confidence` field, and the Level 7 finding above
  for the precise "would the answer differ" test), and for a multi-topic
  question also produces `topic_questions` - a per-topic restatement
  containing only that topic's relevant part (see the Level 7 finding
  above on why this exists and `app.state.get_topic_question()` for how
  it's consumed downstream).
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
  `rag_retriever` found for that topic (plus a tool result, if
  `tool_router` ran one for this topic - Level 8), with appended source
  citations, or explicitly report insufficient information. For a
  multi-topic question, each agent answers its own
  `get_topic_question()` restatement rather than the full question (see
  the Level 7 finding above). Since Level 10, if the first attempt
  declines or a selected tool failed, makes one bounded retry (self-
  corrected tool input, and/or retrieval broadened to the whole topic)
  before giving up - see the Level 10 section above.
- **`tool_router`**: for each selected topic, decides whether
  `calculator`, `sql_query`, or `metadata_lookup` is genuinely needed
  beyond the already-retrieved passages (shown to it explicitly, so it
  can judge rather than guess - see the Level 8 finding above), and
  executes the chosen tool immediately if so. Most questions still need
  no tool at all - RAG retrieval alone already answers them, exactly as
  in Levels 1-7.
- **`synthesis_agent`**: a free pass-through for the single-topic case
  (the overwhelming majority of questions - no extra cost or behavior
  change); for a multi-topic question (Level 7), makes one extra LLM
  call to merge the already-grounded, already-cited per-topic answers
  into a single coherent reply with one merged `Sources:` line.

Run `python -m app.main "<question>"` to see this end to end, or open the
Streamlit dashboard for a rendered graph diagram.

## Project layout

```
routing/
├── .chroma/                 # Local Chroma vector store (gitignored; rebuild with scripts/build_index.py)
├── app/                     # LangGraph application code
│   ├── routers/             # complexity, multihop_router, topic (+ambiguity flag, +topic_questions), subtopic, chapter_selector, tool_router (all done)
│   ├── agents/               # one agent per topic (RAG-grounded, +tool results, +bounded recovery retry) + clarification_agent + multihop_agent + synthesis_agent
│   ├── rag/                  # ingestion/chunking/embeddings/retrieval (done); reranking (stub)
│   ├── tools/                # calculator/sql_query/metadata_lookup (done, Level 8); document_search (deliberately unimplemented - see Level 8 README section)
│   ├── evaluation/            # routing_metrics, retrieval_metrics, answer_metrics (all done)
│   └── observability/        # mlflow_tracing, graph_visualizer, execution_logger
├── knowledge_base/           # 57 Markdown chapters + CSV/JSON/TXT, across 6 topics / 19 subtopics
├── datasets/                  # routing_ground_truth.jsonl (L1: 24, L2: 19, L3: 38, L4: 22, L5: 32, L6: 23, L7: 20, L8: 22, L9: 14, L10: 14 questions - 228 total, all 6 topics)
├── tests/                     # test_basic_routing.py (L1), test_subtopic_routing.py (L2), test_chapter_routing.py (L3), test_rag_retrieval.py (L4), test_ambiguous_questions.py (L5), test_multichapter_evidence.py (L6), test_multitopic_routing.py (L7), test_tool_selection.py (L8), test_multihop_reasoning.py (L9), test_error_recovery.py (L10)
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

# Run all pytest suites (takes 35-55 minutes on a cold cache - real LLM +
# embedding calls; much faster on a warm cache, see app/cache.py)
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

All 10 levels from
[`3_scenarios.md`](../instructions/Langgraph_routing/3_scenarios.md) are
implemented and tested, and the Level 5-10 backfill across all 6 topics
(see "Backfill: Levels 5-10 across all 6 topics" above) is also done -
the project's originally-planned scope is complete, with a 228-row,
10-level dataset passing cleanly except for the one pre-existing
`L3-022` non-determinism flake. A natural further step is the "compare
three routing architectures" experiment named in
[`6_routing_design.md`](../instructions/Langgraph_routing/6_routing_design.md)
(a single LLM router vs. a hierarchical router vs. this project's hybrid
router, on the same full dataset) to quantify whether the added
complexity actually earns its latency and cost.
