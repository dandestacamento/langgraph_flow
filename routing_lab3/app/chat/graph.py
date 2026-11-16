"""Chat-application graph (routing-lab3): wraps the existing, unmodified
single-question `app.graph.build_graph()` pipeline with conversation
memory - see instructions/learnings/routing-lab3-chat-app-plan.md
section 3.

    START -> condense -> invoke_routing_pipeline -> record_turn -> END

`condense` resolves the latest message into a self-contained question
(`app.chat.condense.condense_question`); `invoke_routing_pipeline` passes
that question, completely unmodified, into `app.graph.build_graph()` -
the same recursive-invocation-of-the-existing-graph pattern
`app.agents.multihop_agent.execute_multihop` already uses for its own hop
sub-questions, not a new technique; `record_turn` appends this turn to
`conversation_history`.

Give `build_chat_graph()` a checkpointer (e.g. `InMemorySaver()`, the same
choice `smarthome-csr/app.py` makes) and invoke it with a stable
`thread_id` per conversation - only `user_message` needs to be passed on
each call; `conversation_history` is restored from the checkpoint
automatically.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.chat.condense import condense_question
from app.chat.state import ChatState
from app.graph import build_graph
from app.state import initial_state


def condense(state: ChatState) -> dict:
    self_contained_question = condense_question(
        state.get("conversation_history", []), state["user_message"]
    )
    return {"self_contained_question": self_contained_question}


def invoke_routing_pipeline(state: ChatState) -> dict:
    """Invokes the existing, unmodified single-question pipeline on the
    condensed question. `app.graph.build_graph()` is rebuilt per call
    (cheap - it's just graph construction, not an LLM call) rather than
    cached at module scope, to avoid any shared-state surprises between
    chat turns."""
    routing_graph = build_graph()
    result = routing_graph.invoke(initial_state(state["self_contained_question"]))
    return {"routing_result": result, "final_answer": result.get("final_answer", "")}


def record_turn(state: ChatState) -> dict:
    turn = {
        "user_message": state["user_message"],
        "self_contained_question": state["self_contained_question"],
        "final_answer": state["final_answer"],
    }
    return {"conversation_history": [turn]}


def build_chat_graph(checkpointer=None):
    graph = StateGraph(ChatState)

    graph.add_node("condense", condense)
    graph.add_node("invoke_routing_pipeline", invoke_routing_pipeline)
    graph.add_node("record_turn", record_turn)

    graph.add_edge(START, "condense")
    graph.add_edge("condense", "invoke_routing_pipeline")
    graph.add_edge("invoke_routing_pipeline", "record_turn")
    graph.add_edge("record_turn", END)

    return graph.compile(checkpointer=checkpointer)
