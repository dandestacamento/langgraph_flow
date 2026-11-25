"""Ingestion pipeline tests (chat-ui-plan5.md Phase A).

API-level tests follow tests/test_chat_api.py's conventions: the HTTP
layer via TestClient (which runs FastAPI background tasks synchronously
before returning - so an upload response means ingestion has finished),
auth against a locally generated RSA key, real LLM calls through the
shared response cache. Vector-store writes are cleaned up after each
end-to-end test so the curated index isn't polluted.
"""

from __future__ import annotations

import io
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import app.api.auth as auth_module
import app.api.main as api_module
import app.ingestion.graph as ingestion_graph
from app.agents._shared import _source_labels
from app.api.attachments import MAX_EXTRACTED_CHARS, extract_document_text
from app.api.main import app
from app.chat.routing_summary import build_routing_summary
from app.ingestion.classify import DocumentClassification, classification_problem
from app.ingestion.graph import chunk_text
from app.ingestion.registry import DocumentRegistry
from app.ingestion.storage import LocalDocumentStorage
from app.rag.retrieval import get_vector_store

client = TestClient(app)

_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()

SAMPLE_BULLETIN = (
    Path(__file__).resolve().parent.parent
    / "datasets"
    / "ingestion_samples"
    / "wm500-maintenance-bulletin.md"
)


@pytest.fixture(autouse=True)
def _use_test_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_get_signing_key", lambda token: _TEST_PUBLIC_KEY)


def _auth_headers(sub: str = "test-user") -> dict[str, str]:
    payload = {"sub": sub, "azp": auth_module.KEYCLOAK_CLIENT_ID, "iss": auth_module.KEYCLOAK_ISSUER}
    token = pyjwt.encode(payload, _TEST_PRIVATE_KEY, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


def _cleanup_document(document_id: str) -> None:
    """Removes a test document's chunks from the shared Chroma index."""
    detail = client.get(f"/knowledge/documents/{document_id}", headers=_auth_headers()).json()
    if detail.get("chunk_ids"):
        get_vector_store().delete(ids=detail["chunk_ids"])


# ---------------------------------------------------------------- unit


def test_multichapter_pdf_preserves_page_boundaries_for_chunking() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "instructions" / "sample_files" / "dishwasher_manual_file2.pdf"
    )
    text = extract_document_text(path.read_bytes(), "application/pdf")
    chunks = chunk_text(text)

    assert len(text) < MAX_EXTRACTED_CHARS
    assert len(chunks) >= 6
    for title in ("Model and controls", "Programs and cycle selection", "Loading and daily use",
                  "Routine care", "Fault codes and troubleshooting", "Warranty and support"):
        assert any(title in chunk for chunk in chunks)
    assert "7-year motor warranty" in " ".join(text.split())


def test_chunk_text_merges_small_paragraphs_and_splits_large_content() -> None:
    small = "para one\n\npara two\n\npara three"
    assert chunk_text(small) == ["para one\n\npara two\n\npara three"]

    big_paragraphs = "\n\n".join(f"paragraph {i} " + "x" * 700 for i in range(4))
    chunks = chunk_text(big_paragraphs)
    assert len(chunks) == 4  # each ~700 chars: merging would exceed the target
    assert chunks[0].startswith("paragraph 0")

    long_paragraph = "x" * 2501
    chunks = chunk_text(long_paragraph)
    assert all(set(chunk) == {"x"} for chunk in chunks)
    assert sum(map(len, chunks)) >= len(long_paragraph)
    assert max(map(len, chunks)) <= 1200


def test_chunk_text_keeps_sentence_together_at_a_line_boundary() -> None:
    text = "x" * 1135 + "\nProfiles are based on requirements and risk tolerance,\nand resources."
    expected = "Profiles are based on requirements and risk tolerance, and resources."
    chunks = chunk_text(text)
    assert any(expected in " ".join(chunk.split()) for chunk in chunks)
    assert max(map(len, chunks)) <= 1200


class _SemanticTestEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0] if "Paris" in text else [1.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def test_semantic_chunking_groups_similar_sentences_and_splits_topic_changes():
    text = "Wash dishes first. Dry the dishes. Paris is in France. Paris has museums."
    assert ingestion_graph.semantic_chunk_text(text, _SemanticTestEmbeddings()) == [
        "Wash dishes first. Dry the dishes.",
        "Paris is in France. Paris has museums.",
    ]


def test_semantic_chunking_bounds_long_sentences_and_batches():
    class CountingEmbeddings(_SemanticTestEmbeddings):
        batches: list[int]

        def __init__(self):
            self.batches = []

        def embed_documents(self, texts):
            self.batches.append(len(texts))
            return super().embed_documents(texts)

    embeddings = CountingEmbeddings()
    text = " ".join(f"Sentence {i}." for i in range(130)) + " " + "x" * 2501
    chunks = ingestion_graph.semantic_chunk_text(text, embeddings)
    assert embeddings.batches == [128, 5]
    assert all(len(chunk) <= 1200 for chunk in chunks)
    assert all(f"Sentence {i}." in " ".join(chunks) for i in range(130))
    assert sum(chunk.count("x") for chunk in chunks) >= 2501


def test_semantic_chunking_rejects_zero_and_inconsistent_embeddings():
    class InvalidEmbeddings(_SemanticTestEmbeddings):
        def embed_documents(self, texts):
            return [[0.0, 0.0] for _ in texts]

    with pytest.raises(ValueError, match="non-zero"):
        ingestion_graph.semantic_chunk_text("One. Two.", InvalidEmbeddings())

    class InconsistentEmbeddings(_SemanticTestEmbeddings):
        def embed_documents(self, texts):
            return [[1.0] if "128" in text else [1.0, 0.0] for text in texts]

    text = " ".join(f"Sentence {i}." for i in range(129))
    with pytest.raises(ValueError, match="dimension"):
        ingestion_graph.semantic_chunk_text(text, InconsistentEmbeddings())


def test_csv_upload_indexes_rows_and_surfaces_provenance(monkeypatch, tmp_path):
    class Store:
        def __init__(self):
            self.documents = []

        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    store = Store()
    registry = DocumentRegistry()
    monkeypatch.setattr(api_module, "_document_registry", registry)
    monkeypatch.setattr(api_module, "_document_storage", LocalDocumentStorage(tmp_path))
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    monkeypatch.setattr(
        ingestion_graph, "classify_document",
        lambda filename, text: DocumentClassification(
            topic="appliances", subtopic="dishwashers", chapters=["manual"], confidence=0.95
        ),
    )
    content = b'\xef\xbb\xbfmodel,description\r\nD1,"quiet, efficient"\r\nD2,"line one\nline two"\r\n'
    response = client.post(
        "/knowledge/documents", files={"file": ("devices.csv", content, "text/csv")},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    detail = registry.get(response.json()["document_id"])
    assert detail["status"] == "indexed", detail["error"]
    assert [(doc.metadata["row"], doc.page_content) for doc in store.documents] == [
        (2, "model: D1\ndescription: quiet, efficient"),
        (3, "model: D2\ndescription: line one\nline two"),
    ]
    passage = {**store.documents[1].metadata, "text": store.documents[1].page_content}
    summary = build_routing_summary({"retrieved_passages": {"appliances": [passage]}})
    assert summary["passages"]["appliances"][0]["row"] == 3
    assert "row 3" in _source_labels([passage])[0]

    # Identical bytes under a non-CSV name must not reuse differently parsed content.
    other = client.post(
        "/knowledge/documents", files={"file": ("devices.txt", content, "text/plain")},
        headers=_auth_headers(),
    )
    assert other.status_code == 200
    assert other.json()["document_id"] != response.json()["document_id"]
    assert registry.get(other.json()["document_id"])["status"] == "indexed"
    assert all("row" not in doc.metadata for doc in store.documents)


def test_large_csv_row_keeps_row_metadata_across_chunks(monkeypatch):
    class Store:
        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    store = Store()
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    content = ("model,description\nD1," + "x" * 2500 + "\n").encode()
    registry = DocumentRegistry()
    record = registry.create(
        filename="devices.CSV", media_type="text/plain", size_bytes=len(content),
        content_hash="large", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "indexed", detail["error"]
    assert len(store.documents) > 1
    assert all(doc.metadata["row"] == 2 and len(doc.page_content) <= 1200 for doc in store.documents)
    assert sum(doc.page_content.count("x") for doc in store.documents) >= 2500


@pytest.mark.parametrize(
    "content",
    [b"name,name\nx,y\n", b"name,\nx,y\n", b"name,value\nx\n",
     b'name,value\nx,"unterminated', b"name,value\n", b"name,value\n\nx,y\n"],
)
def test_invalid_csv_fails_before_indexing(content, monkeypatch):
    monkeypatch.setattr(
        ingestion_graph, "get_vector_store",
        lambda: pytest.fail("invalid CSV must not reach indexing"),
    )
    registry = DocumentRegistry()
    record = registry.create(
        filename="invalid.csv", media_type="text/plain", size_bytes=len(content),
        content_hash="invalid", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "failed"
    assert "extract:" in detail["error"]


def _text_pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_semantic_upload_preserves_pdf_page_provenance(monkeypatch):
    class Store:
        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    store = Store()
    monkeypatch.setattr(ingestion_graph, "UPLOAD_CHUNKING_STRATEGY", "semantic")
    monkeypatch.setattr(ingestion_graph, "get_embeddings_client", _SemanticTestEmbeddings)
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    content = _text_pdf("Wash dishes. Dry dishes. Paris is in France.", "Paris has museums.")
    registry = DocumentRegistry()
    record = registry.create(
        filename="manual.pdf", media_type="application/pdf", size_bytes=len(content),
        content_hash="semantic-pdf", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "indexed", detail["error"]
    assert [(doc.metadata["page"], doc.page_content) for doc in store.documents] == [
        (1, "Wash dishes. Dry dishes."),
        (1, "Paris is in France."),
        (2, "Paris has museums."),
    ]
    assert any(event["node"] == "chunk" and "semantic" in event["detail"] for event in detail["events"])


def test_semantic_strategy_leaves_csv_row_chunking_unchanged(monkeypatch):
    class Store:
        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    store = Store()
    monkeypatch.setattr(ingestion_graph, "UPLOAD_CHUNKING_STRATEGY", "semantic")
    monkeypatch.setattr(ingestion_graph, "get_embeddings_client", lambda: pytest.fail("CSV is not semantic"))
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    content = b"name,description\nD1,Wash dishes. Paris is in France.\n"
    registry = DocumentRegistry()
    record = registry.create(
        filename="devices.csv", media_type="text/plain", size_bytes=len(content),
        content_hash="semantic-csv", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "indexed", detail["error"]
    assert [(doc.metadata["row"], doc.page_content) for doc in store.documents] == [
        (2, "name: D1\ndescription: Wash dishes. Paris is in France."),
    ]


def test_semantic_embedding_failure_fails_before_indexing(monkeypatch):
    class FailingEmbeddings(_SemanticTestEmbeddings):
        def embed_documents(self, texts):
            raise RuntimeError("embedding service unavailable")

    monkeypatch.setattr(ingestion_graph, "UPLOAD_CHUNKING_STRATEGY", "semantic")
    monkeypatch.setattr(ingestion_graph, "get_embeddings_client", FailingEmbeddings)
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: pytest.fail("must not index"))
    content = b"First sentence. Second sentence."
    registry = DocumentRegistry()
    record = registry.create(
        filename="manual.txt", media_type="text/plain", size_bytes=len(content),
        content_hash="semantic-failure", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "failed"
    assert "chunk: embedding service unavailable" in detail["error"]


@pytest.mark.parametrize("media_type", ["text/plain", "application/pdf"])
def test_ingestion_indexes_complete_long_documents_with_page_provenance(monkeypatch, media_type):
    class Store:
        documents = []

        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    store = Store()
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    content = (
        _text_pdf("A" * 8500, "last page unique warranty")
        if media_type == "application/pdf"
        else ("A" * 8500 + "\n\nlast page unique warranty").encode()
    )
    registry = DocumentRegistry()
    record = registry.create(
        filename="manual.pdf" if media_type == "application/pdf" else "manual.txt",
        media_type=media_type, size_bytes=len(content), content_hash="long", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "indexed", detail["error"]
    assert any("last page unique warranty" in doc.page_content for doc in store.documents)
    assert all(len(doc.page_content) <= 1200 for doc in store.documents)
    last = next(doc for doc in store.documents if "last page unique warranty" in doc.page_content)
    assert last.metadata["source"] == record["filename"]
    assert last.metadata["version"] == 1
    assert last.metadata.get("page") == (2 if media_type == "application/pdf" else None)


def test_scanned_pdf_is_not_silently_indexed(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "reference" / "1_Krish-RAG" / "1_RAG" / "1-2RAG.pdf"
    if not path.exists():
        pytest.skip("Optional reference PDF is not available")
    content = path.read_bytes()
    registry = DocumentRegistry()
    record = registry.create(
        filename=path.name, media_type="application/pdf", size_bytes=len(content),
        content_hash="scanned", uploaded_by="u1",
    )
    ingestion_graph.run_ingestion(registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers")
    detail = registry.get(record["document_id"])
    assert detail["status"] == "failed"
    assert "OCR" in detail["error"]


def test_registry_dedup_and_event_log() -> None:
    registry = DocumentRegistry()
    record = registry.create(
        filename="a.md", media_type="text/plain", size_bytes=3,
        content_hash="hash-1", uploaded_by="u1",
    )
    assert registry.find_by_hash("hash-1")["document_id"] == record["document_id"]
    assert registry.find_by_hash("other") is None

    registry.append_event(record["document_id"], "extract", 12, "3 chars")
    events = registry.get(record["document_id"])["events"]
    assert events[0]["node"] == "extract"
    assert events[0]["elapsed_ms"] == 12


def test_postgres_replacement_registry_in_temporary_schema(monkeypatch):
    import os
    from contextlib import nullcontext
    import psycopg

    conn_string = os.environ.get("TEST_POSTGRES_DSN")
    if not conn_string:
        pytest.skip("Set TEST_POSTGRES_DSN to run the isolated PostgreSQL registry test")
    with psycopg.connect(conn_string, autocommit=True) as conn:
        conn.execute(
            "CREATE TEMP TABLE knowledge_documents ("
            "document_id TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL, "
            "size_bytes INTEGER NOT NULL, content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, "
            "status TEXT NOT NULL, uploaded_by TEXT NOT NULL DEFAULT '', topic TEXT, subtopic TEXT, "
            "chapters TEXT NOT NULL DEFAULT '[]', classification_confidence REAL, error TEXT, "
            "chunk_count INTEGER NOT NULL DEFAULT 0, chunk_ids TEXT NOT NULL DEFAULT '[]', "
            "events TEXT NOT NULL DEFAULT '[]', stored_path TEXT NOT NULL DEFAULT '', "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: nullcontext(conn))
        registry = DocumentRegistry(conn_string)
        document = registry.create(filename="sample.txt", media_type="text/plain", size_bytes=1,
                                   content_hash="old", uploaded_by="tester")
        document_id = document["document_id"]
        registry.update(document_id, status="indexed", chunk_count=1, chunk_ids=["old-id"])
        pending = {"version": 2, "content_hash": "new"}
        assert registry.begin_replacement(document_id, 1, pending, indexed_only=True)
        assert not registry.begin_replacement(document_id, 1, pending, indexed_only=True)
        assert registry.active_versions() == ((document_id, 1),)
        registry.recover_interrupted_replacements()
        assert registry.get(document_id)["status"] == "failed"
        assert registry.active_versions() == ((document_id, 1),)
        assert not registry.begin_replacement(document_id, 1, pending, indexed_only=True)
        assert registry.resume_replacement(document_id, ("failed",))
        registry.update(document_id, status="needs_review")
        assert registry.resume_replacement(document_id, ("needs_review",))
        assert not registry.resume_replacement(document_id, ("needs_review",))
        registry.update(document_id, status="indexed", version=2, pending=None, cleanup_ids=["old-id"])
        assert registry.get(document_id)["pending"] is None
        assert registry.get(document_id)["cleanup_ids"] == ["old-id"]
        assert registry.active_versions() == ((document_id, 2),)


def test_classification_problem_flags_bad_taxonomy_and_low_confidence() -> None:
    good = DocumentClassification(
        topic="appliances", subtopic="washing_machines", chapters=["troubleshooting"], confidence=0.95
    )
    assert classification_problem(good) is None

    unknown_topic = good.model_copy(update={"topic": "cooking"})
    assert "Unknown topic" in classification_problem(unknown_topic)

    wrong_subtopic = good.model_copy(update={"subtopic": "networking"})
    assert "Unknown subtopic" in classification_problem(wrong_subtopic)

    unsure = good.model_copy(update={"confidence": 0.3})
    assert "Low classification confidence" in classification_problem(unsure)


# ----------------------------------------------------------------- API


def test_knowledge_upload_requires_authentication() -> None:
    response = client.post(
        "/knowledge/documents", files={"file": ("a.md", b"hello", "text/plain")}
    )
    assert response.status_code == 401


def test_knowledge_upload_rejects_unsupported_types() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    response = client.post(
        "/knowledge/documents",
        files={"file": ("image.png", png, "image/png")},
        headers=_auth_headers(),
    )
    assert response.status_code == 415


def test_ingest_classify_index_and_answer_through_the_existing_pipeline() -> None:
    """The Phase A exit criterion end-to-end: upload a bulletin with
    knowledge the curated KB does not contain (error E77), watch it get
    classified into appliances/washing_machines, indexed, retrieval-
    validated and published - then ask the UNCHANGED chat pipeline about
    E77 and get an answer grounded in the new document."""
    content = SAMPLE_BULLETIN.read_bytes()
    upload = client.post(
        "/knowledge/documents",
        files={"file": (SAMPLE_BULLETIN.name, content, "text/markdown")},
        headers=_auth_headers(),
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["document_id"]

    try:
        detail = client.get(
            f"/knowledge/documents/{document_id}", headers=_auth_headers()
        ).json()
        assert detail["status"] == "indexed", detail.get("error")
        assert detail["topic"] == "appliances"
        assert detail["subtopic"] == "washing_machines"
        assert detail["chunk_count"] > 0
        event_nodes = [e["node"] for e in detail["events"]]
        assert event_nodes[0] == "validate"
        assert "publish" in event_nodes

        # Duplicate upload: same bytes -> same document, nothing reprocessed.
        again = client.post(
            "/knowledge/documents",
            files={"file": ("renamed.md", content, "text/markdown")},
            headers=_auth_headers(),
        ).json()
        assert again["duplicate"] is True
        assert again["document_id"] == document_id

        # The money test: the chat pipeline, untouched, answers from the
        # newly ingested knowledge with the standard citation machinery.
        answer = client.post(
            "/chat",
            json={
                "thread_id": f"test-ingest-{document_id}",
                "message": "What does washing machine error E77 mean?",
            },
            headers=_auth_headers(),
        ).json()
        assert "door" in answer["final_answer"].lower()
        assert "insufficient information" not in answer["final_answer"].lower()
        assert answer["routing_summary"]["topics"] == ["appliances"]
        retrieved_doc_ids = {
            passage.get("document_id")
            for passages in answer["routing_summary"]["passages"].values()
            for passage in passages
        }
        assert document_id in retrieved_doc_ids
    finally:
        detail = client.get(
            f"/knowledge/documents/{document_id}", headers=_auth_headers()
        ).json()
        chunk_ids = detail.get("chunk_ids") or []
        if chunk_ids:
            get_vector_store().delete(ids=chunk_ids)


def test_off_taxonomy_document_is_parked_for_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """A document the classifier can't place in the taxonomy must end in
    needs_review - parked, visible, and NOT indexed (the Phase C review
    flow will resume it)."""
    monkeypatch.setattr(
        ingestion_graph,
        "classify_document",
        lambda filename, text: DocumentClassification(
            topic="cooking", subtopic="desserts", chapters=["recipes"], confidence=0.9
        ),
    )

    response = client.post(
        "/knowledge/documents",
        files={"file": ("recipes.md", b"How to bake a perfect sponge cake...", "text/markdown")},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    detail = client.get(
        f"/knowledge/documents/{response.json()['document_id']}", headers=_auth_headers()
    ).json()
    assert detail["status"] == "needs_review"
    assert "Unknown topic" in detail["error"]
    assert detail["chunk_count"] == 0


def test_manual_override_unparks_and_indexes_a_needs_review_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan5 Phase B's manual override: a human-corrected classification
    re-runs ingestion from the stored original (no LLM classification)
    and the document ends up indexed under the chosen taxonomy."""
    monkeypatch.setattr(
        ingestion_graph,
        "classify_document",
        lambda filename, text: DocumentClassification(
            topic="cooking", subtopic="desserts", chapters=["recipes"], confidence=0.9
        ),
    )
    uploaded = client.post(
        "/knowledge/documents",
        files={
            "file": (
                "wm-descale.md",
                b"Descaling guide: run an empty 90-degree wash with descaler every six months "
                b"to protect the heating element of a front-loader washing machine.",
                "text/markdown",
            )
        },
        headers=_auth_headers(),
    ).json()
    document_id = uploaded["document_id"]
    assert (
        client.get(f"/knowledge/documents/{document_id}", headers=_auth_headers()).json()["status"]
        == "needs_review"
    )

    try:
        response = client.post(
            f"/knowledge/documents/{document_id}/classification",
            json={"topic": "appliances", "subtopic": "washing_machines"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        detail = client.get(
            f"/knowledge/documents/{document_id}", headers=_auth_headers()
        ).json()
        assert detail["status"] == "indexed", detail.get("error")
        assert detail["topic"] == "appliances"
        assert detail["subtopic"] == "washing_machines"
        assert detail["classification_confidence"] == 1.0
        assert detail["chunk_count"] > 0
        assert any(e["node"] == "manual_override" for e in detail["events"])
    finally:
        detail = client.get(
            f"/knowledge/documents/{document_id}", headers=_auth_headers()
        ).json()
        if detail.get("chunk_ids"):
            get_vector_store().delete(ids=detail["chunk_ids"])


def test_manual_override_rejects_invalid_taxonomy() -> None:
    uploaded = client.post(
        "/knowledge/documents",
        files={"file": ("note.md", b"A short note about washing machine detergent dosing.", "text/markdown")},
        headers=_auth_headers(),
    ).json()
    document_id = uploaded["document_id"]
    try:
        response = client.post(
            f"/knowledge/documents/{document_id}/classification",
            json={"topic": "cooking", "subtopic": "desserts"},
            headers=_auth_headers(),
        )
        assert response.status_code == 422
    finally:
        detail = client.get(
            f"/knowledge/documents/{document_id}", headers=_auth_headers()
        ).json()
        if detail.get("chunk_ids"):
            get_vector_store().delete(ids=detail["chunk_ids"])


def test_unreadable_document_fails_honestly() -> None:
    """A PDF with no extractable text must end in failed with a clear
    error, not an empty document silently published."""
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)

    response = client.post(
        "/knowledge/documents",
        files={"file": ("scanned.pdf", buffer.getvalue(), "application/pdf")},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    detail = client.get(
        f"/knowledge/documents/{response.json()['document_id']}", headers=_auth_headers()
    ).json()
    assert detail["status"] == "failed"
    assert "no readable text" in detail["error"]


def test_new_taxonomy_requires_approval_and_persists(tmp_path, monkeypatch):
    import app.api.main as api
    import app.ingestion.taxonomy as taxonomy
    from app.ingestion.storage import LocalDocumentStorage

    store = taxonomy.TaxonomyStore(path=tmp_path / "taxonomy.db")
    monkeypatch.setattr(taxonomy, "_store", store)
    monkeypatch.setattr(api, "_document_registry", DocumentRegistry())
    monkeypatch.setattr(api, "_document_storage", LocalDocumentStorage(tmp_path))
    monkeypatch.setattr(
        ingestion_graph, "classify_document",
        lambda filename, text: DocumentClassification(
            topic="artificial_intelligence", subtopic="risk_management",
            chapters=["framework"], confidence=0.9,
        ),
    )

    class Store:
        documents = []

        def add_documents(self, documents, ids):
            self.documents = documents

        def similarity_search(self, query, k, filter):
            return self.documents[:k]

    vector_store = Store()
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: vector_store)
    response = client.post(
        "/knowledge/documents", files={"file": ("ai.txt", b"AI risk framework", "text/plain")},
        headers=_auth_headers(),
    )
    document_id = response.json()["document_id"]
    detail = client.get(f"/knowledge/documents/{document_id}", headers=_auth_headers()).json()
    assert detail["status"] == "needs_review"
    assert detail["topic"] == "artificial_intelligence"
    assert "artificial_intelligence" not in store.get()
    refreshed = client.post(f"/knowledge/documents/{document_id}/suggestion", headers=_auth_headers())
    assert refreshed.status_code == 200
    assert client.get(f"/knowledge/documents/{document_id}", headers=_auth_headers()).json()["status"] == "needs_review"
    body = {"topic": "artificial_intelligence", "subtopic": "risk_management"}
    rejected = client.post(f"/knowledge/documents/{document_id}/classification", json=body, headers=_auth_headers())
    assert rejected.status_code == 422
    invalid = client.post(
        f"/knowledge/documents/{document_id}/classification",
        json={**body, "topic": "../bad", "create_missing": True}, headers=_auth_headers(),
    )
    assert invalid.status_code == 422
    approved = client.post(
        f"/knowledge/documents/{document_id}/classification",
        json={**body, "create_missing": True}, headers=_auth_headers(),
    )
    assert approved.status_code == 200
    detail = client.get(f"/knowledge/documents/{document_id}", headers=_auth_headers()).json()
    assert detail["status"] == "indexed", detail["error"]
    assert detail["chunk_count"] > 0
    assert client.post(f"/knowledge/documents/{document_id}/suggestion", headers=_auth_headers()).status_code == 409
    assert taxonomy.TaxonomyStore(path=tmp_path / "taxonomy.db").get()["artificial_intelligence"] == ["risk_management"]
    store.add("appliances", "ovens")
    assert "ovens" in taxonomy.TaxonomyStore(path=tmp_path / "taxonomy.db").get()["appliances"]


@pytest.mark.parametrize(
    ("topic", "subtopic"),
    [("artificial_intelligence", "risk_management"), ("appliances", "ovens")],
)
def test_custom_taxonomy_routes_to_retrieved_document(tmp_path, monkeypatch, topic, subtopic):
    import app.graph as routing_graph
    import app.ingestion.taxonomy as taxonomy
    import app.rag.retrieval as retrieval
    import app.routers.subtopic_router as subtopic_router
    import app.routers.topic_router as topic_router
    import app.agents._shared as agent
    from langchain_core.documents import Document
    from app.state import initial_state

    store = taxonomy.TaxonomyStore(path=tmp_path / "taxonomy.db")
    store.add(topic, subtopic)
    monkeypatch.setattr(taxonomy, "_store", store)
    models = []

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, model):
            models.append(model)
            self.model = model
            return self

        def invoke(self, messages):
            if self.model.__name__ == "CurrentTopicOutput":
                return self.model(
                    is_ambiguous=False, topics=[topic],
                    topic_questions=[{"topic": topic, "question": "What is the framework?"}],
                    confidence=0.9, reasoning="AI risk",
                )
            return self.model(subtopic=subtopic, confidence=0.9, reasoning="AI risk")

    class FakeVectorStore:
        def similarity_search_with_score(self, query, k, filter):
            assert filter["$and"][0] == {"$and": [{"topic": topic}, {"subtopic": subtopic}]}
            return [(Document(page_content="The framework manages AI risks.", metadata={
                "topic": topic, "subtopic": subtopic,
                "chapter_id": "ingested_framework", "document_id": "DOC-AI",
            }), 0.1)]

    monkeypatch.setattr(topic_router, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(subtopic_router, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(retrieval, "_has_uploaded_content", lambda *args: False)
    monkeypatch.setattr(routing_graph, "classify_complexity", lambda state: {})
    monkeypatch.setattr(routing_graph, "classify_multihop", lambda state: {"is_multi_hop": False})
    monkeypatch.setattr(routing_graph, "select_tools", lambda state: {})
    monkeypatch.setattr(agent, "_generate_answer", lambda topic, question, passages, tool: (passages[0]["text"], False))
    result = routing_graph.build_graph().invoke(initial_state("What is the framework?"))
    assert result["selected_topics"] == [topic]
    assert result["selected_subtopics"][topic] == subtopic
    assert result["retrieved_passages"][topic][0]["document_id"] == "DOC-AI"
    assert result["final_answer"] == "The framework manages AI risks."
    assert topic in str(models[0].model_json_schema())


def test_custom_agent_preserves_multitopic_question():
    from app.graph import route_to_agents
    from app.state import get_topic_question

    state = {
        "question": "Ask about AI and appliances",
        "selected_topics": ["artificial_intelligence", "appliances"],
        "topic_decision": {"topic_questions": {"artificial_intelligence": "Ask about AI"}},
    }
    custom = route_to_agents(state)[0]
    assert custom.node == "custom_topic_agent"
    assert custom.arg["custom_agent_topic"] == "artificial_intelligence"
    assert get_topic_question(custom.arg, "artificial_intelligence") == "Ask about AI"


def test_uploaded_sources_include_deduplicated_pages_and_preserve_other_sources(monkeypatch):
    from types import SimpleNamespace
    import app.agents._shared as agent

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content="Risk management supports trustworthy AI.")

    monkeypatch.setattr(agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(agent.llm_gateway, "llm_kwargs", lambda: {})
    monkeypatch.setattr(
        agent, "taxonomy_store",
        lambda: SimpleNamespace(get=lambda: {"artificial_intelligence": ["risk_management"]}),
    )
    uploaded = {
        "chapter_id": "ingested_manual", "source": "NIST.AI.100-1.pdf",
        "document_id": "DOC-123", "version": 1, "text": "AI risk management",
    }
    passages = [
        {**uploaded, "page": 9}, {**uploaded, "page": 1}, {**uploaded, "page": 9},
        {**uploaded, "page": None},
        {**uploaded, "document_id": "DOC-789", "version": 2, "page": 3},
        {"chapter_id": "chapter_01", "text": "Curated chapter"},
        {"chapter_id": "ingested_note", "source": "notes.txt", "document_id": "DOC-456", "version": 2, "text": "Note"},
    ]
    answer, insufficient = agent._generate_answer(
        "artificial_intelligence", "What is the purpose?", passages,
        {"tool_name": "calculator", "tool_input": "1+1", "output": "2", "error": None},
    )
    assert not insufficient
    assert "chapter_01" in answer
    assert "NIST.AI.100-1.pdf (DOC-123; v1; pages 1, 9; other passages without page numbers; retrieved, not verified)" in answer
    assert "NIST.AI.100-1.pdf (DOC-789; v2; page 3; retrieved, not verified)" in answer
    assert "notes.txt (DOC-456; v2; retrieved, not verified)" in answer
    assert "tool:calculator" in answer
    assert "ingested_manual" not in answer


def test_insufficient_answer_does_not_list_uploaded_sources(monkeypatch):
    from types import SimpleNamespace
    import app.agents._shared as agent

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content=agent.INSUFFICIENT_INFO_MARKER)

    monkeypatch.setattr(agent, "ChatOpenAI", FakeLLM)
    monkeypatch.setattr(agent.llm_gateway, "llm_kwargs", lambda: {})
    monkeypatch.setattr(
        agent, "taxonomy_store",
        lambda: SimpleNamespace(get=lambda: {"artificial_intelligence": ["risk_management"]}),
    )
    answer, insufficient = agent._generate_answer(
        "artificial_intelligence", "What is missing?",
        [{"chapter_id": "ingested_manual", "source": "NIST.AI.100-1.pdf", "page": 9, "text": "AI risk"}],
        None,
    )
    assert insufficient
    assert answer == agent.INSUFFICIENT_INFO_MARKER


@pytest.fixture
def replacement_environment(tmp_path, monkeypatch):
    import chromadb
    import uuid
    import app.api.main as api
    import app.rag.retrieval as retrieval
    from app.ingestion.storage import LocalDocumentStorage
    from langchain_chroma import Chroma
    from langchain_core.embeddings import Embeddings

    class TestEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    registry = DocumentRegistry()
    store = Chroma(client=chromadb.Client(), collection_name=f"replacement_{uuid.uuid4().hex}", embedding_function=TestEmbeddings())
    monkeypatch.setattr(api, "_document_registry", registry)
    monkeypatch.setattr(api, "_document_storage", LocalDocumentStorage(tmp_path))
    monkeypatch.setattr(api, "_scope_llm_calls_to", lambda user: None)
    monkeypatch.setattr(api, "get_vector_store", lambda: store)
    monkeypatch.setattr(ingestion_graph, "get_vector_store", lambda: store)
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: store)
    monkeypatch.setattr(retrieval, "_registry_provider", lambda: registry)
    monkeypatch.setattr(
        ingestion_graph, "classify_document",
        lambda filename, text: DocumentClassification(
            topic="appliances", subtopic="dishwashers", chapters=["manual"], confidence=0.95,
        ),
    )
    return registry, store


def _upload_test_version(content: bytes):
    return client.post(
        "/knowledge/documents", files={"file": ("replace.txt", content, "text/plain")},
        headers=_auth_headers(),
    )


def test_section_reference_hints_require_a_unique_visible_topic(replacement_environment):
    import app.rag.retrieval as retrieval

    _, store = replacement_environment
    store.add_texts(
        ["MANAGE 4.3: Active instructions.", "MANAGE 4.3: Pending instructions."],
        metadatas=[
            {"topic": "appliances", "subtopic": "dishwashers"},
            {"topic": "finance", "subtopic": "budgeting", "replacement_pending": True},
        ],
        ids=["active", "pending"],
    )
    question = "What does MANAGE 4.3 require?"
    assert retrieval.find_reference_topics(question, ["appliances", "finance"]) == [
        ("MANAGE 4.3", "appliances"),
    ]
    assert retrieval.find_reference_topics("What does MANAGE 4.4 require?", ["appliances", "finance"]) == []
    store.add_texts(
        ["MANAGE 4.3: Other active instructions."],
        metadatas=[{"topic": "finance", "subtopic": "budgeting"}],
        ids=["other"],
    )
    assert retrieval.find_reference_topics(question, ["appliances", "finance"]) == []


def test_topic_router_includes_unique_indexed_section_hint(monkeypatch):
    from types import SimpleNamespace
    import app.routers.topic_router as topic_router

    prompts = []

    class FakeLLM:
        def invoke(self, messages):
            prompts.append(messages[0][1])
            return SimpleNamespace(
                topics=["artificial_intelligence"], topic_questions=[], is_ambiguous=False,
                confidence=0.9, reasoning="The reference matches an indexed topic.",
            )

    monkeypatch.setattr(topic_router, "build_topic_llm", lambda: FakeLLM())
    monkeypatch.setattr(topic_router, "taxonomy_store", lambda: SimpleNamespace(
        get=lambda: {"artificial_intelligence": ["risk_management"]},
    ))
    monkeypatch.setattr(topic_router, "find_reference_topics", lambda question, topics: [
        ("MANAGE 4.3", "artificial_intelligence"),
    ])
    result = topic_router.classify_topic({"question": "What does MANAGE 4.3 require?"})
    assert result["selected_topics"] == ["artificial_intelligence"]
    assert '["MANAGE 4.3", "artificial_intelligence"]' in prompts[0]


def test_force_reindex_same_content_keeps_old_version_until_published(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    content = b"Original dishwasher instructions."
    document_id = _upload_test_version(content).json()["document_id"]
    old = registry.get(document_id)
    observed = []
    add_documents = store.add_documents

    def observe_during_index(documents, **kwargs):
        result = add_documents(documents, **kwargs)
        if documents[0].metadata.get("replacement_pending"):
            observed.extend(retrieval.retrieve("dishwasher", "appliances", "dishwashers"))
        return result

    monkeypatch.setattr(store, "add_documents", observe_during_index)
    response = client.post(f"/knowledge/documents/{document_id}/reindex", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["pending"]["version"] == 2
    assert observed[0]["version"] == 1
    current = registry.get(document_id)
    assert current["status"] == "indexed"
    assert current["version"] == 2
    assert current["content_hash"] == old["content_hash"]
    assert store.get(ids=old["chunk_ids"])["ids"] == []
    assert retrieval.retrieve("dishwasher", "appliances", "dishwashers")[0]["version"] == 2
    assert _upload_test_version(content).json()["duplicate"] is True


def test_force_reindex_rejects_pending_and_missing_original(replacement_environment, monkeypatch):
    import app.api.main as api

    registry, _ = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    record = registry.get(document_id)
    registry.update(document_id, status="needs_review", pending={"version": 2})
    assert client.post(f"/knowledge/documents/{document_id}/reindex", headers=_auth_headers()).status_code == 409
    registry.update(document_id, status="indexed", pending=None)
    monkeypatch.setattr(api._document_storage, "read_original", lambda *args: (_ for _ in ()).throw(FileNotFoundError()))
    assert client.post(f"/knowledge/documents/{document_id}/reindex", headers=_auth_headers()).status_code == 409
    assert registry.get(document_id)["version"] == record["version"]
    assert registry.get(document_id)["status"] == "indexed"


def test_force_reindex_failure_keeps_published_chunks(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    old_ids = registry.get(document_id)["chunk_ids"]
    monkeypatch.setattr(store, "similarity_search", lambda *args, **kwargs: [])
    assert client.post(f"/knowledge/documents/{document_id}/reindex", headers=_auth_headers()).status_code == 200
    failed = registry.get(document_id)
    assert failed["status"] == "failed"
    assert failed["version"] == 1
    assert failed["chunk_ids"] == old_ids
    assert "validate_retrieval" in failed["error"]
    assert retrieval.retrieve("dishwasher", "appliances", "dishwashers")[0]["version"] == 1


def test_changed_upload_keeps_old_version_until_new_version_is_published(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    first = _upload_test_version(b"Original dishwasher instructions.")
    document_id = first.json()["document_id"]
    original = registry.get(document_id)
    assert original["status"] == "indexed"
    old_ids = original["chunk_ids"]
    assert _upload_test_version(b"Original dishwasher instructions.").json()["duplicate"] is True
    monkeypatch.setattr(
        ingestion_graph, "classify_document",
        lambda filename, text: DocumentClassification(
            topic="finance", subtopic="budgeting", chapters=["budget"], confidence=0.95,
        ),
    )
    add_documents = store.add_documents
    observed = []

    def observe_during_index(documents, **kwargs):
        result = add_documents(documents, **kwargs)
        if documents[0].metadata.get("replacement_pending"):
            observed.append((
                retrieval.retrieve("instructions", "appliances", "dishwashers"),
                retrieval.retrieve("instructions", "finance", "budgeting"),
                retrieval.retrieve("instructions", "finance", retrieval_mode="hybrid", candidate_pool_size=40),
                retrieval._has_uploaded_content("finance", "budgeting"),
            ))
        return result

    monkeypatch.setattr(store, "add_documents", observe_during_index)
    response = _upload_test_version(b"Updated budgeting instructions.")
    assert response.status_code == 200
    assert response.json()["document_id"] == document_id
    assert response.json()["pending"]["version"] == 2
    assert observed and observed[0][0][0]["text"] == "Original dishwasher instructions."
    assert observed[0][1] == []
    assert observed[0][2] == []
    assert observed[0][3] is False
    current = registry.get(document_id)
    assert current["status"] == "indexed", current["error"]
    assert current["version"] == 2
    assert current["topic"] == "finance"
    assert current["pending"] is None
    assert store.get(ids=old_ids)["ids"] == []
    assert retrieval.retrieve("instructions", "appliances", "dishwashers") == []
    assert retrieval.retrieve("instructions", "finance", "budgeting")[0]["text"] == "Updated budgeting instructions."
    assert len(registry.list_documents()) == 1


def test_replacement_awaiting_review_keeps_old_version_until_approved(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    old_ids = registry.get(document_id)["chunk_ids"]
    monkeypatch.setattr(
        ingestion_graph, "classify_document",
        lambda filename, text: DocumentClassification(
            topic="appliances", subtopic="dishwashers", chapters=["manual"], confidence=0.4,
        ),
    )
    _upload_test_version(b"Updated dishwasher instructions.")
    waiting = registry.get(document_id)
    assert waiting["status"] == "needs_review"
    assert waiting["version"] == 1
    assert waiting["pending"]["version"] == 2
    assert waiting["chunk_ids"] == old_ids
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Original dishwasher instructions."
    assert _upload_test_version(b"Another replacement.").status_code == 409
    response = client.post(
        f"/knowledge/documents/{document_id}/classification",
        json={"topic": "appliances", "subtopic": "dishwashers"}, headers=_auth_headers(),
    )
    assert response.status_code == 200
    updated = registry.get(document_id)
    assert updated["status"] == "indexed", updated["error"]
    assert updated["version"] == 2
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Updated dishwasher instructions."
    assert store.get(ids=old_ids)["ids"] == []


def test_failed_replacement_preserves_old_index_and_allows_retry(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    old_ids = registry.get(document_id)["chunk_ids"]
    original_search = store.similarity_search
    monkeypatch.setattr(store, "similarity_search", lambda *args, **kwargs: [])
    _upload_test_version(b"Updated dishwasher instructions.")
    failed = registry.get(document_id)
    assert failed["status"] == "failed"
    assert failed["version"] == 1
    assert failed["chunk_ids"] == old_ids
    assert "validate_retrieval" in failed["error"]
    assert store.get(where={"version": 2})["ids"] == []
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Original dishwasher instructions."
    monkeypatch.setattr(store, "similarity_search", original_search)
    _upload_test_version(b"Updated dishwasher instructions.")
    updated = registry.get(document_id)
    assert updated["status"] == "indexed", updated["error"]
    assert updated["version"] == 3
    assert store.get(ids=old_ids)["ids"] == []


def test_failed_replacement_cleanup_is_reserved_and_retryable(replacement_environment, monkeypatch):
    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    original_search = store.similarity_search
    monkeypatch.setattr(store, "similarity_search", lambda *args, **kwargs: [])
    _upload_test_version(b"Updated dishwasher instructions.")
    monkeypatch.setattr(store, "similarity_search", original_search)
    original_get = store.get

    def fail_cleanup(*args, **kwargs):
        assert registry.get(document_id)["status"] == "processing"
        raise RuntimeError("cleanup unavailable")

    monkeypatch.setattr(store, "get", fail_cleanup)
    assert _upload_test_version(b"Updated dishwasher instructions.").status_code == 503
    failed = registry.get(document_id)
    assert failed["pending"]["abandoned_versions"] == [2]
    assert failed["version"] == 1
    monkeypatch.setattr(store, "get", original_get)
    assert _upload_test_version(b"Updated dishwasher instructions.").status_code == 200
    assert registry.get(document_id)["version"] == 4


def test_interrupted_replacement_is_retryable_after_restart(replacement_environment):
    import app.rag.retrieval as retrieval
    from langchain_core.documents import Document

    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    assert registry.begin_replacement(document_id, 1, {"version": 2, "content_hash": "interrupted"})
    store.add_documents(
        [Document(page_content="Interrupted replacement", metadata={
            "topic": "appliances", "subtopic": "dishwashers", "document_id": document_id,
            "version": 2, "replacement_pending": True, "chapter_id": "manual",
        })],
        ids=["interrupted-2"],
    )
    registry.recover_interrupted_replacements()
    assert registry.get(document_id)["status"] == "failed"
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Original dishwasher instructions."
    _upload_test_version(b"Updated dishwasher instructions.")
    assert registry.get(document_id)["version"] == 3
    assert store.get(ids=["interrupted-2"])["ids"] == []


def test_cleanup_failure_hides_old_version_and_retries(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, store = replacement_environment
    document_id = _upload_test_version(b"Original dishwasher instructions.").json()["document_id"]
    old_ids = registry.get(document_id)["chunk_ids"]
    original_delete = store.delete

    def fail_old_delete(ids, **kwargs):
        if ids == old_ids:
            raise RuntimeError("cleanup unavailable")
        return original_delete(ids=ids, **kwargs)

    monkeypatch.setattr(store, "delete", fail_old_delete)
    _upload_test_version(b"Updated dishwasher instructions.")
    current = registry.get(document_id)
    assert current["version"] == 2
    assert current["cleanup_ids"] == old_ids
    assert "cleanup failed" in current["error"]
    assert store.get(ids=old_ids)["ids"] == old_ids
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Updated dishwasher instructions."
    monkeypatch.setattr(store, "delete", original_delete)
    response = _upload_test_version(b"Updated dishwasher instructions.")
    assert response.json()["duplicate"] is True
    assert registry.get(document_id)["cleanup_ids"] == []
    assert store.get(ids=old_ids)["ids"] == []


def test_retrieval_keeps_unregistered_legacy_documents_visible(replacement_environment):
    import app.rag.retrieval as retrieval
    from langchain_core.documents import Document

    _, store = replacement_environment
    store.add_documents(
        [Document(page_content="Legacy indexed text", metadata={
            "topic": "appliances", "subtopic": "dishwashers", "document_id": "DOC-legacy",
            "version": 1, "ingested": True, "chapter_id": "legacy",
        })],
        ids=["legacy-1"],
    )
    assert retrieval.retrieve("legacy", "appliances", "dishwashers")[0]["text"] == "Legacy indexed text"


def test_standalone_retrieval_uses_configured_persistent_registry(replacement_environment, monkeypatch):
    import app.rag.retrieval as retrieval

    registry, _ = replacement_environment
    _upload_test_version(b"Original dishwasher instructions.")
    _upload_test_version(b"Updated dishwasher instructions.")
    monkeypatch.setattr(retrieval, "_registry_provider", None)
    monkeypatch.setenv("CHAT_DB_URL", "configured-test-database")
    monkeypatch.setattr(retrieval, "_standalone_registry", lambda connection: registry)
    assert retrieval.retrieve("instructions", "appliances", "dishwashers")[0]["text"] == "Updated dishwasher instructions."


def test_hybrid_retrieval_refreshes_after_replacement(replacement_environment):
    import app.rag.retrieval as retrieval

    retrieval._bm25_retriever.cache_clear()
    _upload_test_version(b"Original dishwasher instructions.")
    assert retrieval.retrieve("dishwasher", "appliances", "dishwashers", retrieval_mode="hybrid")[0]["text"] == "Original dishwasher instructions."
    _upload_test_version(b"Updated dishwasher instructions.")
    assert retrieval.retrieve("dishwasher", "appliances", "dishwashers", retrieval_mode="hybrid")[0]["text"] == "Updated dishwasher instructions."
    retrieval._bm25_retriever.cache_clear()
