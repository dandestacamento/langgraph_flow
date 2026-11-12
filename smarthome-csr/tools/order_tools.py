"""Tools for looking up mock customer orders (data/orders.json)."""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_ORDERS_CACHE: list[dict] | None = None

ORDER_ID_PATTERN = re.compile(r"ORD-\d+", re.IGNORECASE)


def _load_orders() -> list[dict]:
    global _ORDERS_CACHE
    if _ORDERS_CACHE is None:
        with open(DATA_DIR / "orders.json", encoding="utf-8") as f:
            _ORDERS_CACHE = json.load(f)
    return _ORDERS_CACHE


def extract_order_id(text: str) -> str | None:
    """Pull an order id like 'ORD-1045' out of free text, if present."""
    match = ORDER_ID_PATTERN.search(text)
    return match.group(0).upper() if match else None


def get_order(order_id: str) -> dict | None:
    return next((o for o in _load_orders() if o["order_id"] == order_id), None)


def get_delivery_status(order_id: str, today: date | None = None) -> dict:
    """Simulate a call to an external carrier/delivery-tracking API.

    Use case 5 ("Where is my delivery?") is explicitly about demonstrating
    external tool/API execution, so this adds a small artificial latency
    the way `basic_search1/openai_agent.py`'s mocked `search` tool does.
    """
    time.sleep(0.1)  # simulate network latency to a carrier API

    today = today or date.today()
    order = get_order(order_id)
    if order is None:
        return {"found": False, "message": f"No order found with id {order_id}."}

    order_date = datetime.strptime(order["order_date"], "%Y-%m-%d").date()
    days_since_order = (today - order_date).days

    return {
        "found": True,
        "delivery_status": order["delivery_status"],
        "delivery_date": order["delivery_date"],
        "days_since_order": days_since_order,
    }

