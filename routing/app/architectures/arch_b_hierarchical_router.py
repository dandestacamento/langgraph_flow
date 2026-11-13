"""Architecture B - Hierarchical Router (`6_routing_design.md`'s
comparison table): "Topic -> subtopic -> chapter -> retrieval".

A deterministic three-stage cascade with no multi-topic planning, no
tool selection, no ambiguity detection, no multi-hop decomposition, and
no error-recovery retry. Only the topic-classification stage is new code
(`app.architectures._shared.classify_topic_only` - a single-topic-only
classifier, deliberately simpler than
`app.routers.topic_router.classify_topic`, shared with Architecture A);
the subtopic, chapter, and retrieval stages reuse
`app.routers.subtopic_router.classify_subtopic`,
`app.routers.chapter_selector.select_chapter`, and
`app.rag.retrieval.retrieve_evidence` completely unchanged - those nodes
were already "pure" per-topic classifiers with no multi-topic/ambiguity
logic baked into them, so reusing them here is both fair (same stages
the design doc describes for Architecture B) and gets the same
LLM-response cache hits Architecture C's own runs already paid for, for
any question these nodes have seen before.
"""

from __future__ import annotations

import time

from app.agents._shared import _generate_answer
from app.architectures._shared import classify_topic_only
from app.rag.retrieval import retrieve_evidence
from app.routers.chapter_selector import select_chapter
from app.routers.subtopic_router import classify_subtopic
from app.state import RoutingState


def answer_from_chapter_scoped_retrieval(state: RoutingState) -> dict:
    """Node 5 (final): answer from the passages `rag_retriever` already
    retrieved (subtopic-scoped, per `app.rag.retrieval`'s own docstring on
    why retrieval stays scoped to subtopic rather than the single
    chapter_selector guess) - no tool selection, no multi-topic merge, no
    recovery retry."""
    topic = state["selected_topics"][0]
    question = state["question"]
    passages = state["retrieved_passages"].get(topic, [])

    start = time.perf_counter()
    answer, is_insufficient = _generate_answer(topic, question, passages, tool_result=None)
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {topic: answer},
        "final_answer": answer,
        "execution_log": [
            {
                "node": "arch_b_agent",
                "action": "answer_from_chapter_scoped_retrieval",
                "output": {"answer_preview": answer[:200], "insufficient_info": is_insufficient},
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }


def build_arch_b_graph():
    """START -> arch_b_topic_router -> subtopic_router -> chapter_selector
    -> rag_retriever -> arch_b_agent -> END. The middle three nodes are
    the real `app.routers`/`app.rag` node functions, unmodified."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(RoutingState)
    graph.add_node("arch_b_topic_router", classify_topic_only("arch_b_topic_router"))
    graph.add_node("subtopic_router", classify_subtopic)
    graph.add_node("chapter_selector", select_chapter)
    graph.add_node("rag_retriever", retrieve_evidence)
    graph.add_node("arch_b_agent", answer_from_chapter_scoped_retrieval)
    graph.add_edge(START, "arch_b_topic_router")
    graph.add_edge("arch_b_topic_router", "subtopic_router")
    graph.add_edge("subtopic_router", "chapter_selector")
    graph.add_edge("chapter_selector", "rag_retriever")
    graph.add_edge("rag_retriever", "arch_b_agent")
    graph.add_edge("arch_b_agent", END)
    return graph.compile()
