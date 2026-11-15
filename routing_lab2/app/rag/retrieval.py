"""Vector retrieval.

Queries the Chroma collection built by `scripts/build_index.py`, filtered
by topic/subtopic metadata (narrowed down by `topic_router` and
`subtopic_router`), and returns passages with their source
topic/subtopic/chapter_id/document_id intact for citation.

Retrieval is deliberately scoped to (topic, subtopic) rather than the
single chapter picked by `chapter_selector` - that keeps Retrieval
Recall@K an independent measurement of the vector search itself (did it
find the right chapter among several candidates?) rather than one that's
trivially 100% whenever the Chapter Selector happens to be right, per the
five evaluation questions in
instructions/Langgraph_routing/1_architecture.md ("Routing" and
"Retrieval" are tracked as separate questions).

`retrieve()` also supports an optional "hybrid" retrieval mode (vector +
BM25 keyword search) and optional cross-encoder reranking - see
instructions/learnings/routing-lab2-learnings.md section 4 (P1). Both are
opt-in (off by default via `app.config.RETRIEVAL_MODE`/`RERANK_ENABLED`):
Level 4's baseline is already 100% Retrieval Recall@K on plain similarity
search, so there's no benchmarked evidence yet that either improves
anything here - see `scripts/compare_retrieval_modes.py` before changing
either default.
"""

from __future__ import annotations

import time
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from app.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    RERANK_ENABLED,
    RERANK_FETCH_K,
    RETRIEVAL_MODE,
    RETRIEVAL_MODES,
    RETRIEVAL_TOP_K,
)
from app.rag.embeddings import get_embeddings_client
from app.rag.reranking import rerank
from app.state import RoutingState, get_topic_question


@lru_cache(maxsize=1)
def get_vector_store() -> Chroma:
    return Chroma(
        collection_name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embeddings_client(),
        persist_directory=str(CHROMA_PERSIST_DIR),
    )


def _build_where(topic: str, subtopic: str | None) -> dict:
    return {"topic": topic} if subtopic is None else {
        "$and": [{"topic": topic}, {"subtopic": subtopic}]
    }


@lru_cache(maxsize=None)
def _bm25_retriever(topic: str, subtopic: str | None, k: int) -> BM25Retriever:
    """A BM25 keyword index scoped to exactly one (topic, subtopic) pair -
    not the whole collection, unlike a single global corpus - so hybrid
    retrieval still respects the same (topic, subtopic) scoping
    `similarity_search_with_score`'s `where` filter applies. Built from
    Chroma's own `.get(where=...)` (a supported public API), not an
    internal attribute. Cached per (topic, subtopic, k) for the process
    lifetime, same lifetime as `get_vector_store()` - restart the process
    after `scripts/build_index.py` changes the index to pick up new
    content here."""
    where = _build_where(topic, subtopic)
    raw = get_vector_store().get(where=where, include=["documents", "metadatas"])
    documents = [
        Document(page_content=text, metadata=metadata)
        for text, metadata in zip(raw["documents"], raw["metadatas"])
    ]
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = k
    return retriever


def _similarity_candidates(query: str, topic: str, subtopic: str | None, top_k: int) -> list[dict]:
    where = _build_where(topic, subtopic)
    results = get_vector_store().similarity_search_with_score(query, k=top_k, filter=where)
    return [
        {**document.metadata, "text": document.page_content, "score": score}
        for document, score in results
    ]


def _hybrid_candidates(query: str, topic: str, subtopic: str | None, top_k: int) -> list[dict]:
    """Combines dense (embedding) search with sparse (BM25 keyword)
    search via reciprocal rank fusion, so exact terms (fault codes,
    acronyms like APR/APY, model numbers) aren't missed just because
    their embedding similarity is lower than a more generic passage."""
    where = _build_where(topic, subtopic)
    vector_retriever = get_vector_store().as_retriever(search_kwargs={"k": top_k, "filter": where})
    bm25_retriever = _bm25_retriever(topic, subtopic, top_k)
    ensemble = EnsembleRetriever(retrievers=[vector_retriever, bm25_retriever], weights=[0.7, 0.3])
    documents = ensemble.invoke(query)[:top_k]

    # Reciprocal rank fusion blends two incomparable score scales (Chroma
    # L2 distance vs. BM25 term-frequency scores), so there's no single
    # meaningful "similarity" number to report here. A rank-based
    # pseudo-score keeps the same dict shape every other mode returns
    # (useful for logging/the dashboard) without claiming false precision.
    return [
        {**document.metadata, "text": document.page_content, "score": round(1.0 / (rank + 1), 4)}
        for rank, document in enumerate(documents)
    ]


def retrieve(
    query: str,
    topic: str,
    subtopic: str | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    retrieval_mode: str = RETRIEVAL_MODE,
    use_reranking: bool = RERANK_ENABLED,
) -> list[dict]:
    """Retrieve the top_k most similar chunks for `query`, filtered to the
    given topic (and subtopic, if provided). Returns a list of dicts with
    `text`, `chapter_id`, `document_id`, `topic`, `subtopic`, `chunk_index`,
    and `score`, ordered by relevance (lower Chroma L2 distance or higher
    rank-based/cross-encoder score, depending on mode - see below).

    `retrieval_mode`: "similarity" (default - Chroma vector search only)
    or "hybrid" (vector + BM25 keyword search, see `_hybrid_candidates`).
    `use_reranking`: if True, fetches a larger candidate pool
    (`max(top_k, RERANK_FETCH_K)`) and re-scores it with a cross-encoder
    (`app.rag.reranking.rerank`) before narrowing back down to `top_k`.

    Both parameters default to `app.config`'s `RETRIEVAL_MODE`/
    `RERANK_ENABLED` (both opt-in, off by default) - override them
    explicitly for experiments (see `scripts/compare_retrieval_modes.py`)
    rather than changing the config defaults without benchmarked
    evidence; see instructions/learnings/routing-lab2-learnings.md
    section 1 for why."""
    if retrieval_mode not in RETRIEVAL_MODES:
        raise ValueError(f"retrieval_mode must be one of {RETRIEVAL_MODES}, got {retrieval_mode!r}")

    fetch_k = max(top_k, RERANK_FETCH_K) if use_reranking else top_k
    candidates = (
        _hybrid_candidates(query, topic, subtopic, fetch_k)
        if retrieval_mode == "hybrid"
        else _similarity_candidates(query, topic, subtopic, fetch_k)
    )

    if use_reranking:
        return rerank(query, candidates, top_k)
    return candidates


def retrieve_evidence(state: RoutingState) -> dict:
    """RAG Retriever graph node: for each selected topic, retrieve the
    top-k passages from that topic's chosen subtopic and record them in
    `retrieved_passages`, keyed by topic - same per-topic-loop pattern as
    `subtopic_router.classify_subtopic` and `chapter_selector.select_chapter`,
    including using `get_topic_question()` (not the full multi-topic
    question) as the embedding query for a Level 7 question."""
    retrieved_passages: dict = {}
    log_entries: list[dict] = []

    for topic in state["selected_topics"]:
        subtopic = state["selected_subtopics"].get(topic)
        start = time.perf_counter()
        passages = retrieve(get_topic_question(state, topic), topic=topic, subtopic=subtopic)
        duration_ms = (time.perf_counter() - start) * 1000

        retrieved_passages[topic] = passages
        log_entries.append(
            {
                "node": "rag_retriever",
                "action": f"retrieve[{topic}/{subtopic}]",
                "output": {
                    "retrieved_chapters": [p["chapter_id"] for p in passages],
                    "scores": [round(p["score"], 4) for p in passages],
                },
                "duration_ms": round(duration_ms, 1),
            }
        )

    return {"retrieved_passages": retrieved_passages, "execution_log": log_entries}
