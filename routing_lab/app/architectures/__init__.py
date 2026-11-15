"""Alternative, simpler routing architectures built for the "compare three
routing architectures" experiment in
instructions/Langgraph_routing/6_routing_design.md.

`app.graph.build_graph()` (unchanged, used as-is) is Architecture C - the
"Hybrid Router" this whole project has built level by level: LLM
classification + semantic retrieval + multi-agent planning (Level 7) +
tool selection (Level 8) + multi-hop decomposition (Level 9) + bounded
error-recovery retry (Level 10).

This package adds the two simpler points of comparison from that same
design doc's table:

- `arch_a_llm_router`: Architecture A - "LLM selects one topic and
  agent". The simplest possible router: one LLM call picks a single
  topic, then a single grounded-answer call follows, retrieving at the
  topic level (no subtopic/chapter narrowing at all, since there is no
  such stage).
- `arch_b_hierarchical_router`: Architecture B - "Topic -> subtopic ->
  chapter -> retrieval". A deterministic three-stage cascade with no
  multi-topic planning, no tool selection, no ambiguity detection, no
  multi-hop decomposition, and no error-recovery retry - genuinely
  reusing `app.routers.subtopic_router`/`chapter_selector` and
  `app.rag.retrieval.retrieve_evidence` as-is (those nodes were already
  "pure" per-topic classifiers with no multi-topic/ambiguity logic baked
  in), with only its own single-topic classifier and a simplified,
  tool-less/retry-less answer node being new code.

Both reuse `app.agents._shared._generate_answer` for the final
answer-generation call - the same grounded, cited-answer logic
Architecture C's topic agents use - so the comparison isolates the
*routing* design as the variable under test, not answer-generation
quality.
"""
