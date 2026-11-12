"""Tools for looking up mock customer orders (data/orders.json)."""

from __future__ import annotations

import json
import re
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
