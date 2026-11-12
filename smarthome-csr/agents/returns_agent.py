"""Returns Agent: evaluates a refund/return/replacement request against
data/policies.json.

Phase 3 human-in-the-loop: if the order value exceeds the policy's
`requires_human_approval_above_aud` threshold, this agent sets
`pending_approval` instead of finalizing a decision. `graph.workflow` then
routes to the Approval Gate node, which pauses the graph (LangGraph
`interrupt()`) until a CSR approves or denies it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from langchain_openai import ChatOpenAI

from graph.state import CSRState
from tools.order_tools import extract_order_id, get_order
from tools.product_tools import get_product_by_id

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_POLICIES_CACHE: dict | None = None

SYSTEM_PROMPT = """You are the Returns specialist for SmartHome Appliances, an Australian \
retailer. Summarize the customer's return/refund request, referencing Australian Consumer Law \
for faulty items where relevant. If the order details below say approval is required, tell the \
customer their request has been forwarded to a supervisor and they'll hear back shortly - do not \
promise a refund or replacement yourself. If no approval is required, you may confirm the return. \
Be concise."""


def _load_policies() -> dict:
    global _POLICIES_CACHE
    if _POLICIES_CACHE is None:
        with open(DATA_DIR / "policies.json", encoding="utf-8") as f:
            _POLICIES_CACHE = json.load(f)
    return _POLICIES_CACHE


def returns_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]
    order_id = state.get("order_id") or extract_order_id(message)

    policies = _load_policies()
    approval_threshold = policies["refund_policy"]["requires_human_approval_above_aud"]

    order = get_order(order_id) if order_id else None
    amount = None
    product = None
    if order:
        item = order["items"][0]
        product = get_product_by_id(item["product_id"])
        if product:
            amount = product["price"] * item["quantity"]

    requires_approval = amount is not None and amount > approval_threshold

    if order_id is None:
        context = "No order number was provided or found in the message."
    elif order is None:
        context = f"Order {order_id} was not found in our records."
    else:
        context = (
            f"Order {order_id}: {product['brand']} {product['model']} (${amount:.2f} AUD). "
            f"Approval required above ${approval_threshold:.2f} AUD: "
            f"{'YES - this request needs supervisor approval' if requires_approval else 'no, within CSR discretion'}."
        )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        [("system", SYSTEM_PROMPT), ("human", f"Customer message: {message}\n\n{context}")]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    result: dict = {
        "agent_responses": {"returns": response.content},
        "execution_log": [
            {
                "node": "returns_agent",
                "action": "evaluate_return",
                "tool_result": context,
                "requires_approval": requires_approval,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }

    if requires_approval:
        result["pending_approval"] = {
            "agent": "returns",
            "action": "refund_or_replacement",
            "order_id": order_id,
            "amount": amount,
            "reason": f"Refund/replacement for order {order_id} ({product['brand']} {product['model']})",
        }

    return result

