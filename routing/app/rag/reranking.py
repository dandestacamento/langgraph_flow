"""Reranking: optional refinement of `retrieval.py` results, used once
Retrieval Recall@K measurements (Level 4+) show the raw vector search
ordering needs improvement.
"""

from __future__ import annotations


def rerank(query: str, passages: list[dict]) -> list[dict]:
    raise NotImplementedError(
        "Reranking is implemented starting at Level 4, once baseline "
        "Retrieval Recall@K results justify adding it (see "
        "instructions/Langgraph_routing/6_routing_design.md)."
    )
