"""Tools for querying mock warehouse inventory (data/inventory.json)."""

from __future__ import annotations

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_INVENTORY_CACHE: list[dict] | None = None


class InventoryAPIError(RuntimeError):
    """Simulates the mock inventory API being transiently unreachable
    (use case 9: "The inventory API is not responding.")."""


def _load_inventory() -> list[dict]:
    global _INVENTORY_CACHE
    if _INVENTORY_CACHE is None:
        with open(DATA_DIR / "inventory.json", encoding="utf-8") as f:
            _INVENTORY_CACHE = json.load(f)
    return _INVENTORY_CACHE


def _call_inventory_api(product_id: str) -> int:
    """The underlying (mocked) external inventory lookup."""
    return sum(item["quantity"] for item in _load_inventory() if item["product_id"] == product_id)


def check_stock(product_id: str, max_retries: int = 2, _fail_times: int = 0) -> dict:
    """Check stock with retry/fallback (use case 9: error handling and
    retry/fallback). `_fail_times` is a test-only hook - the caller can
    force this many simulated `InventoryAPIError`s before the call
    succeeds, so the retry path is exercisable deterministically in tests
    without ever being flaky in the live app (where it defaults to 0, i.e.
    the mocked API never actually fails).

    Returns a dict rather than raising, so callers always have something
    to show the customer even if every retry is exhausted:
        {"quantity": int | None, "attempts": [...], "degraded": bool}
    """
    attempts: list[dict] = []
    for attempt in range(1, max_retries + 2):  # 1 initial try + max_retries retries
        try:
            if attempt <= _fail_times:
                raise InventoryAPIError(f"Inventory API temporarily unavailable for {product_id}")
            quantity = _call_inventory_api(product_id)
            attempts.append({"attempt": attempt, "success": True})
            return {"quantity": quantity, "attempts": attempts, "degraded": False}
        except InventoryAPIError as exc:
            attempts.append({"attempt": attempt, "success": False, "error": str(exc)})
            time.sleep(0.05)  # brief backoff before retrying

    return {"quantity": None, "attempts": attempts, "degraded": True}

