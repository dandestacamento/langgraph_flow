"""CLI entry point: run a single question through the routing graph and
print the selected topic(s), the final answer, and the execution trace.

Usage:
    python -m app.main "What is a Python decorator?"
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from app.graph import build_graph
from app.observability.mlflow_tracing import enable_mlflow_tracing_if_available
from app.state import initial_state


def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2:
        print('Usage: python -m app.main "<question>"')
        raise SystemExit(1)
    question = " ".join(sys.argv[1:])

    if enable_mlflow_tracing_if_available():
        print("(MLflow tracing active - see http://127.0.0.1:5000)")

    graph = build_graph()
    result = graph.invoke(initial_state(question))

    print(f"\nQuestion: {question}")
    print(f"Selected topic(s): {result['selected_topics']}")
    print(f"\nFinal answer:\n{result['final_answer']}")
    print("\nExecution trace:")
    for entry in result["execution_log"]:
        print(f"  - {entry['node']}: {entry['action']} ({entry['duration_ms']} ms)")


if __name__ == "__main__":
    main()
