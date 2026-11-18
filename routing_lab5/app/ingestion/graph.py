"""The ingestion LangGraph workflow (chat-ui-plan5.md §1/§4) - a separate
graph from the question-answering one, by design: uploading knowledge
must never interrupt active conversations, and the QA graph stays
untouched (the same wrap-don't-touch rule every chat feature followed).

    START -> validate -> extract -> classify -+-> [usable] -> chunk -> index -> validate_retrieval -+-> [found] -> publish -> END
                 |            |                +-> [review/invalid] -> park (needs_review) -> END     +-> [missing] -> rollback (failed) -> END
                 +-> [bad] ---+--> fail -> END

Every node records a timed event in the DocumentRegistry - the raw
material for the later Ingestion Inspector - and every terminal node
leaves the registry row in exactly one of: indexed / needs_review /
failed.

Chunks are indexed into the SAME Chroma collection the curated knowledge
base uses, with the same metadata keys the retriever filters on
(topic/subtopic) plus provenance (document_id, source filename, version,
ingested=True) - so retrieval, citations, and the existing router work on
ingested knowledge with zero changes.

Known caveats, deliberate for Phase A:
- `scripts/build_index.py --rebuild` wipes the whole collection and
  reindexes only the curated knowledge base - ingested documents must be
  re-published afterwards (a `reindex` admin action is Phase C work,
  tracked in chat-ui-plan5.md).
- Hybrid retrieval's BM25 index is cached per-process; newly ingested
  content appears in BM25 results only after a backend restart. The
  default "similarity" mode picks it up immediately.
"""

from __future__ import annotations

import re
import time
from typing import TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from app.api.attachments import extract_document_text
from app.ingestion.classify import classification_problem, classify_document
from app.ingestion.registry import DocumentRegistry
from app.rag.retrieval import get_vector_store

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
# Merge paragraphs up to roughly this size so an arbitrary uploaded
# document doesn't explode into hundreds of two-line chunks (the curated
# KB's chapters are short by construction; uploads aren't).
_TARGET_CHUNK_CHARS = 1200
_RETRIEVAL_TEST_CHUNKS = 3
_RETRIEVAL_TEST_TOP_K = 5


class IngestionState(TypedDict):
    document_id: str
    version: int
    filename: str
    media_type: str
    content: bytes
    extracted_text: str
    topic: str
    subtopic: str
    chapters: list[str]
    confidence: float
    chunks: list[str]
    chunk_ids: list[str]
    outcome: str  # "", "failed", "needs_review", "indexed"
    error: str


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "general"


def chunk_text(text: str) -> list[str]:
    """Paragraph-based chunking with small-paragraph merging - the same
    blank-line splitting the curated KB uses (app/rag/chunking.py), plus
    merging because uploaded documents aren't pre-shaped into short
    chapters the way generate_knowledge_base.py output is."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > _TARGET_CHUNK_CHARS:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def build_ingestion_graph(registry: DocumentRegistry):
    """Compiles the ingestion workflow bound to a DocumentRegistry (the
    API layer owns the registry instance; tests pass their own)."""

    def timed(node_name: str):
        """Wraps a node so its duration + outcome land in the registry's
        event log, and any unexpected exception becomes a clean `failed`
        state instead of a crashed background task."""

        def decorator(fn):
            def wrapper(state: IngestionState) -> dict:
                started = time.perf_counter()
                try:
                    update = fn(state)
                    detail = update.pop("_event_detail", "")
                except Exception as exc:  # noqa: BLE001 - terminal failure path
                    update = {"outcome": "failed", "error": f"{node_name}: {exc}"}
                    detail = str(exc)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                registry.append_event(state["document_id"], node_name, elapsed_ms, detail)
                return update

            return wrapper

        return decorator

    @timed("validate")
    def validate(state: IngestionState) -> dict:
        if not state["content"]:
            return {"outcome": "failed", "error": "validate: empty file"}
        return {"_event_detail": f"{len(state['content'])} bytes, {state['media_type']}"}

    @timed("extract")
    def extract(state: IngestionState) -> dict:
        text = extract_document_text(state["content"], state["media_type"])
        if not text.strip():
            return {
                "outcome": "failed",
                "error": "extract: no readable text in this document (a scanned PDF needs OCR, "
                "which this pipeline deliberately doesn't do yet)",
            }
        return {"extracted_text": text, "_event_detail": f"{len(text)} chars"}

    @timed("classify")
    def classify(state: IngestionState) -> dict:
        classification = classify_document(state["filename"], state["extracted_text"])
        problem = classification_problem(classification)
        update = {
            "topic": classification.topic,
            "subtopic": classification.subtopic,
            "chapters": classification.chapters,
            "confidence": classification.confidence,
            "_event_detail": (
                f"{classification.topic}/{classification.subtopic} "
                f"(confidence {classification.confidence:.2f})"
            ),
        }
        if problem is not None:
            update["outcome"] = "needs_review"
            update["error"] = problem
        return update

    @timed("chunk")
    def chunk(state: IngestionState) -> dict:
        chunks = chunk_text(state["extracted_text"])
        if not chunks:
            return {"outcome": "failed", "error": "chunk: no chunks produced"}
        return {"chunks": chunks, "_event_detail": f"{len(chunks)} chunks"}

    @timed("index")
    def index(state: IngestionState) -> dict:
        chapter_id = f"ingested_{_slug(state['chapters'][0] if state['chapters'] else 'general')}"
        ids = [
            f"{state['document_id']}:v{state['version']}:{i}" for i in range(len(state["chunks"]))
        ]
        documents = [
            Document(
                page_content=text,
                metadata={
                    "topic": state["topic"],
                    "subtopic": state["subtopic"],
                    "chapter_id": chapter_id,
                    "document_id": state["document_id"],
                    "chunk_index": i,
                    "source": state["filename"],
                    "version": state["version"],
                    "ingested": True,
                },
            )
            for i, text in enumerate(state["chunks"])
        ]
        get_vector_store().add_documents(documents, ids=ids)
        return {"chunk_ids": ids, "_event_detail": f"{len(ids)} chunks indexed"}

    @timed("validate_retrieval")
    def validate_retrieval(state: IngestionState) -> dict:
        """Before publishing, prove the new content is actually findable
        through the same filtered search the QA pipeline uses - plan5 §7.
        Each sampled chunk's own opening words are used as the query; the
        document must appear in the top results. Deliberately NOT an LLM
        judgment - retrieval success, not answer quality."""
        store = get_vector_store()
        where = {"$and": [{"topic": state["topic"]}, {"subtopic": state["subtopic"]}]}
        misses = []
        for chunk_text_sample in state["chunks"][:_RETRIEVAL_TEST_CHUNKS]:
            query = " ".join(chunk_text_sample.split()[:12])
            results = store.similarity_search(query, k=_RETRIEVAL_TEST_TOP_K, filter=where)
            if not any(r.metadata.get("document_id") == state["document_id"] for r in results):
                misses.append(query)
        if misses:
            # Roll back: an unfindable document must not be published.
            store.delete(ids=state["chunk_ids"])
            return {
                "outcome": "failed",
                "error": f"validate_retrieval: document not retrievable for: {misses}",
                "chunk_ids": [],
            }
        return {"_event_detail": f"{min(len(state['chunks']), _RETRIEVAL_TEST_CHUNKS)} probe queries passed"}

    @timed("publish")
    def publish(state: IngestionState) -> dict:
        return {"outcome": "indexed", "_event_detail": "published"}

    def after(fallthrough: str):
        def route(state: IngestionState) -> str:
            return "finish" if state.get("outcome") else fallthrough

        return route

    def finish(state: IngestionState) -> dict:
        return {}

    graph = StateGraph(IngestionState)
    graph.add_node("validate", validate)
    graph.add_node("extract", extract)
    graph.add_node("classify", classify)
    graph.add_node("chunk", chunk)
    graph.add_node("index", index)
    graph.add_node("validate_retrieval", validate_retrieval)
    graph.add_node("publish", publish)
    graph.add_node("finish", finish)

    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", after("extract"), {"extract": "extract", "finish": "finish"})
    graph.add_conditional_edges("extract", after("classify"), {"classify": "classify", "finish": "finish"})
    graph.add_conditional_edges("classify", after("chunk"), {"chunk": "chunk", "finish": "finish"})
    graph.add_conditional_edges("chunk", after("index"), {"index": "index", "finish": "finish"})
    graph.add_conditional_edges("index", after("validate_retrieval"), {"validate_retrieval": "validate_retrieval", "finish": "finish"})
    graph.add_conditional_edges("validate_retrieval", after("publish"), {"publish": "publish", "finish": "finish"})
    graph.add_edge("publish", "finish")
    graph.add_edge("finish", END)

    return graph.compile()


def run_ingestion(registry: DocumentRegistry, record: dict, content: bytes) -> None:
    """Executes the ingestion workflow for one uploaded document and
    writes the terminal result to the registry. Designed to run as a
    FastAPI background task - it must never raise."""
    graph = build_ingestion_graph(registry)
    initial: IngestionState = {
        "document_id": record["document_id"],
        "version": record["version"],
        "filename": record["filename"],
        "media_type": record["media_type"],
        "content": content,
        "extracted_text": "",
        "topic": "",
        "subtopic": "",
        "chapters": [],
        "confidence": 0.0,
        "chunks": [],
        "chunk_ids": [],
        "outcome": "",
        "error": "",
    }
    try:
        final = graph.invoke(initial)
    except Exception as exc:  # noqa: BLE001 - background task must not raise
        registry.update(record["document_id"], status="failed", error=f"ingestion crashed: {exc}")
        return

    registry.update(
        record["document_id"],
        status=final.get("outcome") or "failed",
        error=final.get("error") or None,
        topic=final.get("topic") or None,
        subtopic=final.get("subtopic") or None,
        chapters=final.get("chapters", []),
        classification_confidence=final.get("confidence") or None,
        chunk_count=len(final.get("chunk_ids", [])),
        chunk_ids=final.get("chunk_ids", []),
    )
