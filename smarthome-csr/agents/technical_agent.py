"""Technical Support Agent: provides first-line troubleshooting steps for a
reported fault.

Phase 2 troubleshooting loop: rather than a single diagnostic pass, this
agent checks `conversation_history` (persisted across turns via the
LangGraph checkpointer - see graph/workflow.py) for earlier visits where
the Technical agent already ran in this same conversation. If the customer
is coming back about the same issue, it escalates (technician visit /
replacement assessment) instead of repeating the same generic advice,
which is what the "loop" in use case 3 is demonstrating across turns.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from graph.state import CSRState

FIRST_PASS_PROMPT = """You are the Technical Support specialist for SmartHome Appliances. Given a \
customer's fault description, suggest the most likely cause and 2-3 concrete troubleshooting \
steps a CSR can relay to the customer. Be concise and practical. If the fault sounds serious \
(e.g. mechanical failure, safety risk), recommend a technician visit or replacement assessment."""

ESCALATION_PROMPT = """You are the Technical Support specialist for SmartHome Appliances. The \
customer has already been given troubleshooting steps for this issue in an earlier message and \
is still having the problem. Do not repeat the same generic steps - acknowledge that the basic \
troubleshooting didn't resolve it and escalate: recommend a technician visit or a replacement \
assessment. Be concise."""


def _prior_technical_visits(conversation_history: list[dict]) -> int:
    """Count how many earlier turns in this conversation already involved
    the Technical agent, to detect a repeat visit for the same fault."""
    return sum(1 for turn in conversation_history if "technical" in turn.get("agents", []))


def technical_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]
    prior_visits = _prior_technical_visits(state.get("conversation_history", []))
    is_repeat_visit = prior_visits > 0

    system_prompt = ESCALATION_PROMPT if is_repeat_visit else FIRST_PASS_PROMPT
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke([("system", system_prompt), ("human", message)])
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {"technical": response.content},
        "execution_log": [
            {
                "node": "technical_agent",
                "action": "escalate_fault" if is_repeat_visit else "diagnose_fault",
                "prior_visits": prior_visits,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
