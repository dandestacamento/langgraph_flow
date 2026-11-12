"""Retrieval accuracy metrics: Level 4 (RAG retrieval). Not yet
implemented - needs `app.rag.retrieval` and a retrieval ground-truth
dataset (`datasets/retrieval_ground_truth.jsonl`, listing expected
chapter/document IDs per question) to be meaningful.
"""

from __future__ import annotations


def retrieval_recall_at_k(results, k: int = 5) -> float:
    raise NotImplementedError(
        "Retrieval metrics are implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/4_to_5_obserability.md)."
    )
