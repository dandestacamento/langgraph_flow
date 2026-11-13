"""Architecture A - LLM Router (`6_routing_design.md`'s comparison table):
"LLM selects one topic and agent".

The simplest of the three architectures under comparison: a single LLM
call classifies the question into exactly one of the six topics (no
subtopic/chapter awareness, no multi-topic planning, no ambiguity
detection - see `app.architectures._shared` for that classifier, shared
with Architecture B), then a single grounded-answer call retrieves
passages at the *topic* level (there is no subtopic to narrow to) and
answers from them - reusing `app.agents._shared._generate_answer`, the
same answer-generation logic Architecture C's topic agents use, so only
the routing design differs between architectures, not answer quality.
"""

from __future__ import annotations

import time

from app.agents._shared import _generate_answer
from app.architectures._shared import classify_topic_only
from app.rag.retrieval import retrieve
from app.state import RoutingState


def answer_directly(state: RoutingState) -> dict:
    """Node 2: retrieve at the topic level (no subtopic narrowing - there
    is no subtopic stage in this architecture) and answer directly. This
    is Architecture A's entire answer stage - no tool selection, no
    multi-topic merge, no recovery retry."""
    topic = state["selected_topics"][0]
    question = state["question"]

    start = time.perf_counter()
    passages = retrieve(question, topic=topic, subtopic=None)
    retrieval_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    answer, is_insufficient = _generate_answer(topic, question, passages, tool_result=None)
    generation_ms = (time.perf_counter() - start) * 1000

    return {
        "retrieved_passages": {topic: passages},
        "agent_responses": {topic: answer},
        "final_answer": answer,
        "execution_log": [
            {
                "node": "arch_a_retriever",
                "action": "retrieve_topic_level",
                "output": {"retrieved_chapters": [p["chapter_id"] for p in passages]},
                "duration_ms": round(retrieval_ms, 1),
            },
            {
                "node": "arch_a_agent",
                "action": "answer_directly",
                "output": {"answer_preview": answer[:200], "insufficient_info": is_insufficient},
                "duration_ms": round(generation_ms, 1),
            },
        ],
    }


def build_arch_a_graph():
    """START -> arch_a_topic_router -> arch_a_agent -> END. Two nodes
    total - the minimum needed to answer a question at all."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(RoutingState)
    graph.add_node("arch_a_topic_router", classify_topic_only("arch_a_topic_router"))
    graph.add_node("arch_a_agent", answer_directly)
    graph.add_edge(START, "arch_a_topic_router")
    graph.add_edge("arch_a_topic_router", "arch_a_agent")
    graph.add_edge("arch_a_agent", END)
    return graph.compile()
