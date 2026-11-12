"""Tools for querying mock warehouse inventory (data/inventory.json)."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_INVENTORY_CACHE: list[dict] | None = None


def _load_inventory() -> list[dict]:
    global _INVENTORY_CACHE
    if _INVENTORY_CACHE is None:
        with open(DATA_DIR / "inventory.json", encoding="utf-8") as f:
            _INVENTORY_CACHE = json.load(f)
    return _INVENTORY_CACHE


def check_stock(product_id: str) -> int:
    """Return total quantity across all warehouses for a product_id (0 if unknown)."""
    return sum(item["quantity"] for item in _load_inventory() if item["product_id"] == product_id)
