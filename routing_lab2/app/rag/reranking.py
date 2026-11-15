"""Reranking: optional refinement of `retrieval.py`'s results via a
cross-encoder re-scoring pass - see
instructions/learnings/routing-lab2-learnings.md section 4 (P1).

Adapted from reference/rag_krish/rag/retrieval.py's reranking approach:
`retrieval.py` fetches a larger candidate pool than the final desired
count, then this module re-scores every candidate against the actual
query with a small, CPU-friendly cross-encoder (more accurate, but
slower, than embedding/BM25 similarity alone), and `retrieve()` narrows
back down to the top_k most relevant. Calls the cross-encoder's `.score()`
directly (rather than LangChain's `CrossEncoderReranker` compressor
wrapper) so the resulting relevance scores are preserved on each passage,
not discarded - every other retrieval mode here returns a `score` field
too, and `app.rag.retrieval.retrieve_evidence()` logs it.

Opt-in only (`use_reranking=False` by default everywhere, see
`app.config.RERANK_ENABLED`) - Level 4's baseline is already 100%
Retrieval Recall@K on plain similarity search, so there is no benchmarked
evidence yet that reranking improves anything here. Benchmark with
`scripts/compare_retrieval_modes.py` before flipping any default.

Requires the optional `sentence-transformers` dependency (pulls in torch
and downloads a ~80MB model on first use) - not needed unless
`use_reranking=True` is actually requested.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import RERANK_MODEL

try:
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

    _RERANKING_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover - optional dependency
    _RERANKING_IMPORT_ERROR = exc


@lru_cache(maxsize=1)
def _get_cross_encoder() -> "HuggingFaceCrossEncoder":
    if _RERANKING_IMPORT_ERROR is not None:
        raise ImportError(
            "Reranking requires the optional 'sentence-transformers' dependency "
            "(pip install sentence-transformers) - not installed by default since "
            "it pulls in torch and a ~80MB model download. See "
            "instructions/learnings/routing-lab2-learnings.md section 4 (P1)."
        ) from _RERANKING_IMPORT_ERROR
    return HuggingFaceCrossEncoder(model_name=RERANK_MODEL)


def rerank(query: str, passages: list[dict], top_k: int) -> list[dict]:
    """Re-score `passages` (as returned by `retrieval._similarity_candidates`/
    `_hybrid_candidates`, fetched with a larger pool than `top_k`) against
    `query` using a cross-encoder, and return the `top_k` most relevant,
    re-ordered. Each passage's `score` is replaced with the cross-encoder's
    own relevance score (higher = more relevant) - it isn't on the same
    scale as Chroma's L2 distance (lower = more similar) or the
    hybrid-mode rank-based pseudo-score, so don't compare `score` values
    across different `retrieval_mode`/`use_reranking` combinations."""
    if not passages:
        return []

    scores = _get_cross_encoder().score([(query, passage["text"]) for passage in passages])
    scored = sorted(
        (
            {**passage, "score": round(float(score), 4)}
            for passage, score in zip(passages, scores)
        ),
        key=lambda passage: passage["score"],
        reverse=True,
    )
    return scored[:top_k]
