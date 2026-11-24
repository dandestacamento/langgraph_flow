from pathlib import Path

import pytest

import app.evaluation.llm_judge as judge_module
import scripts.run_batch_tests as batch_module
from app.evaluation.llm_judge import SupportJudgment, judge_answer
from scripts.run_batch_tests import build_detail, evaluate_support, render_markdown_report, score_case


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
