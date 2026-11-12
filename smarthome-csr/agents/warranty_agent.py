"""Warranty Agent: determines whether a product purchase is still covered,
using the mock order and warranty datasets."""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from graph.state import CSRState
from tools.order_tools import extract_order_id, get_order
from tools.warranty_tools import check_warranty

SYSTEM_PROMPT = """You are the Warranty specialist for SmartHome Appliances, an Australian \
retailer. Use the warranty lookup result to tell the customer clearly whether their product is \
covered, and what their options are (repair, replacement, or refund) under Australian Consumer \
Law and the manufacturer/retailer warranty. Be concise."""


def warranty_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]
    order_id = state.get("order_id") or extract_order_id(message)

    if order_id is None:
        context = "No order number was provided or found in the message."
    else:
        order = get_order(order_id)
        if order is None:
            context = f"Order {order_id} was not found in our records."
        else:
            warranty = check_warranty(order_id)
            context = f"Order {order_id}: {order}. Warranty check: {warranty}"

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        [("system", SYSTEM_PROMPT), ("human", f"Customer message: {message}\n\n{context}")]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {"warranty": response.content},
        "execution_log": [
            {
                "node": "warranty_agent",
                "action": "check_warranty",
                "tool_result": context,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
