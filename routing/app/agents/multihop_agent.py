"""Multi-Hop Agent (Level 9 - complex multi-hop reasoning): executes a
genuine multi-hop question's two-hop plan (`state["hop_plan"]`, produced
by `app.routers.multihop_router.classify_multihop`) and produces the
final answer, bypassing the rest of the normal single-pass pipeline
entirely (similar to how `clarification_agent` bypasses it for an
ambiguous question).

Each hop is resolved by recursively invoking `app.graph.build_graph()` on
that hop's own self-contained question text - reusing the ENTIRE existing
single-question pipeline (topic/subtopic/chapter routing, RAG retrieval,
tool selection, topic agent) unchanged, rather than duplicating any of
that logic here. `build_graph` is imported inside the function body
(not at module level) specifically to avoid a circular import: this
module is itself wired into the graph `build_graph()` constructs.

Between hops, a small structured-output LLM call extracts the specific
short value hop 1's answer actually identified (e.g. "WM-900", not the
whole sentence it appears in), which is substituted into hop 2's
`{hop1_answer}` placeholder before hop 2 is resolved.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import AGENT_MODEL
from app.state import RoutingState, initial_state

_EXTRACT_SYSTEM_PROMPT = """You are extracting a value from a sub-question's answer, to use as \
input to a different, follow-up question. Given the sub-question and its answer below, output \
ONLY the specific short value (a model name, code, or number) that answers the sub-question - \
not a full sentence, not units or extra words, just the value itself (e.g. "WM-900", "E21", "7")."""

_SYNTHESIS_SYSTEM_PROMPT = """You are the Multi-Hop Synthesis step. You are given two sequential \
sub-questions and their answers, where the second sub-question depended on the first's answer. \
Combine them into ONE clear, well-organized answer to the original question. Preserve every fact \
and citation from both answers - do not drop or alter any of them. Do not add any new information \
beyond what the two answers already say. Each answer below is introduced by a '--- HOP N: ... ---' \
header - this header is NOT a citation and must never appear in your own Sources line; only copy \
the real chapter_id/tool values that already appear after each hop's own 'Sources:' line. End your \
answer with a single merged 'Sources: ' line listing every one of those values, without duplicates."""


class ExtractedValue(BaseModel):
    """Structured output for the between-hops extraction call."""

    extracted_value: str = Field(description="The short value extracted from the hop's answer.")


def _extract_value(hop_question: str, hop_answer: str) -> str:
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0).with_structured_output(ExtractedValue)
    result: ExtractedValue = llm.invoke(
        [
            ("system", _EXTRACT_SYSTEM_PROMPT),
            ("human", f"Sub-question: {hop_question}\n\nAnswer: {hop_answer}"),
        ]
    )
    return result.extracted_value.strip()


def execute_multihop(state: RoutingState) -> dict:
    """Resolve a multi-hop question's two-hop plan and produce the final,
    synthesized answer."""
    from app.graph import build_graph  # local import: avoids a circular import with app.graph

    start = time.perf_counter()
    hop_plan = state["hop_plan"]
    graph = build_graph()
    log_entries: list[dict] = []

    hop1_question = hop_plan["hop1_question"]
    hop1_state = graph.invoke(initial_state(hop1_question, is_hop_subquestion=True))
    hop1_answer = hop1_state["final_answer"]
    hop1_extracted = _extract_value(hop1_question, hop1_answer)
    hop1_result = {
        "hop_number": 1,
        "question": hop1_question,
        "final_answer": hop1_answer,
        "extracted_value": hop1_extracted,
    }
    log_entries.append(
        {
            "node": "multihop_agent",
            "action": "execute_hop[1]",
            "output": hop1_result,
            "duration_ms": 0.0,
        }
    )

    hop2_question = hop_plan["hop2_question_template"].replace("{hop1_answer}", hop1_extracted)
    hop2_state = graph.invoke(initial_state(hop2_question, is_hop_subquestion=True))
    hop2_answer = hop2_state["final_answer"]
    hop2_result = {
        "hop_number": 2,
        "question": hop2_question,
        "final_answer": hop2_answer,
        "extracted_value": None,
    }
    log_entries.append(
        {
            "node": "multihop_agent",
            "action": "execute_hop[2]",
            "output": hop2_result,
            "duration_ms": 0.0,
        }
    )

    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    human_message = (
        f"Original question: {state['question']}\n\n"
        f"--- HOP 1: {hop1_question} ---\n{hop1_answer}\n\n"
        f"--- HOP 2: {hop2_question} ---\n{hop2_answer}"
    )
    response = llm.invoke([("system", _SYNTHESIS_SYSTEM_PROMPT), ("human", human_message)])
    final_answer = response.content.strip()
    duration_ms = (time.perf_counter() - start) * 1000

    log_entries.append(
        {
            "node": "multihop_agent",
            "action": "synthesize_hops",
            "output": {"hops_combined": 2},
            "duration_ms": round(duration_ms, 1),
        }
    )

    return {
        "hop_results": [hop1_result, hop2_result],
        "final_answer": final_answer,
        "execution_log": log_entries,
    }
