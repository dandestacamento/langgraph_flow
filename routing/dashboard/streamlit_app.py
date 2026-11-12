"""Streamlit dashboard for the Routing Accuracy Lab.

Shows: MLflow tracing status, the compiled graph's structure, a free-form
question tester (selected topic(s), final answer, execution trace), and a
Level 1 routing-accuracy report run against
`datasets/routing_ground_truth.jsonl`.

Later levels will add: subtopic/chapter selection, retrieved
passages/citations, tool calls, and routing/retrieval/answer evaluation
results per instructions/Langgraph_routing/4_to_5_obserability.md - this
first version only has Level 1 data to show.

Run with:
    streamlit run dashboard/streamlit_app.py
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.evaluation.routing_metrics import RoutingResult, summarize  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.observability.graph_visualizer import render_graph_diagram  # noqa: E402
from app.observability.mlflow_tracing import (  # noqa: E402
    DEFAULT_TRACKING_URI,
    enable_mlflow_tracing_if_available,
)
from scripts.run_evaluations import load_ground_truth  # noqa: E402

st.set_page_config(page_title="LangGraph Routing Accuracy Lab", layout="wide")


@st.cache_resource
def get_graph():
    return build_graph()


@st.cache_resource
def get_mlflow_status() -> bool:
    return enable_mlflow_tracing_if_available()


@st.cache_resource
def get_graph_diagram():
    return render_graph_diagram(get_graph())


st.title("🧭 LangGraph Routing Accuracy Lab")
title_col, status_col = st.columns([4, 1])
title_col.caption(
    "Test, visualize, and measure routing accuracy across topics, subtopics, chapters, and agents."
)
if get_mlflow_status():
    status_col.caption(f"🟢 MLflow tracing active ({DEFAULT_TRACKING_URI})")
else:
    status_col.caption("⚪ MLflow not running (see start_mlflow.ps1)")

with st.expander("🗺️ Graph visualization"):
    png_bytes, mermaid_source = get_graph_diagram()
    if png_bytes:
        st.image(png_bytes, caption="Routing Accuracy Lab graph (Level 1)")
    else:
        st.warning("Couldn't reach the Mermaid render service - showing diagram source instead.")
        st.code(mermaid_source, language="text")

st.divider()

ask_tab, eval_tab = st.tabs(["🔍 Ask a question", "📊 Level 1 evaluation"])

with ask_tab:
    question = st.text_input("Question", placeholder="e.g. What is a Python decorator?")
    if st.button("Run", type="primary") and question:
        with st.spinner("Routing..."):
            result = get_graph().invoke(
                {
                    "question": question,
                    "agent_responses": {},
                    "subtopic_decisions": {},
                    "selected_subtopics": {},
                    "execution_log": [],
                }
            )
        st.subheader("Selected topic(s)")
        st.write(result["selected_topics"])
        st.subheader("Final answer")
        st.write(result["final_answer"])
        st.subheader("Execution trace")
        st.table(
            [
                {
                    "node": e["node"],
                    "action": e["action"],
                    "duration_ms": e["duration_ms"],
                }
                for e in result["execution_log"]
            ]
        )
        with st.expander("Raw router decisions"):
            st.json(
                {
                    "complexity_decision": result.get("complexity_decision"),
                    "topic_decision": result.get("topic_decision"),
                }
            )

with eval_tab:
    st.caption(
        "Runs every Level 1 (simple topic routing) question from "
        "datasets/routing_ground_truth.jsonl through the graph and scores the "
        "Topic Router's output against the expected topic - deterministic "
        "set-equality, not an LLM judge."
    )
    if st.button("Run Level 1 evaluation"):
        cases = load_ground_truth(level=1)
        graph = get_graph()
        progress = st.progress(0, text="Running...")
        rows = []
        results = []
        for i, case in enumerate(cases):
            output = graph.invoke(
                {
                    "question": case["question"],
                    "agent_responses": {},
                    "subtopic_decisions": {},
                    "selected_subtopics": {},
                    "execution_log": [],
                }
            )
            result = RoutingResult(
                question_id=case["id"],
                expected_topics=case["expected_topics"],
                actual_topics=output["selected_topics"],
            )
            results.append(result)
            rows.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "expected": case["expected_topics"],
                    "actual": output["selected_topics"],
                    "correct": "✅" if result.is_correct else "❌",
                }
            )
            progress.progress((i + 1) / len(cases), text=f"{i + 1}/{len(cases)}")

        summary = summarize(results)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Topic accuracy", f"{summary['topic_accuracy']:.0%}")
        m2.metric("Precision", f"{summary['precision']:.0%}")
        m3.metric("Recall", f"{summary['recall']:.0%}")
        m4.metric("Correct / Total", f"{summary['correct']}/{summary['total']}")
        st.dataframe(rows, use_container_width=True)
