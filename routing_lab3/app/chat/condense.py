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

from app import llm_gateway
from app.chat.state import ChatTurn
from app.config import AGENT_MODEL

_CONDENSE_SYSTEM_PROMPT = """You are rewriting a user's latest chat message into a fully \
self-contained question, using the conversation history below for context. The rewritten \
question must be understandable completely on its own, with no reference to "it", "that", "the \
first one", "instead", etc. - resolve every such reference to the specific entity/topic/model the \
conversation history actually established.

If the latest message is already self-contained (doesn't depend on any prior turn to understand), \
return it unchanged. Do not answer the question yourself - only rewrite it. Do not add facts that \
aren't already implied by the conversation history or the latest message itself.

Also classify the latest message: set is_conversation_meta to true ONLY when the message asks \
about the conversation itself (e.g. "what was my previous question?", "summarize our \
conversation", "what did you just say?") rather than asking for information about appliances. A \
follow-up appliance question that merely *references* the conversation (e.g. "how do I fix that \
error?") is NOT conversation-meta - it should be rewritten and answered from the knowledge base."""


class CondensedQuestion(BaseModel):
    """Structured output for the condensing call."""

    self_contained_question: str = Field(
        description="The user's latest message, rewritten as a fully self-contained question "
        "that doesn't require the conversation history to understand."
    )
    is_conversation_meta: bool = Field(
        description="True only when the latest message asks about the conversation itself "
        "(previous questions/answers, a summary of the chat) rather than about appliances."
    )


def _format_history(history: list[ChatTurn]) -> str:
    if not history:
        return "(no prior turns)"
    lines = []
    for i, turn in enumerate(history, start=1):
        lines.append(f"Turn {i} - user: {turn['user_message']}")
        lines.append(f"Turn {i} - assistant: {turn['final_answer']}")
    return "\n".join(lines)


def condense_question(
    conversation_history: list[ChatTurn], latest_message: str
) -> CondensedQuestion:
    """Rewrite `latest_message` into a self-contained question, given
    `conversation_history` so far, and classify whether it's a
    conversation-meta question (about the chat itself) that should be
    answered from history rather than the knowledge base. The LLM itself
    decides (per the system prompt) whether `latest_message` already is
    self-contained, in which case it's returned unchanged - there's no
    separate heuristic/classifier deciding that ahead of time, and the
    meta classification rides on this same always-on call rather than
    adding a second one."""
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0, **llm_gateway.llm_kwargs()).with_structured_output(
        CondensedQuestion
    )
    human_message = (
        f"Conversation history:\n{_format_history(conversation_history)}\n\n"
        f"Latest message: {latest_message}"
    )
    result: CondensedQuestion = llm.invoke(
        [("system", _CONDENSE_SYSTEM_PROMPT), ("human", human_message)]
    )
    return CondensedQuestion(
        self_contained_question=result.self_contained_question.strip(),
        is_conversation_meta=result.is_conversation_meta,
    )


_HISTORY_ANSWER_SYSTEM_PROMPT = """You are answering a question about the conversation itself \
(e.g. "what was my previous question?", "summarize our conversation"), using ONLY the \
conversation history below. Answer concisely and factually from the transcript. If the history \
doesn't contain what's asked (e.g. there are no prior turns yet), say so plainly. Do not invent \
turns that didn't happen, and do not answer appliance questions here."""


def answer_from_history(conversation_history: list[ChatTurn], latest_message: str) -> str:
    """Answer a conversation-meta question directly from the transcript -
    the chat-ui-plan2.md section 3 route: conversation-history questions
    are served by conversation memory, never by knowledge-base RAG."""
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0, **llm_gateway.llm_kwargs())
    human_message = (
        f"Conversation history:\n{_format_history(conversation_history)}\n\n"
        f"Question about the conversation: {latest_message}"
    )
    result = llm.invoke([("system", _HISTORY_ANSWER_SYSTEM_PROMPT), ("human", human_message)])
    return str(result.content).strip()
