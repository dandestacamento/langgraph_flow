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

from app.cache import CACHE_ENABLED, enable_llm_cache  # noqa: E402
from app.evaluation.routing_metrics import (  # noqa: E402
    ChapterRoutingResult,
    RoutingResult,
    SubtopicRoutingResult,
    summarize,
    summarize_chapter,
    summarize_subtopic,
)
from app.graph import build_graph  # noqa: E402
from app.observability.graph_visualizer import render_graph_diagram  # noqa: E402
from app.observability.mlflow_tracing import (  # noqa: E402
    DEFAULT_TRACKING_URI,
    enable_mlflow_tracing_if_available,
)
from app.state import initial_state  # noqa: E402
from scripts.run_evaluations import load_ground_truth  # noqa: E402

enable_llm_cache()

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
status_col.caption("💾 Response cache active (app/cache.py)" if CACHE_ENABLED else "⚪ Response cache disabled")

with st.expander("🗺️ Graph visualization"):
    png_bytes, mermaid_source = get_graph_diagram()
    if png_bytes:
        st.image(png_bytes, caption="Routing Accuracy Lab graph (Level 1)")
    else:
        st.warning("Couldn't reach the Mermaid render service - showing diagram source instead.")
        st.code(mermaid_source, language="text")

st.divider()

ask_tab, eval_tab = st.tabs(["🔍 Ask a question", "📊 Evaluation"])

with ask_tab:
    question = st.text_input("Question", placeholder="e.g. What is a Python decorator?")
    if st.button("Run", type="primary") and question:
        with st.spinner("Routing..."):
            result = get_graph().invoke(initial_state(question))
        st.subheader("Selected topic(s)")
        st.write(result["selected_topics"])
        st.subheader("Selected subtopic(s) / chapter(s)")
        st.write(
            {
                topic: {
                    "subtopic": result["selected_subtopics"].get(topic),
                    "chapter": result["selected_chapters"].get(topic),
                }
                for topic in result["selected_topics"]
            }
        )
        st.subheader("Final answer")
        st.write(result["final_answer"])
        with st.expander("Retrieved passages", expanded=False):
            for topic in result["selected_topics"]:
                st.caption(f"Topic: {topic}")
                for p in result["retrieved_passages"].get(topic, []):
                    st.markdown(f"**[{p['chapter_id']}]** (score {p['score']:.3f})")
                    st.caption(p["text"])
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
                    "subtopic_decisions": result.get("subtopic_decisions"),
                    "chapter_decisions": result.get("chapter_decisions"),
                }
            )

with eval_tab:
    level = st.selectbox(
        "Level",
        [1, 2, 3],
        format_func=lambda lv: {
            1: "Level 1 - topic routing",
            2: "Level 2 - subtopic routing",
            3: "Level 3 - chapter routing",
        }[lv],
    )
    st.caption(
        "Runs every question for the selected level from "
        "datasets/routing_ground_truth.jsonl through the graph and scores the router's "
        "output against the expected topic/subtopic/chapter - deterministic equality, "
        "not an LLM judge."
    )
    if st.button("Run evaluation"):
        cases = load_ground_truth(level=level)
        graph = get_graph()
        progress = st.progress(0, text="Running...")
        rows = []
        results = []
        for i, case in enumerate(cases):
            output = graph.invoke(initial_state(case["question"]))
            expected_topic = case["expected_topics"][0]
            actual_subtopic = output["selected_subtopics"].get(expected_topic)
            actual_chapter = output["selected_chapters"].get(expected_topic)

            if level == 1:
                result = RoutingResult(
                    question_id=case["id"],
                    expected_topics=case["expected_topics"],
                    actual_topics=output["selected_topics"],
                )
            elif level == 2:
                result = SubtopicRoutingResult(
                    question_id=case["id"],
                    expected_topic=expected_topic,
                    expected_subtopic=case["expected_subtopic"],
                    actual_topics=output["selected_topics"],
                    actual_subtopics=output["selected_subtopics"],
                )
            else:
                result = ChapterRoutingResult(
                    question_id=case["id"],
                    expected_topic=expected_topic,
                    expected_subtopic=case["expected_subtopic"],
                    expected_chapter=case["expected_chapter"],
                    actual_topics=output["selected_topics"],
                    actual_subtopics=output["selected_subtopics"],
                    actual_chapters=output["selected_chapters"],
                )
            results.append(result)
            rows.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "expected": f"{expected_topic} / {case.get('expected_subtopic', '')} / {case.get('expected_chapter', '')}",
                    "actual": f"{output['selected_topics']} / {actual_subtopic} / {actual_chapter}",
                    "correct": "✅" if result.is_correct else "❌",
                }
            )
            progress.progress((i + 1) / len(cases), text=f"{i + 1}/{len(cases)}")

        if level == 1:
            summary = summarize(results)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Topic accuracy", f"{summary['topic_accuracy']:.0%}")
            m2.metric("Precision", f"{summary['precision']:.0%}")
            m3.metric("Recall", f"{summary['recall']:.0%}")
            m4.metric("Correct / Total", f"{summary['correct']}/{summary['total']}")
        elif level == 2:
            summary = summarize_subtopic(results)
            m1, m2 = st.columns(2)
            m1.metric("Subtopic accuracy", f"{summary['subtopic_accuracy']:.0%}")
            m2.metric("Correct / Total", f"{summary['correct']}/{summary['total']}")
        else:
            summary = summarize_chapter(results)
            m1, m2 = st.columns(2)
            m1.metric("Chapter accuracy", f"{summary['chapter_accuracy']:.0%}")
            m2.metric("Correct / Total", f"{summary['correct']}/{summary['total']}")
        st.dataframe(rows, use_container_width=True)
