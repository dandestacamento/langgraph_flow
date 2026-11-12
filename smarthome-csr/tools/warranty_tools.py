"""Tools for evaluating mock warranty coverage (data/warranties.json)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_WARRANTIES_CACHE: list[dict] | None = None


def _load_warranties() -> list[dict]:
    global _WARRANTIES_CACHE
    if _WARRANTIES_CACHE is None:
        with open(DATA_DIR / "warranties.json", encoding="utf-8") as f:
            _WARRANTIES_CACHE = json.load(f)
    return _WARRANTIES_CACHE


def get_warranty_by_order(order_id: str) -> dict | None:
    return next((w for w in _load_warranties() if w["order_id"] == order_id), None)


def check_warranty(order_id: str, today: date | None = None) -> dict:
    """Return warranty coverage for an order, computed from purchase_date +
    warranty_months relative to `today` (defaults to the real current date)."""
    today = today or date.today()
    warranty = get_warranty_by_order(order_id)
    if warranty is None:
        return {"found": False, "status": "unknown", "message": "No warranty record found for this order."}

    purchase_date = datetime.strptime(warranty["purchase_date"], "%Y-%m-%d").date()
    months_elapsed = (today.year - purchase_date.year) * 12 + (today.month - purchase_date.month)
    active = months_elapsed < warranty["warranty_months"]

    return {
        "found": True,
        "status": "active" if active else "expired",
        "purchase_date": warranty["purchase_date"],
        "warranty_months": warranty["warranty_months"],
        "months_elapsed": months_elapsed,
        "coverage_notes": warranty.get("coverage_notes", ""),
    }
