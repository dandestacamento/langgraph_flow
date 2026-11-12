"""Technical Support Agent: provides first-line troubleshooting steps for a
reported fault.

Phase 1 gives a single diagnostic pass. Phase 2 ("Tools and state") will
turn this into a looping conversation that asks clarifying questions before
giving a final diagnosis (see instructions/SmartHome_Appliances/9_dev_phase.md).
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from graph.state import CSRState

SYSTEM_PROMPT = """You are the Technical Support specialist for SmartHome Appliances. Given a \
customer's fault description, suggest the most likely cause and 2-3 concrete troubleshooting \
steps a CSR can relay to the customer. Be concise and practical. If the fault sounds serious \
(e.g. mechanical failure, safety risk), recommend a technician visit or replacement assessment."""


def technical_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke([("system", SYSTEM_PROMPT), ("human", message)])
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {"technical": response.content},
        "execution_log": [
            {
                "node": "technical_agent",
                "action": "diagnose_fault",
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
