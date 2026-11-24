"""Tests for the "compare three routing architectures" experiment
(`6_routing_design.md`) - Architectures A and B in `app/architectures/`
(Architecture C is `app.graph.build_graph()`, already covered by every
other test file).

These are deliberately lighter than the per-level test suites: A and B
exist to measure where the *simpler* architectures fall short, not to be
held to the same accuracy bar as the full hybrid router. This file
checks two things:

1. Both graphs build and run end to end, routing ordinary single-topic
   questions (Level 1/4) correctly - proving they're genuinely working
   minimal pipelines, not just scaffolding.
2. The documented architectural ceiling actually holds: on a genuinely
   multi-topic (Level 7) question, both A and B structurally answer only
   ONE topic, confirmed via `selected_topics` having length 1 - this is
   the experiment's central finding (see README's "Experiment: comparing
   three routing architectures" section), kept here as a regression
   guard so a future change can't silently and invisibly give A or B
   multi-topic support without anyone noticing it contradicts their own
   docstrings.
"""

from __future__ import annotations

import pytest

from app.architectures.arch_a_llm_router import build_arch_a_graph
from app.architectures.arch_b_hierarchical_router import build_arch_b_graph
from app.evaluation.answer_metrics import AnswerResult
from app.state import initial_state
from tests.conftest import load_ground_truth

_ARCHITECTURES = {
    "A": build_arch_a_graph,
    "B": build_arch_b_graph,
}

# A handful of Level 1 cases, one per topic, so both architectures are
# exercised against every topic's own data at least once.
_LEVEL_1_SAMPLE_IDS = {"L1-001", "L1-005", "L1-009", "L1-013", "L1-017", "L1-021"}
LEVEL_1_CASES = [c for c in load_ground_truth(level=1) if c["id"] in _LEVEL_1_SAMPLE_IDS]
assert len(LEVEL_1_CASES) == len(_LEVEL_1_SAMPLE_IDS), "Expected Level 1 sample IDs not found"

# A couple of Level 4 cases (answerable + deliberately unanswerable) to
# confirm both architectures ground answers in retrieval and decline
# gracefully, not just route correctly.
_LEVEL_4_SAMPLE_IDS = {"L4-001", "L4-020"}
LEVEL_4_CASES = [c for c in load_ground_truth(level=4) if c["id"] in _LEVEL_4_SAMPLE_IDS]
assert len(LEVEL_4_CASES) == len(_LEVEL_4_SAMPLE_IDS), "Expected Level 4 sample IDs not found"


@pytest.fixture(scope="module")
def arch_graphs():
    return {name: builder() for name, builder in _ARCHITECTURES.items()}


@pytest.mark.parametrize("arch_name", list(_ARCHITECTURES))
@pytest.mark.parametrize("case", LEVEL_1_CASES, ids=[c["id"] for c in LEVEL_1_CASES])
def test_single_topic_question_routes_correctly(arch_graphs, arch_name, case):
    """Both simpler architectures must still get ordinary single-topic
    routing right - the gap this experiment is about only shows up on
    Levels 6+ (see README), not on the easy majority case."""
    output = arch_graphs[arch_name].invoke(initial_state(case["question"]))
    actual_topics = output["selected_topics"]
    assert actual_topics == [case["expected_topics"][0]], (
        f"Architecture {arch_name} / {case['id']}: expected topic {case['expected_topics']}, "
        f"got {actual_topics} (question: {case['question']!r})"
    )


@pytest.mark.parametrize("arch_name", list(_ARCHITECTURES))
@pytest.mark.parametrize("case", LEVEL_4_CASES, ids=[c["id"] for c in LEVEL_4_CASES])
def test_answer_grounded_or_correctly_declines(arch_graphs, arch_name, case):
    """Both architectures reuse `app.agents._shared._generate_answer`, so
    they should answer correctly (or correctly decline when
    unanswerable) just as reliably as the full graph does for an
    ordinary single-topic question."""
    output = arch_graphs[arch_name].invoke(initial_state(case["question"]))
    result = AnswerResult(
        question_id=case["id"],
        actual_answer=output.get("final_answer", ""),
        expected_facts=case["expected_facts"],
        retrieved_texts=[p["text"] for p in output.get("retrieved_passages", {}).get(case["expected_topics"][0], [])],
        is_answerable=case["is_answerable"],
    )
    assert result.is_correct, (
        f"Architecture {arch_name} / {case['id']}: expected facts {case['expected_facts']} "
        f"(is_answerable={case['is_answerable']}), got answer: {output.get('final_answer', '')!r}"
    )


@pytest.mark.parametrize("arch_name", list(_ARCHITECTURES))
def test_multitopic_question_only_answers_one_topic(arch_graphs, arch_name):
    """The experiment's central finding, kept as a regression guard: a
    genuinely multi-topic (Level 7) question is structurally answered by
    only ONE topic in both A and B - neither has a multi-topic planning
    stage at all, by design (see each module's docstring)."""
    multi_topic_case = next(
        c for c in load_ground_truth(level=7) if len(c["expected_topics"]) > 1
    )
    output = arch_graphs[arch_name].invoke(initial_state(multi_topic_case["question"]))
    assert len(output["selected_topics"]) == 1, (
        f"Architecture {arch_name} unexpectedly selected more than one topic "
        f"({output['selected_topics']}) for a multi-topic question - this contradicts "
        f"its own single-topic-only design (see app/architectures/{arch_name.lower()}*.py)."
    )
