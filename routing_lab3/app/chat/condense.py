"""Condensing step: resolves a follow-up message into a self-contained
question, using the conversation history so far - see
instructions/learnings/routing-lab3-chat-app-plan.md section 3.1.

The existing single-question pipeline (app.graph.build_graph()) assumes
every question is self-contained - every router/retriever/agent in it is
calibrated against ground-truth rows that are all self-contained
questions. A follow-up like "is it covered under warranty?" only makes
sense given a prior turn that established which product "it" refers to,
so this step runs first and rewrites it into something the existing
pipeline can answer unmodified, e.g. "Is the WM-900's warranty valid for
this repair?" - the same small, single-purpose structured-output call
shape already used by app.agents.multihop_agent._extract_value, applied
to a new problem rather than a new kind of component.

Runs on every turn unconditionally, rather than gating behind a separate
"is this actually a follow-up?" classifier - per the chat-app plan's
section 7: a small always-on call is simpler and more robust than a
brittle gate, and critically its output is always actually consumed
downstream (unlike app.routers.complexity_router's cautionary tale of an
always-on classification whose result nothing uses - see
instructions/learnings/routing-project-learnings.md section 11, item 3).
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.chat.state import ChatTurn
from app.config import AGENT_MODEL

_CONDENSE_SYSTEM_PROMPT = """You are rewriting a user's latest chat message into a fully \
self-contained question, using the conversation history below for context. The rewritten \
question must be understandable completely on its own, with no reference to "it", "that", "the \
first one", "instead", etc. - resolve every such reference to the specific entity/topic/model the \
conversation history actually established.

If the latest message is already self-contained (doesn't depend on any prior turn to understand), \
return it unchanged. Do not answer the question yourself - only rewrite it. Do not add facts that \
aren't already implied by the conversation history or the latest message itself."""


class CondensedQuestion(BaseModel):
    """Structured output for the condensing call."""

    self_contained_question: str = Field(
        description="The user's latest message, rewritten as a fully self-contained question "
        "that doesn't require the conversation history to understand."
    )


def _format_history(history: list[ChatTurn]) -> str:
    if not history:
        return "(no prior turns)"
    lines = []
    for i, turn in enumerate(history, start=1):
        lines.append(f"Turn {i} - user: {turn['user_message']}")
        lines.append(f"Turn {i} - assistant: {turn['final_answer']}")
    return "\n".join(lines)


def condense_question(conversation_history: list[ChatTurn], latest_message: str) -> str:
    """Rewrite `latest_message` into a self-contained question, given
    `conversation_history` so far. The LLM itself decides (per the
    system prompt) whether `latest_message` already is self-contained,
    in which case it's returned unchanged - there's no separate
    heuristic/classifier deciding that ahead of time."""
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0).with_structured_output(CondensedQuestion)
    human_message = (
        f"Conversation history:\n{_format_history(conversation_history)}\n\n"
        f"Latest message: {latest_message}"
    )
    result: CondensedQuestion = llm.invoke(
        [("system", _CONDENSE_SYSTEM_PROMPT), ("human", human_message)]
    )
    return result.self_contained_question.strip()
