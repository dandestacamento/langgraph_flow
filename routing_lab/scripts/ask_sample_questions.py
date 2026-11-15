"""Runs a fixed set of sample questions (simple -> complex, one per
Level 1-10 mechanism) through the full graph with MLflow tracing and the
LLM/embedding response cache both active, so each run is fully traced and
cheap to re-run.

Usage:
    python scripts/ask_sample_questions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.cache import enable_llm_cache  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.observability.mlflow_tracing import enable_mlflow_tracing_if_available  # noqa: E402
from app.state import initial_state  # noqa: E402

# One question per level, simple -> complex, each reusing an existing
# ground-truth question (see datasets/routing_ground_truth.jsonl) so
# there's an established expected answer/behavior to check against.
SAMPLE_QUESTIONS = [
    ("Level 1 - simple topic routing", "What is a Python decorator?"),
    ("Level 2 - subtopic routing", "What's the difference between a VNet and a subnet in Azure?"),
    ("Level 3 - chapter routing", "What does the spark.sql.shuffle.partitions setting default to?"),
    (
        "Level 4 - RAG retrieval + insufficient-info handling",
        "What is the maximum amperage draw of the RF-900 refrigerator's compressor?",
    ),
    ("Level 5 - ambiguous question (clarification)", "Is it covered?"),
    (
        "Level 6 - multi-chapter evidence (one topic)",
        "What does E21 mean on the WM-500, and what is its standard warranty term?",
    ),
    (
        "Level 7 - multi-topic (parallel agents)",
        "My WM-500 is showing error E21 - is that covered under warranty, and what's "
        "SmartHome's standard refund policy?",
    ),
    ("Level 8 - tool selection and execution", "What's the price of the WM-900 washing machine?"),
    (
        "Level 9 - complex multi-hop reasoning",
        "Which washing machine model has the largest capacity, and what's its price?",
    ),
    ("Level 10 - error recovery and fallback", "Does SmartHome offer same-day delivery?"),
]


def main() -> None:
    if enable_llm_cache():
        print("(LLM/embedding response cache active)")
    if enable_mlflow_tracing_if_available():
        print("(MLflow tracing active - see http://127.0.0.1:5000)")
    else:
        print("(MLflow NOT reachable - these runs will not be traced; run start_mlflow.ps1 first)")

    graph = build_graph()
    for i, (label, question) in enumerate(SAMPLE_QUESTIONS, start=1):
        print(f"\n[{i}/10] {label}")
        print(f"  Q: {question}")
        result = graph.invoke(initial_state(question))
        print(f"  Topics: {result['selected_topics']}")
        print(f"  A: {result['final_answer'][:150]}")


if __name__ == "__main__":
    main()
