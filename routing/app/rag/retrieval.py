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
"""

from __future__ import annotations

import time
from functools import lru_cache

from langchain_chroma import Chroma

from app.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, RETRIEVAL_TOP_K
from app.rag.embeddings import get_embeddings_client
from app.state import RoutingState


@lru_cache(maxsize=1)
def get_vector_store() -> Chroma:
    return Chroma(
        collection_name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embeddings_client(),
        persist_directory=str(CHROMA_PERSIST_DIR),
    )


def retrieve(
    query: str,
    topic: str,
    subtopic: str | None = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> list[dict]:
    """Retrieve the top_k most similar chunks for `query`, filtered to the
    given topic (and subtopic, if provided). Returns a list of dicts with
    `text`, `chapter_id`, `document_id`, `topic`, `subtopic`, `chunk_index`,
    and `score` (Chroma's L2 distance - lower is more similar), ordered by
    similarity."""
    where = {"topic": topic} if subtopic is None else {
        "$and": [{"topic": topic}, {"subtopic": subtopic}]
    }
    store = get_vector_store()
    results = store.similarity_search_with_score(query, k=top_k, filter=where)

    return [
        {
            **document.metadata,
            "text": document.page_content,
            "score": score,
        }
        for document, score in results
    ]


def retrieve_evidence(state: RoutingState) -> dict:
    """RAG Retriever graph node: for each selected topic, retrieve the
    top-k passages from that topic's chosen subtopic and record them in
    `retrieved_passages`, keyed by topic - same per-topic-loop pattern as
    `subtopic_router.classify_subtopic` and `chapter_selector.select_chapter`."""
    retrieved_passages: dict = {}
    log_entries: list[dict] = []

    for topic in state["selected_topics"]:
        subtopic = state["selected_subtopics"].get(topic)
        start = time.perf_counter()
        passages = retrieve(state["question"], topic=topic, subtopic=subtopic)
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
