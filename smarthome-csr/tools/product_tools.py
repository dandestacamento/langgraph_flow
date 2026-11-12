"""Tools for querying the mock product catalog (data/products.json).

Phase 1 "basic routing" use: grounds the Product Agent's answers in actual
catalog data instead of letting the LLM hallucinate prices/availability.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_PRODUCTS_CACHE: list[dict] | None = None

CATEGORY_KEYWORDS = {
    "refrigerator": ["fridge", "refrigerator"],
    "washing_machine": ["washing machine", "washer"],
    "dryer": ["dryer"],
    "dishwasher": ["dishwasher"],
    "oven": ["oven"],
    "air_conditioner": ["air conditioner", "air con", "aircon", "ac unit"],
}


def _load_products() -> list[dict]:
    global _PRODUCTS_CACHE
    if _PRODUCTS_CACHE is None:
        with open(DATA_DIR / "products.json", encoding="utf-8") as f:
            _PRODUCTS_CACHE = json.load(f)
    return _PRODUCTS_CACHE


def get_product_by_id(product_id: str) -> dict | None:
    return next((p for p in _load_products() if p["product_id"] == product_id), None)


def _detect_category(query_lower: str) -> str | None:
    # Use word-boundary matching rather than plain substring checks: a plain
    # "washer" in query_lower would otherwise also match inside "dishwasher".
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(keyword)}\b", query_lower) for keyword in keywords):
            return category
    return None


def _detect_budget(query: str) -> float | None:
    """Pull a dollar amount out of phrases like 'under $1,500' or 'budget of 900'."""
    match = re.search(r"\$?\s?([\d,]+(?:\.\d+)?)", query)
    if match and ("$" in query or "under" in query.lower() or "budget" in query.lower()):
        return float(match.group(1).replace(",", ""))
    return None


def _detect_product_id(query: str) -> str | None:
    """Pull an explicit catalog id like 'FRIDGE-001' out of free text, if present."""
    match = re.search(r"\b[a-zA-Z]+-\d+\b", query)
    return match.group(0).upper() if match else None


def search_products(query: str) -> list[dict]:
    """Keyword + filter search over the catalog.

    If the query mentions an exact product id (e.g. "FRIDGE-001"), that
    product is looked up directly. Otherwise, detects an appliance category
    (fridge, washer, ...) and an optional budget from the free-text query,
    falling back to simple brand/model keyword matching if neither is present.
    """
    product_id = _detect_product_id(query)
    if product_id:
        product = get_product_by_id(product_id)
        return [product] if product else []

    query_lower = query.lower()
    category = _detect_category(query_lower)
    budget = _detect_budget(query)

    results = []
    for product in _load_products():
        if category and product["category"] != category:
            continue
        if budget is not None and product["price"] > budget:
            continue
        if category is None and budget is None:
            haystack = f"{product['brand']} {product['model']} {product['category']}".lower()
            words = [w for w in query_lower.split() if len(w) > 2]
            if not any(word in haystack for word in words):
                continue
        results.append(product)

    return sorted(results, key=lambda p: p["price"])
