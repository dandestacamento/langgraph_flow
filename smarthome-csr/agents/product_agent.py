"""Product Agent: answers questions about product availability, specs,
pricing and recommendations using the mock product/inventory data."""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from graph.state import CSRState
from tools.inventory_tools import check_stock
from tools.product_tools import search_products

SYSTEM_PROMPT = """You are the Product specialist for SmartHome Appliances, an Australian \
appliance retailer. Use the product search results below to answer the customer's question \
concisely and factually. Mention price in AUD and stock availability. If stock status is \
unavailable, say so rather than guessing a quantity. If nothing matches, say so."""


def product_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]

    matches = search_products(message)
    lines = []
    retry_events = []
    for p in matches:
        stock = check_stock(p["product_id"])
        if stock["degraded"]:
            stock_text = "stock status temporarily unavailable (inventory API unreachable)"
        else:
            stock_text = f"{stock['quantity']} in stock"
        if len(stock["attempts"]) > 1 or stock["degraded"]:
            retry_events.append({"product_id": p["product_id"], "attempts": stock["attempts"]})
        lines.append(
            f"- {p['product_id']}: {p['brand']} {p['model']} ({p['category']}): "
            f"${p['price']:.2f} AUD, {stock_text}"
        )
    context = "\n".join(lines) if lines else "No matching products found in catalog."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", f"Customer message: {message}\n\nSearch results:\n{context}"),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    log_entry = {
        "node": "product_agent",
        "action": "search_products",
        "tool_result": context,
        "duration_ms": round(duration_ms, 1),
    }
    if retry_events:
        log_entry["inventory_api_retries"] = retry_events

    return {
        "agent_responses": {"product": response.content},
        "execution_log": [log_entry],
    }

