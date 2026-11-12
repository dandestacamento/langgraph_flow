"""Orders Agent: answers order-status and delivery questions.

Phase 2 feature (use case 5, "Where is my delivery?"): demonstrates an
external tool/API call via `tools.order_tools.get_delivery_status`, which
simulates a request to a carrier/logistics API. Also benefits from Phase 2
conversation memory - if the customer already mentioned their order number
earlier in the chat, `state["order_id"]` is already populated by
`graph.workflow.extract_context` and doesn't need to be repeated.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from graph.state import CSRState
from tools.order_tools import extract_order_id, get_delivery_status

SYSTEM_PROMPT = """You are the Orders specialist for SmartHome Appliances, an Australian \
retailer. Use the delivery-tracking result below to tell the customer clearly where their \
order is and when to expect it. If it's already delivered, say so. If no order number is \
available, politely ask the customer for their order number. Be concise."""


def orders_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]
    order_id = state.get("order_id") or extract_order_id(message)

    if order_id is None:
        context = "No order number was provided or found in the message."
    else:
        context = f"Order {order_id} delivery tracking: {get_delivery_status(order_id)}"

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        [("system", SYSTEM_PROMPT), ("human", f"Customer message: {message}\n\n{context}")]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {"orders": response.content},
        "execution_log": [
            {
                "node": "orders_agent",
                "action": "get_delivery_status",
                "tool_result": context,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
