from pathlib import Path

import pytest

from scripts.run_batch_tests import build_detail, render_markdown_report, score_case


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
