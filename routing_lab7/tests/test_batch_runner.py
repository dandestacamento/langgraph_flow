import csv
import json
import sys
from pathlib import Path

import pytest

import app.evaluation.llm_judge as judge_module
import scripts.run_batch_tests as batch_module
from app.evaluation.llm_judge import SupportJudgment, judge_answer
from scripts.run_batch_tests import (
    DATASET_PATH, build_detail, evaluate_support, load_questions, render_markdown_report, score_case,
)


@pytest.mark.parametrize("facts", [None, [], [""], ["  "], ["eco", ""]])
def test_answerable_case_without_valid_facts_is_incomplete(facts):
    case = {
        "test_id": "S000", "level": 1, "question": "What is the cycle?",
        "expected_topics": ["appliances"], "expected_facts": facts, "graded": ["topic"],
    }
    output = {"selected_topics": ["appliances"], "final_answer": "Invented answer."}

    scores = score_case(case, output)

    assert scores["routing_correct"] is True
    assert scores["answer_correct"] is None
    assert scores["overall_correct"] is None
    assert scores["answer_scoring_issue"]


def test_incomplete_answer_still_records_incorrect_routing():
    case = {
        "test_id": "S000", "question": "What is the cycle?",
        "expected_topics": ["appliances"], "expected_facts": [], "graded": ["topic"],
    }
    scores = score_case(case, {"selected_topics": ["python"], "final_answer": "Invented answer."})
    assert scores["routing_correct"] is False
    assert scores["answer_correct"] is None
    assert scores["overall_correct"] is False


def test_unanswerable_case_without_facts_still_scores_decline():
    case = {
        "test_id": "S000", "question": "Unknown?", "is_answerable": False,
        "expected_facts": [], "graded": [],
    }
    output = {"final_answer": "Insufficient information in the knowledge base to answer this question."}
    scores = score_case(case, output)
    assert scores["answer_correct"] is True
    assert scores["overall_correct"] is True


def test_report_surfaces_unscored_answer():
    case = {
        "test_id": "S000", "level": 1, "question": "What is the cycle?",
        "expected_topics": ["appliances"], "expected_facts": [], "graded": ["topic"],
    }
    output = {"selected_topics": ["appliances"], "final_answer": "Invented answer."}
    run_result = {
        "output": output, "error": None, "trace_id": None, "latency_ms": 1,
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
    }
    detail = build_detail(case, run_result, score_case(case, output))
    report = render_markdown_report([detail], Path("questions.json"), Path("results"))
    assert "**1** unscored answer(s)" in report
    assert "expected_facts" in report
    assert "**1/1** correct on all scored dimensions" not in report


def test_batch_exits_nonzero_for_unscored_answer(monkeypatch, tmp_path):
    case = {
        "test_id": "S000", "level": 1, "question": "What is the cycle?",
        "expected_topics": ["appliances"], "expected_facts": [], "graded": ["topic"],
    }
    dataset = tmp_path / "questions.json"
    dataset.write_text(json.dumps([case]), encoding="utf-8")
    output_dir = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", ["run_batch_tests.py", "--dataset", str(dataset), "--output-dir", str(output_dir)])
    monkeypatch.setattr(batch_module, "enable_llm_cache", lambda: False)
    monkeypatch.setattr(batch_module, "enable_mlflow_tracing_if_available", lambda: False)
    monkeypatch.setattr(batch_module, "build_graph", lambda: None)
    monkeypatch.setattr(batch_module, "render_graph_diagram", lambda _graph: (None, "graph"))
    monkeypatch.setattr(batch_module, "run_case", lambda _graph, _case: {
        "output": {"selected_topics": ["appliances"], "final_answer": "Invented answer."},
        "error": None, "trace_id": None, "latency_ms": 1, "total_tokens": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
    })

    with pytest.raises(SystemExit) as exc:
        batch_module.main()
    assert exc.value.code == 1
    with (output_dir / "batch_results.csv").open(encoding="utf-8", newline="") as file:
        assert "expected_facts" in next(csv.DictReader(file))["answer_scoring_issue"]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("A decorator wraps a function. functools.wraps preserves metadata.", True),
        ("A decorator wraps a function.", False),
    ],
)
def test_batch_question_answer_regression(answer, expected):
    case = load_questions(DATASET_PATH, ["T001"])[0]
    output = {"selected_topics": ["python"], "final_answer": answer}
    scores = score_case(case, output)
    assert scores["routing_correct"] is True
    assert scores["answer_correct"] is expected
    assert scores["overall_correct"] is expected


@pytest.mark.parametrize(
    ("source", "expected"), [("manual.pdf", True), ("other.pdf", False), (None, False)]
)
def test_batch_scores_expected_retrieved_source(source, expected):
    case = {
        "test_id": "S001",
        "level": 1,
        "question": "What is the cycle name?",
        "expected_topics": ["appliances"],
        "expected_source": "manual.pdf",
        "expected_facts": ["eco"],
        "graded": ["topic", "source"],
    }
    output = {
        "selected_topics": ["appliances"],
        "retrieved_passages": {
            "appliances": [{"chapter_id": "manual", "source": source, "text": "Eco cycle."}]
        },
        "final_answer": "Eco.",
    }
    scores = score_case(case, output)
    assert scores["answer_correct"] is True
    assert scores["source_correct"] is expected
    assert scores["overall_correct"] is expected


def test_report_identifies_custom_dataset_output_and_retrieved_source():
    case = {
        "test_id": "S001", "level": 1, "question": "What is the cycle name?",
        "expected_topics": ["appliances"], "expected_source": "manual.pdf",
        "expected_facts": ["eco"], "graded": ["topic", "source"],
    }
    output = {
        "selected_topics": ["appliances"],
        "retrieved_passages": {
            "appliances": [{"chapter_id": "manual", "source": "manual.pdf", "text": "Eco."}]
        },
        "final_answer": "Eco.",
    }
    run_result = {
        "output": output, "error": None, "trace_id": None, "latency_ms": 1,
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
    }
    detail = build_detail(case, run_result, score_case(case, output))
    report = render_markdown_report([detail], Path("questions.json"), Path("custom-results"))
    assert "`questions.json`" in report
    assert str(Path("custom-results") / "manual_review.csv") in report
    assert "**Retrieved sources:**" in report and "manual.pdf" in report


def test_optional_judge_reports_unsupported_claims_without_changing_scores(monkeypatch):
    class FakeModel:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            assert "manual.pdf" in messages[1][1]
            return SupportJudgment(verdict="unsupported", explanation="The warranty claim is absent.")

    monkeypatch.setattr(judge_module, "ChatOpenAI", FakeModel)
    case = {"question": "What is the warranty?", "test_id": "S1", "expected_facts": ["2 years"]}
    output = {
        "final_answer": "Warranty is 2 years.",
        "retrieved_passages": {"appliances": [{"source": "manual.pdf", "page": 2, "text": "No warranty details."}]},
    }
    scores = score_case(case, output)
    assessment = evaluate_support(case, output)
    assert scores["answer_correct"] is True
    assert assessment["verdict"] == "unsupported"
    assert "absent" in assessment["explanation"]


def test_judge_does_not_make_a_call_without_evidence(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("Model should not be called")

    monkeypatch.setattr(judge_module, "ChatOpenAI", fail)
    assert judge_answer("Question", "Answer", [])["status"] == "not_evaluated"


def test_multihop_judge_includes_both_tool_results(monkeypatch):
    captured = []
    monkeypatch.setattr(batch_module, "judge_answer", lambda question, answer, evidence: captured.extend(evidence) or {})
    evaluate_support(
        {"question": "q"},
        {"is_multi_hop": True, "final_answer": "a", "hop_results": [
            {"tool_results": {"appliances": {"tool_name": "sql_query", "output": "first", "error": None}}},
            {"tool_results": {"appliances": {"tool_name": "sql_query", "output": "second", "error": None}}},
        ]},
    )
    assert [item["text"] for item in captured] == ["first", "second"]
