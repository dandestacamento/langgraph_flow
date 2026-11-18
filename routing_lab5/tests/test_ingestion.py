"""Ingestion pipeline tests (chat-ui-plan5.md Phase A).

API-level tests follow tests/test_chat_api.py's conventions: the HTTP
layer via TestClient (which runs FastAPI background tasks synchronously
before returning - so an upload response means ingestion has finished),
auth against a locally generated RSA key, real LLM calls through the
shared response cache. Vector-store writes are cleaned up after each
end-to-end test so the curated index isn't polluted.
"""

from __future__ import annotations

from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import app.api.auth as auth_module
import app.ingestion.graph as ingestion_graph
from app.api.main import app
from app.ingestion.classify import DocumentClassification, classification_problem
from app.ingestion.graph import chunk_text
from app.ingestion.registry import DocumentRegistry
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


def test_chunk_text_merges_small_paragraphs_and_splits_large_content() -> None:
    small = "para one\n\npara two\n\npara three"
    assert chunk_text(small) == ["para one\n\npara two\n\npara three"]

    big_paragraphs = "\n\n".join(f"paragraph {i} " + "x" * 700 for i in range(4))
    chunks = chunk_text(big_paragraphs)
    assert len(chunks) == 4  # each ~700 chars: merging would exceed the target
    assert chunks[0].startswith("paragraph 0")


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
