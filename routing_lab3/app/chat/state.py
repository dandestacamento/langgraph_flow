"""Shared state definition for the chat-application layer (routing-lab3).

Wraps the existing, unmodified single-question `app.state.RoutingState`
pipeline (`app.graph.build_graph()`) with conversation memory, per
instructions/learnings/routing-lab3-chat-app-plan.md section 3 - the
per-question routing/retrieval/tool/multi-hop pipeline is not touched by
anything here; this is a new, additive layer in front of it.

`conversation_history` follows the exact pattern already proven in this
repo's `smarthome-csr/graph/state.py` (a per-turn accumulator, not
LangGraph's stock `messages`/`add_messages`) - reused deliberately, not
reinvented, per the chat-app plan's section 2.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ChatTurn(TypedDict):
    """One recorded turn: the user's original message, the
    self-contained question `condense_question()` resolved it to (kept
    around for debugging why a follow-up was or wasn't understood
    correctly), the final answer the existing pipeline produced, and the
    trimmed routing summary behind it (app/chat/routing_summary.py) -
    persisted per turn so citations/routing details survive a page
    refresh or conversation switch instead of existing only for
    live-streamed turns (a real gap found in use: 'the citation is not
    clickable' after a reload). Turns recorded before this field existed
    simply lack the key - readers must .get() it."""

    user_message: str
    self_contained_question: str
    final_answer: str
    routing_summary: dict


class ChatState(TypedDict):
    # Input: the latest message in the conversation. Every other field
    # below is produced by a node in app/chat/graph.py.
    user_message: str

    # The condensed, self-contained question fed into the existing
    # single-question pipeline (app.graph.build_graph()) - set by
    # `condense.condense_question`, consumed by
    # `graph.invoke_routing_pipeline`.
    self_contained_question: str

    # True when `condense.condense_question` classified this turn as a
    # question about the conversation itself ("what was my previous
    # question?"), in which case `graph.answer_from_history` answers it
    # from conversation_history and the routing pipeline never runs -
    # chat-ui-plan2.md section 3's "Conversation History" route.
    is_conversation_meta: bool

    # The existing pipeline's full output state (selected_topics,
    # retrieved_passages, tool_results, execution_log, ...) for this
    # turn - kept around, not flattened into conversation_history, so a
    # future generative-UI frontend (CopilotKit, per the chat-app plan's
    # Phase 2) has the rich per-turn data to render as structured
    # components later, not just plain text.
    routing_result: dict

    # Final answer shown to the user for this turn.
    final_answer: str

    # Set by app.chat.graph.check_input / check_output
    # (app.chat.guardrails.scan_input / scan_output) when a turn was
    # blocked - "prompt_injection" (user_message rejected before
    # condense/the routing pipeline ever ran) or "secret_leakage"
    # (final_answer replaced before being returned/persisted). None
    # when guardrails are disabled (the default) or the turn passed
    # both scans - kept around for the same reason routing_result is:
    # a future UI could surface it instead of silently rewriting the
    # answer.
    guardrail_blocked_reason: str | None

    # Per-turn history for this conversation - appended to once per
    # turn via `graph.record_turn`, never overwritten. With a
    # checkpointer and a stable thread_id (see smarthome-csr/app.py for
    # the in-repo precedent), this persists across `graph.invoke()`
    # calls without the caller needing to resend it.
    conversation_history: Annotated[list[ChatTurn], operator.add]
