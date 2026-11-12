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
concisely and factually. Mention price in AUD and stock availability. If nothing matches, say so."""


def product_agent(state: CSRState) -> dict:
    start = time.perf_counter()
    message = state["customer_message"]

    matches = search_products(message)
    lines = [
        f"- {p['product_id']}: {p['brand']} {p['model']} ({p['category']}): ${p['price']:.2f} AUD, "
        f"{check_stock(p['product_id'])} in stock"
        for p in matches
    ]
    context = "\n".join(lines) if lines else "No matching products found in catalog."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", f"Customer message: {message}\n\nSearch results:\n{context}"),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {"product": response.content},
        "execution_log": [
            {
                "node": "product_agent",
                "action": "search_products",
                "tool_result": context,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
