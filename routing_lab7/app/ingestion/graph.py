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

Known caveat:
- Hybrid retrieval's BM25 index is cached per-process and refreshed
  when the registry's active document versions change. Changes to
  unregistered curated content still require a backend restart.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from pathlib import Path
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from pypdf import PdfReader

from app.cache import validate_embeddings
from app.config import UPLOAD_CHUNKING_STRATEGY
from app.ingestion.classify import classification_problem, classify_document
from app.ingestion.registry import DocumentRegistry
from app.rag.embeddings import get_embeddings_client
from app.rag.retrieval import get_vector_store, index_publication_lock

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
# Merge paragraphs up to roughly this size so an arbitrary uploaded
# document doesn't explode into hundreds of two-line chunks (the curated
# KB's chapters are short by construction; uploads aren't).
_TARGET_CHUNK_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 200
_SEMANTIC_SIMILARITY_THRESHOLD = 0.7
_SEMANTIC_BATCH_SIZE = 128
_RETRIEVAL_TEST_TOP_K = 5


class IngestionState(TypedDict):
    document_id: str
    version: int
    is_replacement: bool
    filename: str
    media_type: str
    content: bytes
    extracted_text: str
    pages: list[str]
    csv_rows: list[tuple[int, str]]
    topic: str
    subtopic: str
    chapters: list[str]
    confidence: float
    chunks: list[str]
    chunk_pages: list[int | None]
    chunk_rows: list[int | None]
    chunk_ids: list[str]
    outcome: str  # "", "failed", "needs_review", "indexed"
    error: str
    # Set when a human supplied the classification (the Knowledge Base
    # Manager's manual override, plan5 Phase B): the classify node uses
    # it verbatim instead of calling the LLM.
    manual_topic: str
    manual_subtopic: str


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "general"


def is_csv_document(filename: str, media_type: str) -> bool:
    return media_type == "text/plain" and Path(filename).suffix.lower() == ".csv"


def parse_csv_rows(content: bytes) -> list[tuple[int, str]]:
    """Parse UTF-8 CSV into individually attributable logical records."""
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    headers = next(reader, None)
    if not headers or any(not header.strip() for header in headers):
        raise ValueError("CSV requires a non-empty header for every column")
    headers = [header.strip() for header in headers]
    if len(set(headers)) != len(headers):
        raise ValueError("CSV column headers must be unique")
    rows = []
    for row_number, values in enumerate(reader, start=2):
        if not values:
            raise ValueError(f"CSV row {row_number} is blank")
        if len(values) != len(headers):
            raise ValueError(f"CSV row {row_number} has {len(values)} columns; expected {len(headers)}")
        rows.append((row_number, "\n".join(f"{header}: {value}" for header, value in zip(headers, values))))
    if not rows:
        raise ValueError("CSV must contain at least one data row")
    return rows


def chunk_text(text: str) -> list[str]:
    """Paragraph-based chunking with small-paragraph merging - the same
    blank-line splitting the curated KB uses (app/rag/chunking.py), plus
    sentence-aware splitting and overlap for oversized paragraphs."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_TARGET_CHUNK_CHARS,
        chunk_overlap=_CHUNK_OVERLAP_CHARS,
        separators=[r"(?<=[.!?])\s+", "\n", " ", ""],
        is_separator_regex=True,
    )
    paragraphs = [
        part
        for paragraph in _PARAGRAPH_SPLIT_RE.split(text)
        if paragraph.strip()
        for part in splitter.split_text(paragraph.strip())
    ]
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


def semantic_chunk_text(text: str, embeddings: Embeddings) -> list[str]:
    """Group adjacent sentences by embedding similarity, within the character limit."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_TARGET_CHUNK_CHARS,
        chunk_overlap=_CHUNK_OVERLAP_CHARS,
        separators=["\n", " ", ""],
    )
    sentences = [
        part
        for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n", text.strip())
        if sentence.strip()
        for part in splitter.split_text(sentence.strip())
    ]
    if len(sentences) < 2:
        return sentences

    chunks: list[str] = []
    current = sentences[0]
    previous: list[float] | None = None
    previous_norm = 0.0
    for start in range(0, len(sentences), _SEMANTIC_BATCH_SIZE):
        batch = sentences[start:start + _SEMANTIC_BATCH_SIZE]
        vectors = validate_embeddings(embeddings.embed_documents(batch), len(batch))
        for sentence, vector in zip(batch, vectors):
            norm = math.hypot(*vector)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("Semantic chunking requires finite, non-zero embedding norms")
            if previous is not None:
                if len(previous) != len(vector):
                    raise ValueError("Invalid embedding dimension across semantic chunking batches")
                similarity = math.fsum(
                    (left / previous_norm) * (right / norm)
                    for left, right in zip(previous, vector)
                )
                if similarity < _SEMANTIC_SIMILARITY_THRESHOLD or len(current) + len(sentence) + 1 > _TARGET_CHUNK_CHARS:
                    chunks.append(current)
                    current = sentence
                else:
                    current = f"{current} {sentence}"
            previous, previous_norm = vector, norm
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
        if is_csv_document(state["filename"], state["media_type"]):
            rows = parse_csv_rows(state["content"])
            text = "\n\n".join(row for _, row in rows)
            return {"extracted_text": text, "pages": [], "csv_rows": rows,
                    "_event_detail": f"{len(rows)} CSV rows, {len(text)} chars"}
        if state["media_type"] == "application/pdf":
            reader = PdfReader(io.BytesIO(state["content"]))
            pages = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if not text and len(page.images):
                    raise ValueError(f"page {page_number} has only images; OCR is not supported")
                pages.append(text)
        else:
            pages = [state["content"].decode("utf-8").strip()]
        text = "\n\n".join(pages).strip()
        if not text.strip():
            return {
                "outcome": "failed",
                "error": "extract: no readable text in this document (a scanned PDF needs OCR, "
                "which this pipeline deliberately doesn't do yet)",
            }
        return {"extracted_text": text, "pages": pages, "_event_detail": f"{len(text)} chars"}

    @timed("classify")
    def classify(state: IngestionState) -> dict:
        if state.get("manual_topic"):
            # Human override (plan5 Phase B): taxonomy already validated
            # by the API layer; no LLM call, confidence 1.0 by definition.
            return {
                "topic": state["manual_topic"],
                "subtopic": state["manual_subtopic"],
                "chapters": ["manual"],
                "confidence": 1.0,
                "_event_detail": (
                    f"manual override: {state['manual_topic']}/{state['manual_subtopic']}"
                ),
            }
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
        chunks = []
        chunk_pages = []
        chunk_rows = []
        semantic = UPLOAD_CHUNKING_STRATEGY == "semantic" and not is_csv_document(
            state["filename"], state["media_type"]
        )
        embeddings = get_embeddings_client() if semantic else None
        for row_number, text in state["csv_rows"]:
            row_chunks = chunk_text(text)
            chunks.extend(row_chunks)
            chunk_pages.extend([None] * len(row_chunks))
            chunk_rows.extend([row_number] * len(row_chunks))
        for page_number, text in enumerate(state["pages"], start=1):
            page_chunks = semantic_chunk_text(text, embeddings) if embeddings is not None else chunk_text(text)
            chunks.extend(page_chunks)
            page = page_number if state["media_type"] == "application/pdf" else None
            chunk_pages.extend([page] * len(page_chunks))
            chunk_rows.extend([None] * len(page_chunks))
        if not chunks:
            return {"outcome": "failed", "error": "chunk: no chunks produced"}
        detail = f"{len(chunks)} chunks" + (" (semantic)" if semantic else "")
        return {"chunks": chunks, "chunk_pages": chunk_pages, "chunk_rows": chunk_rows,
                "_event_detail": detail}

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
                    **({"replacement_pending": True} if state["is_replacement"] else {}),
                    **({"page": state["chunk_pages"][i]} if state["chunk_pages"][i] is not None else {}),
                    **({"row": state["chunk_rows"][i]} if state["chunk_rows"][i] is not None else {}),
                },
            )
            for i, text in enumerate(state["chunks"])
        ]
        store = get_vector_store()
        try:
            store.add_documents(documents, ids=ids)
        except Exception:
            store.delete(ids=ids)
            raise
        return {"chunk_ids": ids, "_event_detail": f"{len(ids)} chunks indexed"}

    @timed("validate_retrieval")
    def validate_retrieval(state: IngestionState) -> dict:
        """Before publishing, prove the new content is actually findable
        through the same filtered search the QA pipeline uses - plan5 §7.
        Each sampled chunk's own opening words are used as the query; the
        document must appear in the top results. Deliberately NOT an LLM
        judgment - retrieval success, not answer quality."""
        store = get_vector_store()
        where = {"$and": [
            {"topic": state["topic"]}, {"subtopic": state["subtopic"]},
            {"document_id": state["document_id"]}, {"version": state["version"]},
        ]}
        misses = []
        sample_indices = sorted({
            0, len(state["chunks"]) // 2, len(state["chunks"]) - 1
        })
        for sample_index in sample_indices:
            chunk_text_sample = state["chunks"][sample_index]
            query = " ".join(chunk_text_sample.split()[:12])
            results = store.similarity_search(query, k=_RETRIEVAL_TEST_TOP_K, filter=where)
            if not any(
                r.metadata.get("document_id") == state["document_id"]
                and r.metadata.get("version") == state["version"]
                for r in results
            ):
                misses.append(query)
        if misses:
            # Roll back: an unfindable document must not be published.
            store.delete(ids=state["chunk_ids"])
            return {
                "outcome": "failed",
                "error": f"validate_retrieval: document not retrievable for: {misses}",
                "chunk_ids": [],
            }
        return {"_event_detail": f"{len(sample_indices)} probe queries passed"}

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


def run_ingestion(
    registry: DocumentRegistry,
    record: dict,
    content: bytes,
    manual_topic: str = "",
    manual_subtopic: str = "",
) -> None:
    """Executes the ingestion workflow for one uploaded document and
    writes the terminal result to the registry. Designed to run as a
    FastAPI background task - it must never raise. With
    `manual_topic`/`manual_subtopic` set (the Knowledge Base Manager's
    override), classification is taken as given instead of LLM-decided."""
    graph = build_ingestion_graph(registry)
    initial: IngestionState = {
        "document_id": record["document_id"],
        "version": record["version"],
        "is_replacement": record.get("is_replacement", False),
        "filename": record["filename"],
        "media_type": record["media_type"],
        "content": content,
        "extracted_text": "",
        "pages": [],
        "csv_rows": [],
        "topic": "",
        "subtopic": "",
        "chapters": [],
        "confidence": 0.0,
        "chunks": [],
        "chunk_pages": [],
        "chunk_rows": [],
        "chunk_ids": [],
        "outcome": "",
        "error": "",
        "manual_topic": manual_topic,
        "manual_subtopic": manual_subtopic,
    }
    try:
        final = graph.invoke(initial)
    except Exception as exc:  # noqa: BLE001 - background task must not raise
        registry.update(record["document_id"], status="failed", error=f"ingestion crashed: {exc}")
        return

    if record.get("is_replacement"):
        current = registry.get(record["document_id"])
        if current is None or not current.get("pending") or current["pending"]["version"] != record["version"]:
            raise RuntimeError("Replacement state changed while ingestion was running.")
        pending = current["pending"]
        outcome = final.get("outcome") or "failed"
        if outcome != "indexed":
            if final.get("chunk_ids"):
                try:
                    get_vector_store().delete(ids=final["chunk_ids"])
                except Exception as exc:
                    final["error"] = f"{final.get('error') or outcome}; replacement cleanup failed: {exc}"
            pending.update(
                topic=final.get("topic") or None, subtopic=final.get("subtopic") or None,
                chapters=final.get("chapters", []),
                classification_confidence=final.get("confidence"),
            )
            registry.update(record["document_id"], status=outcome, error=final.get("error") or None, pending=pending)
            return
        old_ids = current["chunk_ids"]
        with index_publication_lock:
            registry.update(
                record["document_id"], status="indexed", error=None,
                version=pending["version"], content_hash=pending["content_hash"],
                media_type=pending["media_type"], size_bytes=pending["size_bytes"],
                stored_path=pending["stored_path"], topic=final.get("topic") or None,
                subtopic=final.get("subtopic") or None, chapters=final.get("chapters", []),
                classification_confidence=final.get("confidence"),
                chunk_count=len(final.get("chunk_ids", [])), chunk_ids=final.get("chunk_ids", []),
                pending=None, cleanup_ids=old_ids,
            )
            try:
                if old_ids:
                    get_vector_store().delete(ids=old_ids)
            except Exception as exc:
                registry.update(record["document_id"], error=f"New version indexed, but old chunk cleanup failed: {exc}")
            else:
                registry.update(record["document_id"], cleanup_ids=[])
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
