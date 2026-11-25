from __future__ import annotations

import uuid

import chromadb
import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import scripts.build_index as build_index
from app.rag.manifest import load_manifest, save_manifest


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text):
        return [float(len(text)), 1.0]


@pytest.fixture
def index_setup(monkeypatch, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    chapter_path = kb / "chapter.md"
    chapter = {
        "document_id": "curated", "chapter_id": "chapter", "path": str(chapter_path),
        "topic": "appliances", "subtopic": "dishwashers", "body": "New curated text",
    }
    stats = {"chapter.md": {"mtime_ns": 10, "size": 20}}
    manifest_path = tmp_path / "manifest.json"
    store = Chroma(
        client=chromadb.Client(), collection_name=f"rebuild_{uuid.uuid4().hex}",
        embedding_function=FakeEmbeddings(),
    )
    store.add_documents(
        [
            Document(page_content="Old curated text", metadata={
                "document_id": "curated", "chapter_id": "chapter",
                "topic": "appliances", "subtopic": "dishwashers", "chunk_index": 0,
            }),
            Document(page_content="Uploaded manual", metadata={
                "document_id": "upload", "version": 1, "source": "manual.pdf",
                "ingested": True, "page": 2, "topic": "appliances", "subtopic": "dishwashers",
            }),
        ],
        ids=["curated:chapter:0", "upload:v1:0"],
    )
    manifest = {
        "version": 1, "ingest_signature": build_index.INGEST_SIGNATURE,
        "files": {"chapter.md": {**stats["chapter.md"], "chunk_ids": ["curated:chapter:0"]}},
    }
    save_manifest(manifest_path, manifest)
    monkeypatch.setattr(build_index, "KNOWLEDGE_BASE_DIR", kb)
    monkeypatch.setattr(build_index, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(build_index, "_get_store", lambda: store)
    monkeypatch.setattr(build_index, "scan_chapter_stats", lambda _: stats)
    monkeypatch.setattr(build_index, "load_knowledge_base_documents", lambda: [chapter])
    return store, manifest, manifest_path


def test_rebuild_preserves_uploaded_documents(index_setup):
    store, _, manifest_path = index_setup
    before = store.get(ids=["upload:v1:0"], include=["documents", "metadatas", "embeddings"])
    build_index.main(force_rebuild=True)
    after = store.get(ids=["upload:v1:0"], include=["documents", "metadatas", "embeddings"])
    assert after["documents"] == before["documents"]
    assert after["metadatas"] == before["metadatas"]
    assert after["embeddings"].tolist() == before["embeddings"].tolist()
    assert store.get(ids=["curated:chapter:0"])["documents"] == ["New curated text"]
    assert load_manifest(manifest_path)["files"]["chapter.md"]["chunk_ids"] == ["curated:chapter:0"]
    assert store.similarity_search("Uploaded manual", k=1, filter={"ingested": True})[0].page_content == "Uploaded manual"


@pytest.mark.parametrize("signature", [None, "paragraph:other-model"])
def test_incompatible_or_unknown_upload_embeddings_block_rebuild(index_setup, signature):
    store, manifest, manifest_path = index_setup
    manifest["ingest_signature"] = signature
    save_manifest(manifest_path, manifest)
    before = store.get(include=["documents", "metadatas"])
    with pytest.raises(RuntimeError, match="embedding|signature"):
        build_index.main(force_rebuild=True)
    assert store.get(include=["documents", "metadatas"]) == before
    assert load_manifest(manifest_path) == manifest


def test_unrecognized_records_block_rebuild_before_deletion(index_setup):
    store, _, _ = index_setup
    store.add_documents([Document(page_content="Unknown", metadata={"source": "external"})], ids=["unknown"])
    before = store.get(include=["documents", "metadatas"])
    with pytest.raises(RuntimeError, match="unrecognized"):
        build_index.main(force_rebuild=True)
    assert store.get(include=["documents", "metadatas"]) == before


def test_failed_curated_rebuild_does_not_remove_uploads(index_setup, monkeypatch):
    store, _, manifest_path = index_setup
    add_documents = store.add_documents

    def fail_add(*args, **kwargs):
        raise ValueError("embedding failure")
    monkeypatch.setattr(store, "add_documents", fail_add)
    with pytest.raises(ValueError, match="embedding failure"):
        build_index.main(force_rebuild=True)
    assert store.get(ids=["upload:v1:0"])["documents"] == ["Uploaded manual"]
    assert load_manifest(manifest_path)["rebuild_in_progress"] is True
    monkeypatch.setattr(store, "add_documents", add_documents)
    build_index.main()
    assert store.get(ids=["curated:chapter:0"])["documents"] == ["New curated text"]
    assert not load_manifest(manifest_path).get("rebuild_in_progress")


def test_missing_manifest_with_uploads_stops_automatic_rebuild(index_setup):
    store, _, manifest_path = index_setup
    before = store.get(include=["documents", "metadatas"])
    manifest_path.unlink()
    with pytest.raises(RuntimeError, match="signature"):
        build_index.main()
    assert store.get(include=["documents", "metadatas"]) == before
    assert not manifest_path.exists()


def test_upload_id_collision_stops_rebuild(index_setup):
    store, _, _ = index_setup
    store.add_documents(
        [Document(page_content="Uploaded", metadata={"ingested": True})],
        ids=["curated:chapter:0"],
    )
    before = store.get(include=["documents", "metadatas"])
    with pytest.raises(RuntimeError, match="overlap"):
        build_index.main(force_rebuild=True)
    assert store.get(include=["documents", "metadatas"]) == before


@pytest.mark.parametrize("old_signature", [None, "paragraph:other-model"])
def test_rebuild_still_works_without_uploaded_vectors(index_setup, old_signature):
    store, manifest, manifest_path = index_setup
    store.delete(ids=["upload:v1:0"])
    manifest["ingest_signature"] = old_signature
    save_manifest(manifest_path, manifest)
    build_index.main()
    assert store.get(ids=["curated:chapter:0"])["documents"] == ["New curated text"]
    assert load_manifest(manifest_path)["ingest_signature"] == build_index.INGEST_SIGNATURE
