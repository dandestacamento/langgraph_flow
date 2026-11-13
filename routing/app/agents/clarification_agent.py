"""Clarification Agent: Level 5 (ambiguous questions).

Runs instead of the normal subtopic/chapter/retrieval/answer pipeline when
`topic_router.classify_topic` flags a question as `is_ambiguous`. Rather
than guessing a topic/subtopic and potentially retrieving (and grounding
an answer in) the wrong knowledge base - which Level 4's insufficient-info
handling can't catch, since the retrieved passages would just be *plausible
but wrong*, not obviously irrelevant - this asks the user a short,
specific clarifying question instead.

This is a terminal node: the graph routes straight from here to END,
bypassing `synthesis_agent` entirely (see `app/graph.py`), since there is
no `agent_responses` entry to synthesize and `synthesize()` would
otherwise overwrite `final_answer` with an empty string.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from app.config import AGENT_MODEL
from app.state import RoutingState

CLARIFICATION_SYSTEM_PROMPT = """You are the Clarification Agent for a routing accuracy test lab. \
The Topic Router could not confidently route the user's question because it is missing \
information needed to answer it (e.g. no product/model, order, or error code, or a vague \
unresolved reference like "it"/"this").

Write ONE short, specific clarifying question that would resolve the ambiguity. Do not attempt to \
answer the original question, apologize, or explain why it's ambiguous - just ask the question a \
helpful support agent would actually ask back."""


def ask_for_clarification(state: RoutingState) -> dict:
    """Terminal node: generate a clarifying question instead of guessing
    an answer, recording it directly as `final_answer`."""
    start = time.perf_counter()
    topic_decision = state["topic_decision"]

    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    human = (
        f"Original question: {state['question']}\n"
        f"Best-guess topic(s): {', '.join(topic_decision['topics'])}\n"
        f"Router's reasoning: {topic_decision['reasoning']}"
    )
    response = llm.invoke(
        [
            ("system", CLARIFICATION_SYSTEM_PROMPT),
            ("human", human),
        ]
    )
    clarifying_question = response.content.strip()
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "final_answer": clarifying_question,
        "execution_log": [
            {
                "node": "clarification_agent",
                "action": "ask_for_clarification",
                "output": {"clarifying_question": clarifying_question},
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
