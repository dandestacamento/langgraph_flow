"""Chat-application graph (routing-lab3): wraps the existing, unmodified
single-question `app.graph.build_graph()` pipeline with conversation
memory - see instructions/learnings/routing-lab3-chat-app-plan.md
section 3.

    START -> check_input -+-> [blocked] --------------------> record_turn -> END
                           +-> [safe] -> condense -+-> [meta] -> answer_from_history -> check_output -> record_turn -> END
                                                    +-> [kb]   -> invoke_routing_pipeline -> check_output -> record_turn -> END

`condense` resolves the latest message into a self-contained question
(`app.chat.condense.condense_question`) and classifies whether it's a
question about the conversation itself; a conversation-meta turn is
answered by `answer_from_history` directly from `conversation_history`
(chat-ui-plan2.md section 3 - history questions are conversation
memory's job, never knowledge-base RAG's), while a knowledge question
goes to `invoke_routing_pipeline`, which passes the condensed question,
completely unmodified, into `app.graph.build_graph()` -
the same recursive-invocation-of-the-existing-graph pattern
`app.agents.multihop_agent.execute_multihop` already uses for its own hop
sub-questions, not a new technique; `record_turn` appends this turn to
`conversation_history`.

`check_input` / `check_output` run `app.chat.guardrails.scan_input` /
`scan_output` (instructions/learnings/routing-lab-prod-plan.md section
2.4) - a prompt-injection classifier on the raw user message, and a
secrets-leakage regex scan on the pipeline's answer, each a no-op unless
`ROUTING_LAB_GUARDRAILS_ENABLED=1`. A blocked input skips condense and
the routing pipeline entirely (never spends an LLM call on a rejected
message); a blocked output replaces `final_answer` with a safe fallback
before it's returned to the caller or persisted to
`conversation_history`.

Give `build_chat_graph()` a checkpointer (e.g. `InMemorySaver()`, the same
choice `smarthome-csr/app.py` makes) and invoke it with a stable
`thread_id` per conversation - only `user_message` needs to be passed on
each call; `conversation_history` is restored from the checkpoint
automatically.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.chat.condense import answer_from_history as answer_meta_question
from app.chat.condense import condense_question
from app.chat.guardrails import scan_input, scan_output
from app.chat.state import ChatState
from app.graph import build_graph
from app.state import initial_state

PROMPT_INJECTION_REFUSAL = "I can't help with that request."
SECRET_LEAKAGE_FALLBACK = "I'm not able to share that information."


def check_input(state: ChatState) -> dict:
    result = scan_input(state["user_message"])
    if not result.blocked:
        # Explicitly reset rather than returning {}: with a checkpointer,
        # every state key persists across turns, so a blocked reason left
        # over from a *previous* turn would otherwise short-circuit this
        # safe one straight to record_turn (and mislabel its response).
        return {"guardrail_blocked_reason": None}
    return {
        "guardrail_blocked_reason": result.reason,
        "self_contained_question": state["user_message"],
        "final_answer": PROMPT_INJECTION_REFUSAL,
    }


def route_after_input_check(state: ChatState) -> str:
    return "record_turn" if state.get("guardrail_blocked_reason") else "condense"


def condense(state: ChatState) -> dict:
    result = condense_question(state.get("conversation_history", []), state["user_message"])
    return {
        "self_contained_question": result.self_contained_question,
        "is_conversation_meta": result.is_conversation_meta,
    }


def route_after_condense(state: ChatState) -> str:
    return "answer_from_history" if state.get("is_conversation_meta") else "invoke_routing_pipeline"


def answer_from_history(state: ChatState) -> dict:
    """Answers a conversation-meta question from the transcript alone.
    `routing_result` is explicitly reset (not left out): state keys
    persist across turns via the checkpointer, so without this the
    *previous* turn's routing trace would be reported as this turn's."""
    answer = answer_meta_question(state.get("conversation_history", []), state["user_message"])
    return {"final_answer": answer, "routing_result": {}}


def invoke_routing_pipeline(state: ChatState) -> dict:
    """Invokes the existing, unmodified single-question pipeline on the
    condensed question. `app.graph.build_graph()` is rebuilt per call
    (cheap - it's just graph construction, not an LLM call) rather than
    cached at module scope, to avoid any shared-state surprises between
    chat turns."""
    routing_graph = build_graph()
    result = routing_graph.invoke(initial_state(state["self_contained_question"]))
    return {"routing_result": result, "final_answer": result.get("final_answer", "")}


def check_output(state: ChatState) -> dict:
    result = scan_output(state["final_answer"])
    if not result.blocked:
        return {}
    return {
        "guardrail_blocked_reason": result.reason,
        "final_answer": SECRET_LEAKAGE_FALLBACK,
    }


def record_turn(state: ChatState) -> dict:
    turn = {
        "user_message": state["user_message"],
        "self_contained_question": state["self_contained_question"],
        "final_answer": state["final_answer"],
    }
    return {"conversation_history": [turn]}


def build_chat_graph(checkpointer=None):
    graph = StateGraph(ChatState)

    graph.add_node("check_input", check_input)
    graph.add_node("condense", condense)
    graph.add_node("answer_from_history", answer_from_history)
    graph.add_node("invoke_routing_pipeline", invoke_routing_pipeline)
    graph.add_node("check_output", check_output)
    graph.add_node("record_turn", record_turn)

    graph.add_edge(START, "check_input")
    graph.add_conditional_edges(
        "check_input",
        route_after_input_check,
        {"record_turn": "record_turn", "condense": "condense"},
    )
    graph.add_conditional_edges(
        "condense",
        route_after_condense,
        {
            "answer_from_history": "answer_from_history",
            "invoke_routing_pipeline": "invoke_routing_pipeline",
        },
    )
    graph.add_edge("answer_from_history", "check_output")
    graph.add_edge("invoke_routing_pipeline", "check_output")
    graph.add_edge("check_output", "record_turn")
    graph.add_edge("record_turn", END)

    return graph.compile(checkpointer=checkpointer)
