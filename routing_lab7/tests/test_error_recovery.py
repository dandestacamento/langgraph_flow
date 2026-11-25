"""Level 10 tests: error recovery and fallback.

Two kinds of tests, for two different reasons:

1. **Dataset-driven, end-to-end tests** (`LEVEL_10_CASES`, via the full
   compiled graph): verify the *decision* to attempt recovery is correct
   - attempted for genuinely unanswerable questions (even though it's
   expected to still fail afterward - recovery being *attempted* is what
   Level 10 tests, not that an impossible question somehow succeeds), and
   NOT attempted for ordinary questions that should succeed on the first
   try (an unnecessary retry is itself a mistake - wasted cost for no
   reason, consistent with Level 8's tool-selection "efficiency"
   reasoning). Also verifies no hallucination: a genuinely unanswerable
   question must still correctly report insufficient information after
   recovery is exhausted, not fabricate an answer.

2. **Direct mechanism tests** (hardcoded, bypassing the full graph):
   Levels 1-9 all reused real end-to-end questions for every test case,
   but Level 10's two recovery paths are hard to reliably *provoke* live
   - a wrong subtopic guess or a tool error are things the pipeline
   mostly no longer makes (after nine levels of fixing exactly those
   kinds of mistakes). Rather than writing brittle tests that depend on
   the live pipeline *happening* to fail a specific way, these construct
   the failure directly (a deliberately wrong `selected_subtopics` entry,
   a deliberately malformed SQL query) and call `run_topic_agent`/
   `_retry_tool` directly - the same "test the deterministic mechanism
   directly" approach already used for the calculator's safety and the
   SQL tool's column-type handling in Level 8.
"""

from __future__ import annotations

import pytest

import app.agents._shared as shared_agent
from app.agents._shared import _retry_tool, run_topic_agent
from app.chat.routing_summary import build_routing_summary
from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.routing_metrics import RecoveryResult, summarize_recovery
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_10_CASES = load_ground_truth(level=10)
assert LEVEL_10_CASES, "No Level 10 cases found in datasets/routing_ground_truth.jsonl"

MIN_RECOVERY_DECISION_ACCURACY = 0.9
MIN_ANSWER_ACCURACY = 0.85


@pytest.mark.parametrize("answerable", [True, False])
def test_unverified_answer_is_scored_as_a_decline(answerable):
    result = AnswerResult(
        question_id="unverified",
        actual_answer=shared_agent.UNVERIFIED_ANSWER_MARKER,
        expected_facts=["expected fact"],
        retrieved_texts=[],
        is_answerable=answerable,
    )
    assert result.is_correct is not answerable


def test_synthesis_preserves_a_topic_answer_that_could_not_be_verified(monkeypatch):
    import app.agents.synthesis_agent as synthesis_agent

    def unexpected_synthesis(**kwargs):
        pytest.fail("A declined topic must not be sent to synthesis")

    monkeypatch.setattr(synthesis_agent, "ChatOpenAI", unexpected_synthesis)
    result = synthesis_agent.synthesize({
        "question": "q",
        "selected_topics": ["first", "second"],
        "agent_responses": {
            "first": "Verified answer.",
            "second": shared_agent.UNVERIFIED_ANSWER_MARKER,
        },
    })
    assert "Verified answer." in result["final_answer"]
    assert shared_agent.UNVERIFIED_ANSWER_MARKER in result["final_answer"]


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_10_CASES, ids=[c["id"] for c in LEVEL_10_CASES])
def test_recovery_attempted_matches_expected(compiled_graph, case):
    """Recovery must be attempted exactly when expected - for a
    genuinely unanswerable question (even though it will still fail), and
    NOT for an ordinary question that succeeds on the first attempt."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    recovery = output["recovery_attempts"].get(expected_topic, {})

    result = RecoveryResult(
        question_id=case["id"],
        expected_recovery_attempted=case["expected_needs_recovery"],
        actual_recovery_attempted=recovery.get("attempted", False),
    )
    assert result.is_correct, (
        f"{case['id']}: expected recovery attempted={case['expected_needs_recovery']!r}, got "
        f"{recovery.get('attempted')!r} (reason={recovery.get('reason')!r}, "
        f"question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", LEVEL_10_CASES, ids=[c["id"] for c in LEVEL_10_CASES])
def test_answer_correct_or_gracefully_declines(compiled_graph, case):
    """An answerable question must still answer correctly (possibly
    after a recovery retry); a genuinely unanswerable one must still
    correctly report insufficient information, not fabricate, even after
    recovery was attempted and failed."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    answer = output["agent_responses"].get(expected_topic, "")
    retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=answer,
        expected_facts=case["expected_facts"],
        retrieved_texts=retrieved_texts,
        is_answerable=case["is_answerable"],
    )
    assert result.is_correct, (
        f"{case['id']}: expected is_answerable={case['is_answerable']!r} with facts "
        f"{case['expected_facts']}, got answer: {answer!r}"
    )


def test_level_10_overall_recovery_decision_accuracy(compiled_graph):
    """Suite-level recovery-decision accuracy across every Level 10 question."""
    results = []
    for case in LEVEL_10_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        recovery = output["recovery_attempts"].get(expected_topic, {})
        results.append(
            RecoveryResult(
                question_id=case["id"],
                expected_recovery_attempted=case["expected_needs_recovery"],
                actual_recovery_attempted=recovery.get("attempted", False),
            )
        )

    summary = summarize_recovery(results)
    print(f"\nLevel 10 recovery decision summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["recovery_decision_accuracy"] >= MIN_RECOVERY_DECISION_ACCURACY, (
        f"Level 10 recovery decision accuracy {summary['recovery_decision_accuracy']:.0%} is below "
        f"the {MIN_RECOVERY_DECISION_ACCURACY:.0%} target. Failed: {failures}"
    )


def test_level_10_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy (correct answers + correct graceful
    declines) across every Level 10 question."""
    results = []
    for case in LEVEL_10_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        answer = output["agent_responses"].get(expected_topic, "")
        retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]
        results.append(
            AnswerResult(
                question_id=case["id"],
                actual_answer=answer,
                expected_facts=case["expected_facts"],
                retrieved_texts=retrieved_texts,
                is_answerable=case["is_answerable"],
            )
        )

    summary = summarize_answers(results)
    print(f"\nLevel 10 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 10 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )


# --- Direct mechanism tests (bypass the full graph; see module docstring) ---

def test_recovery_exposes_passages_actually_used_for_answer(monkeypatch):
    original = {"chapter_id": "old", "text": "wrong"}
    recovered = {"chapter_id": "new", "text": "correct", "source": "manual.pdf", "page": 8, "version": 1}
    answers = iter([("not found", True), ("correct", False)])
    monkeypatch.setattr(shared_agent, "_generate_answer", lambda *args: next(answers))
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [recovered])
    monkeypatch.setattr(shared_agent, "_answer_is_supported", lambda *args: True, raising=False)
    state = {
        "question": "q", "retrieved_passages": {"appliances": [original]},
        "tool_decisions": {}, "tool_results": {},
    }
    result = run_topic_agent("appliances", state)
    summary = build_routing_summary(result)
    assert summary["passages"]["appliances"][0]["source"] == "manual.pdf"
    assert summary["passages"]["appliances"][0]["page"] == 8
    assert summary["passages"]["appliances"][0]["version"] == 1
    assert summary["passages"]["appliances"][0]["chapter_id"] == "new"


def test_unrelated_answer_triggers_retry_and_uses_verified_answer(monkeypatch):
    wrong = {"chapter_id": "summary", "source": "framework.pdf", "page": 25, "text": "Actions need not be ordered."}
    correct = {"chapter_id": "manual", "source": "framework.pdf", "page": 26, "text": "Functions may be performed in any order."}
    answers = iter([("Actions need not be ordered.", False), ("Functions may be performed in any order.", False)])
    assessments = iter([False, True])
    monkeypatch.setattr(shared_agent, "_generate_answer", lambda *args: next(answers))
    monkeypatch.setattr(shared_agent, "_answer_is_supported", lambda *args: next(assessments), raising=False)
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [correct])
    state = {"question": "Must the functions be performed in order?", "retrieved_passages": {"appliances": [wrong]}}
    result = run_topic_agent("appliances", state)
    assert result["agent_responses"]["appliances"] == "Functions may be performed in any order."
    assert result["recovery_attempts"]["appliances"] == {
        "attempted": True, "reason": "answer_not_verified", "succeeded": True,
    }
    assert result["retrieved_passages"]["appliances"][0]["page"] == 26


@pytest.mark.parametrize("retry_has_upload", [True, False])
def test_unverified_retry_does_not_return_misleading_answer(monkeypatch, retry_has_upload):
    passage = {"chapter_id": "summary", "source": "framework.pdf", "text": "Actions need not be ordered."}
    monkeypatch.setattr(shared_agent, "_generate_answer", lambda *args: ("Actions need not be ordered.", False))
    monkeypatch.setattr(shared_agent, "_answer_is_supported", lambda *args: False, raising=False)
    retry_passage = passage if retry_has_upload else {"chapter_id": "other", "text": "Other content."}
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [retry_passage])
    result = run_topic_agent("appliances", {
        "question": "Must the functions be performed in order?", "retrieved_passages": {"appliances": [passage]},
    })
    assert result["agent_responses"]["appliances"] == shared_agent.UNVERIFIED_ANSWER_MARKER
    assert result["recovery_attempts"]["appliances"]["succeeded"] is False
    assert result["execution_log"][0]["output"]["answer_unverified"] is True
    assert result["execution_log"][0]["output"]["insufficient_info"] is False


def test_answer_check_compares_question_answer_and_evidence(monkeypatch):
    import json

    captured = []

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, model):
            assert model is shared_agent._AnswerCheck
            return self

        def invoke(self, messages):
            captured.append(json.loads(messages[1][1]))
            return shared_agent._AnswerCheck(verdict="unsupported", explanation="The answer concerns actions, not functions.")

    monkeypatch.setattr(shared_agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(shared_agent.llm_gateway, "llm_kwargs", lambda: {})
    assert not shared_agent._answer_is_supported(
        "Must the functions be performed in order?",
        "Actions need not be ordered.\n\nSources: framework.pdf",
        [{"text": "Actions need not be ordered."}],
        None,
    )
    assert captured[0]["question"] == "Must the functions be performed in order?"
    assert captured[0]["answer"] == "Actions need not be ordered."
    assert captured[0]["evidence"] == ["Actions need not be ordered."]


def test_first_pass_augments_uploaded_evidence_without_losing_original_results(monkeypatch):
    import app.rag.retrieval as retrieval

    original = {"document_id": "doc", "chapter_id": "manual", "version": 1, "page": 25, "text": "Actions are not a checklist.", "score": 0.1}
    extra = {"document_id": "doc", "chapter_id": "manual", "version": 1, "page": 26, "text": "Functions may be performed in any order.", "score": 0.2}
    calls = []

    def retrieve(query, **kwargs):
        calls.append(kwargs)
        if kwargs.get("retrieval_mode") == "hybrid":
            return [{**original, "score": 0.9}, extra]
        return [original]

    monkeypatch.setattr(retrieval, "retrieve", retrieve)
    monkeypatch.setattr(retrieval, "_has_uploaded_content", lambda *args: True, raising=False)
    result = retrieval.retrieve_evidence({
        "question": "Must the functions be performed in order?",
        "selected_topics": ["ai"], "selected_subtopics": {"ai": "risk"},
    })
    assert result["retrieved_passages"]["ai"] == [original, extra]
    assert calls[1]["retrieval_mode"] == "hybrid"
    assert calls[1]["top_k"] == 10 and calls[1]["candidate_pool_size"] == 40


def test_first_pass_without_uploads_preserves_existing_retrieval(monkeypatch):
    import app.rag.retrieval as retrieval

    calls = []
    passage = {"chapter_id": "original", "text": "original", "score": 0.1}
    monkeypatch.setattr(retrieval, "retrieve", lambda query, **kwargs: calls.append(kwargs) or [passage])
    monkeypatch.setattr(retrieval, "_has_uploaded_content", lambda *args: False)
    result = retrieval.retrieve_evidence({
        "question": "q", "selected_topics": ["ai"], "selected_subtopics": {"ai": "risk"},
    })
    assert result["retrieved_passages"]["ai"] == [passage]
    assert calls == [{"topic": "ai", "subtopic": "risk"}]


def test_recovery_uses_broader_hybrid_search_after_decline(monkeypatch):
    searches = []
    answers = iter([("not found", True), ("found", False)])
    monkeypatch.setattr(shared_agent, "_generate_answer", lambda *args: next(answers))

    def retrieve(query, **kwargs):
        searches.append((query, kwargs))
        return [{"chapter_id": "answer", "text": "found"}]

    monkeypatch.setattr(shared_agent, "retrieve", retrieve)
    state = {"question": "q", "retrieved_passages": {"appliances": []}}
    result = run_topic_agent("appliances", state)
    assert result["recovery_attempts"]["appliances"]["succeeded"] is True
    assert searches == [("q", {
        "topic": "appliances", "subtopic": None, "retrieval_mode": "hybrid",
        "top_k": 20, "candidate_pool_size": 40,
    })]


def test_hybrid_search_fuses_wider_candidates_before_limiting_results(monkeypatch):
    import chromadb
    import uuid
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    import app.rag.retrieval as retrieval

    class TestEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[float(text.split()[0].split("-")[1]), 0.0] for text in texts]

        def embed_query(self, text):
            return [0.0, 0.0]

    texts = [f"item-{i} unrelated information about systems and functions" for i in range(1, 40)]
    texts[30] = "item-31 functions may be performed in any order under governance"
    store = Chroma(client=chromadb.Client(), collection_name=f"retry_{uuid.uuid4().hex}",
                   embedding_function=TestEmbeddings())
    store.add_documents([
        Document(page_content=text, metadata={"topic": "ai", "subtopic": "risk", "chapter_id": str(i)})
        for i, text in enumerate(texts)
    ])
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: store)
    monkeypatch.setattr(retrieval, "_active_versions", lambda: None)
    retrieval._bm25_retriever.cache_clear()
    query = "Must the four core functions be performed in a fixed order?"
    narrow = retrieval.retrieve(query, "ai", "risk", top_k=20, retrieval_mode="hybrid")
    wider = retrieval.retrieve(query, "ai", "risk", top_k=20, retrieval_mode="hybrid", candidate_pool_size=40)
    assert not any("any order" in p["text"] for p in narrow)
    assert any("any order" in p["text"] for p in wider)
    assert len(wider) == 20
    assert all(p["score_type"] == "hybrid_rank" for p in wider)
    retrieval._bm25_retriever.cache_clear()


def test_vector_distance_type_survives_routing_summary(monkeypatch):
    from langchain_core.documents import Document
    import app.rag.retrieval as retrieval

    class Store:
        def similarity_search_with_score(self, query, k, filter):
            return [(Document(page_content="evidence", metadata={"chapter_id": "c1"}), 0.25)]

    monkeypatch.setattr(retrieval, "get_vector_store", lambda: Store())
    monkeypatch.setattr(retrieval, "_active_versions", lambda: None)
    passages = retrieval.retrieve("question", "ai", retrieval_mode="similarity")
    summary = build_routing_summary({"retrieved_passages": {"ai": passages}})
    assert summary["passages"]["ai"][0]["score"] == 0.25
    assert summary["passages"]["ai"][0]["score_type"] == "vector_distance"


def test_reranker_replaces_previous_score_type(monkeypatch):
    import app.rag.reranking as reranking

    class Encoder:
        def score(self, pairs):
            return [0.2, 0.8]

    monkeypatch.setattr(reranking, "_get_cross_encoder", lambda: Encoder())
    passages = [
        {"text": "first", "score": 0.1, "score_type": "vector_distance"},
        {"text": "second", "score": 0.5, "score_type": "hybrid_rank"},
    ]
    result = reranking.rerank("question", passages, top_k=2)
    assert [(p["text"], p["score"], p["score_type"]) for p in result] == [
        ("second", 0.8, "reranker"), ("first", 0.2, "reranker"),
    ]


def test_hybrid_search_returns_no_results_for_empty_scope(monkeypatch):
    import chromadb
    import uuid
    from langchain_chroma import Chroma
    from langchain_core.embeddings import Embeddings
    import app.rag.retrieval as retrieval

    class TestEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    store = Chroma(client=chromadb.Client(), collection_name=f"empty_{uuid.uuid4().hex}",
                   embedding_function=TestEmbeddings())
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: store)
    monkeypatch.setattr(retrieval, "_active_versions", lambda: None)
    retrieval._bm25_retriever.cache_clear()
    assert retrieval.retrieve("question", "ai", retrieval_mode="hybrid", candidate_pool_size=40) == []
    retrieval._bm25_retriever.cache_clear()


def test_recovery_reconsiders_same_evidence_without_reusing_first_prompt(monkeypatch):
    from types import SimpleNamespace

    prompts = []
    passage = {
        "chapter_id": "ingested_executive_summary", "source": "NIST.AI.100-1.pdf", "page": 9,
        "text": (
            "AI risk management offers a path to minimize potential negative impacts of AI systems, "
            "while also providing opportunities to maximize positive impacts."
        ),
    }

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            prompt = messages[0][1]
            prompts.append(prompt)
            content = (
                "AI risk management aims to minimize negative impacts and maximize positive impacts."
                if len(prompts) == 2 and prompt != prompts[0]
                else shared_agent.INSUFFICIENT_INFO_MARKER
            )
            return SimpleNamespace(content=content)

    monkeypatch.setattr(shared_agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(shared_agent.llm_gateway, "llm_kwargs", lambda: {})
    monkeypatch.setattr(shared_agent, "taxonomy_store", lambda: SimpleNamespace(get=lambda: {"appliances": ["manual"]}))
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [passage])
    monkeypatch.setattr(shared_agent, "_answer_is_supported", lambda *args: True, raising=False)
    state = {
        "question": "What is the purpose of the NIST AI Risk Management Framework?",
        "retrieved_passages": {"appliances": [passage]},
    }
    result = run_topic_agent("appliances", state)
    assert result["recovery_attempts"]["appliances"]["succeeded"] is True
    assert "minimize negative impacts" in result["agent_responses"]["appliances"]
    assert "ingested_executive_summary" not in prompts[0]
    assert "NIST.AI.100-1.pdf" in result["agent_responses"]["appliances"]


def test_recovery_reconsiders_conditional_yes_no_question(monkeypatch):
    from types import SimpleNamespace

    prompts = []
    passage = {
        "chapter_id": "manual", "source": "manual.pdf",
        "text": "If approval is in place, the steps may be performed in any order.",
    }

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            prompt = messages[0][1]
            prompts.append(prompt)
            if "conditions explicitly assumed in the question" in prompt:
                return SimpleNamespace(content="No, the steps may be performed in any order.")
            return SimpleNamespace(content=shared_agent.INSUFFICIENT_INFO_MARKER)

    monkeypatch.setattr(shared_agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(shared_agent.llm_gateway, "llm_kwargs", lambda: {})
    monkeypatch.setattr(shared_agent, "taxonomy_store", lambda: SimpleNamespace(get=lambda: {"appliances": ["manual"]}))
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [passage])
    monkeypatch.setattr(shared_agent, "_answer_is_supported", lambda *args: True)
    result = run_topic_agent("appliances", {
        "question": "Assuming approval is in place, must the steps be performed in a fixed order?",
        "retrieved_passages": {"appliances": [passage]},
    })
    assert len(prompts) == 2
    assert "any order" in result["agent_responses"]["appliances"]
    assert result["recovery_attempts"]["appliances"]["succeeded"] is True


def test_reconsideration_still_declines_unsupported_questions(monkeypatch):
    from types import SimpleNamespace

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content=shared_agent.INSUFFICIENT_INFO_MARKER)

    monkeypatch.setattr(shared_agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(shared_agent.llm_gateway, "llm_kwargs", lambda: {})
    monkeypatch.setattr(shared_agent, "taxonomy_store", lambda: SimpleNamespace(get=lambda: {"appliances": ["manual"]}))
    monkeypatch.setattr(shared_agent, "retrieve", lambda *args, **kwargs: [])
    result = run_topic_agent("appliances", {"question": "Unanswerable?", "retrieved_passages": {}})
    assert result["agent_responses"]["appliances"] == shared_agent.INSUFFICIENT_INFO_MARKER
    assert result["recovery_attempts"]["appliances"]["succeeded"] is False


def test_recovery_recovers_from_wrong_subtopic_guess():
    """If `selected_subtopics` is wrong and nothing relevant was
    retrieved under it, broadening retrieval to the whole topic must
    still find the right chapter and answer correctly."""
    state = {
        "question": "What does washing machine error E42 indicate?",
        "selected_topics": ["appliances"],
        "selected_subtopics": {"appliances": "refrigerators"},  # deliberately wrong
        "retrieved_passages": {"appliances": []},
        "tool_decisions": {},
        "tool_results": {},
    }
    result = run_topic_agent("appliances", state)
    recovery = result["recovery_attempts"]["appliances"]
    answer = result["agent_responses"]["appliances"]

    assert recovery["attempted"] is True
    assert recovery["succeeded"] is True
    assert "door lock" in answer.lower()


def test_recovery_recovers_from_wrong_subtopic_guess_customer_support():
    """Same recovery pattern, verified for a second topic/question to
    confirm it isn't specific to one chapter's retrieval quirk."""
    state = {
        "question": "What's included in White Glove delivery?",
        "selected_topics": ["customer_support"],
        "selected_subtopics": {"customer_support": "refunds"},  # deliberately wrong
        "retrieved_passages": {"customer_support": []},
        "tool_decisions": {},
        "tool_results": {},
    }
    result = run_topic_agent("customer_support", state)
    recovery = result["recovery_attempts"]["customer_support"]
    answer = result["agent_responses"]["customer_support"]

    assert recovery["attempted"] is True
    assert recovery["succeeded"] is True
    assert "installation" in answer.lower()


def test_retry_tool_self_corrects_wrong_column_name():
    """A sql_query with a hallucinated/typo'd column name must be
    self-corrected to the real column and re-executed successfully."""
    output, error = _retry_tool(
        "appliances",
        "washing_machines",
        "sql_query",
        "SELECT pricing FROM specifications WHERE model = 'WM-900'",
        "no such column: pricing",
    )
    assert error is None
    assert "1499" in output


def test_retry_tool_self_corrects_sql_syntax_error():
    """A sql_query with a SQL syntax error (missing quotes around a
    string literal) must be self-corrected and re-executed successfully."""
    output, error = _retry_tool(
        "appliances",
        "washing_machines",
        "sql_query",
        "SELECT price_aud FROM specifications WHERE model = WM-900",
        'near "-": syntax error',
    )
    assert error is None
    assert "1499" in output
