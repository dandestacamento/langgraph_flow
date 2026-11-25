from __future__ import annotations

import sqlite3

import pytest
from langchain_core.embeddings import Embeddings

import app.cache as cache
import app.rag.embeddings as embeddings


class FakeEmbeddings(Embeddings):
    def __init__(self, documents, query):
        self.documents = documents
        self.query = query
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return self.documents

    def embed_query(self, text):
        self.calls += 1
        return self.query


@pytest.mark.parametrize(
    "vectors",
    [[[1.0, 2.0]], [[1.0], [1.0], [1.0]], [[1.0, 2.0], []], [[1.0, 2.0], [float("nan"), 1.0]],
     [[1.0, 2.0], [1.0]], [[1.0, 2.0], [True, 1.0]]],
)
def test_invalid_embedding_batch_fails_without_partial_cache(monkeypatch, tmp_path, vectors):
    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "cache.db")
    client = cache.CachedEmbeddings(FakeEmbeddings(vectors, [1.0, 2.0]), "test")
    with pytest.raises(ValueError, match="embedding"):
        client.embed_documents(["first", "second"])
    with sqlite3.connect(cache.CACHE_DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0] == 0


def test_cache_hits_and_fresh_vectors_are_validated_together(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "cache.db")
    provider = FakeEmbeddings([[1.0, 2.0]], [1.0, 2.0])
    client = cache.CachedEmbeddings(provider, "test")
    assert client.embed_query("first") == [1.0, 2.0]
    assert client.embed_documents(["first", "second"]) == [[1.0, 2.0], [1.0, 2.0]]
    provider.documents = [[1.0, 2.0, 3.0]]
    with pytest.raises(ValueError, match="dimension"):
        client.embed_documents(["first", "third"])
    assert client._get_cached("third") is None


@pytest.mark.parametrize("stored", ['not json', '[]', '[1, null]', '[1, NaN]'])
def test_invalid_cached_vector_is_reported_without_provider_fallback(monkeypatch, tmp_path, stored):
    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "cache.db")
    provider = FakeEmbeddings([[1.0]], [1.0])
    client = cache.CachedEmbeddings(provider, "test")
    with sqlite3.connect(cache.CACHE_DB_PATH) as conn:
        conn.execute("INSERT INTO embedding_cache VALUES (?, ?)", (client._key("private"), stored))
    with pytest.raises(ValueError, match="embedding"):
        client.embed_query("private")
    assert provider.calls == 0


def test_embedding_validation_also_applies_without_cache(monkeypatch):
    provider = FakeEmbeddings([[1.0], [1.0, 2.0]], [float("inf")])
    monkeypatch.setattr(embeddings, "CACHE_ENABLED", False)
    monkeypatch.setattr(embeddings, "OpenAIEmbeddings", lambda **kwargs: provider)
    client = embeddings.get_embeddings_client()
    with pytest.raises(ValueError, match="dimension"):
        client.embed_documents(["first", "second"])
    with pytest.raises(ValueError, match="embedding"):
        client.embed_query("query")


def test_invalid_embedding_prevents_document_publication(monkeypatch, tmp_path):
    import chromadb
    from langchain_chroma import Chroma

    import app.ingestion.graph as ingestion
    from app.ingestion.registry import DocumentRegistry

    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "cache.db")
    provider = FakeEmbeddings([[float("nan")]], [1.0])
    store = Chroma(
        client=chromadb.Client(), collection_name="invalid_embedding_test",
        embedding_function=cache.ValidatedEmbeddings(cache.CachedEmbeddings(provider, "test")),
    )
    monkeypatch.setattr(ingestion, "get_vector_store", lambda: store)
    content = b"Example document about dishwasher maintenance."
    registry = DocumentRegistry()
    record = registry.create(
        filename="manual.txt", media_type="text/plain", size_bytes=len(content),
        content_hash="test", uploaded_by="tester",
    )
    ingestion.run_ingestion(
        registry, record, content, manual_topic="appliances", manual_subtopic="dishwashers"
    )
    detail = registry.get(record["document_id"])
    assert detail["status"] == "failed"
    assert "embedding" in detail["error"]
    assert store.get()["ids"] == []
