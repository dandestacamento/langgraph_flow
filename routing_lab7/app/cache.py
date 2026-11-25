"""Caching layer for LLM and embedding API calls, to avoid paying for
identical repeated calls across development/test iterations - this is the
single biggest lever for controlling API cost in this project, since
re-running a test suite after an unrelated change re-asks the exact same
questions with the exact same (deterministic, temperature=0) prompts.

- LLM calls (ChatOpenAI): cached via LangChain's built-in `SQLiteCache`
  (`langchain_community`), enabled globally once via `enable_llm_cache()`.
- Embedding calls (OpenAIEmbeddings): no built-in equivalent at the
  installed langchain-community version (`CacheBackedEmbeddings` lives in
  the full `langchain` package, which isn't installed here) - `CachedEmbeddings`
  below is a small, dependency-free substitute backed by the same SQLite
  file, since an embedding vector (a flat list[float]) is trivial to
  serialize, unlike the complex Generation objects an LLM cache stores.

Both caches persist across process restarts (unlike an in-memory cache),
so repeated pytest runs of the same questions become free after the first
real run. Enabled by default; set ROUTING_LAB_CACHE_ENABLED=0 to force
fresh calls - e.g. after changing a prompt, since the cache key is just
the literal prompt/question text, not aware of which code version
produced a given cached response.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3

from langchain_core.embeddings import Embeddings

from app.config import PROJECT_ROOT

CACHE_DB_PATH = PROJECT_ROOT / ".llm_cache.db"
CACHE_ENABLED = os.environ.get("ROUTING_LAB_CACHE_ENABLED", "1") != "0"

_llm_cache_enabled = False


def validate_embeddings(vectors: object, expected_count: int) -> list[list[float]]:
    """Reject malformed vectors before they can be cached or indexed."""
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ValueError(f"Invalid embedding response: expected {expected_count} vectors")
    dimension = None
    for index, vector in enumerate(vectors):
        if not isinstance(vector, list) or not vector:
            raise ValueError(f"Invalid embedding vector at index {index}: expected a non-empty list")
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ValueError(f"Invalid embedding dimension at index {index}")
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Invalid embedding value at index {index}: expected a finite number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"Invalid embedding value at index {index}: expected a finite number")
    return vectors


class ValidatedEmbeddings(Embeddings):
    """Validate embedding responses whether or not caching is enabled."""

    def __init__(self, underlying: Embeddings):
        self._underlying = underlying

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return validate_embeddings(self._underlying.embed_documents(texts), len(texts))

    def embed_query(self, text: str) -> list[float]:
        return validate_embeddings([self._underlying.embed_query(text)], 1)[0]


def enable_llm_cache() -> bool:
    """Enable the persistent SQLite cache for every ChatOpenAI call made
    through LangChain, process-wide. Call once at startup (app.main,
    tests/conftest.py, scripts/*, the dashboard) - safe to call more than
    once. Returns whether caching is actually active."""
    global _llm_cache_enabled
    if not CACHE_ENABLED:
        return False
    if not _llm_cache_enabled:
        import warnings

        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache

        # Cosmetic only: SQLiteCache warns that a future langchain-community
        # version will require an explicit `allowed_objects` allowlist for
        # cache deserialization. This cache only ever stores/reads our own
        # process's chat responses (never untrusted external input), so the
        # warning doesn't indicate a real risk here - just silence the noise.
        warnings.filterwarnings(
            "ignore", message=".*allowed_objects.*", category=Warning
        )

        CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        set_llm_cache(SQLiteCache(database_path=str(CACHE_DB_PATH)))
        _llm_cache_enabled = True
    return True


class CachedEmbeddings(Embeddings):
    """Wraps an `Embeddings` client with a persistent SQLite cache keyed
    by (model name, text) - repeated embedding calls for the same query
    or chunk (e.g. re-running `scripts/build_index.py` or a retrieval
    test) are served from the cache instead of billed again."""

    def __init__(self, underlying: Embeddings, model_name: str):
        self._underlying = underlying
        self._model_name = model_name
        self._init_db()

    def _init_db(self) -> None:
        CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(CACHE_DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS embedding_cache (key TEXT PRIMARY KEY, vector TEXT NOT NULL)"
            )

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self._model_name}::{text}".encode("utf-8")).hexdigest()

    def _get_cached(self, text: str) -> list[float] | None:
        with sqlite3.connect(CACHE_DB_PATH) as conn:
            row = conn.execute(
                "SELECT vector FROM embedding_cache WHERE key = ?", (self._key(text),)
            ).fetchone()
        if row is None:
            return None
        try:
            vector = json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid cached embedding: malformed JSON") from exc
        try:
            return validate_embeddings([vector], 1)[0]
        except ValueError as exc:
            raise ValueError(f"Invalid cached embedding: {exc}") from exc

    def _set_cached(self, text: str, vector: list[float]) -> None:
        with sqlite3.connect(CACHE_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache (key, vector) VALUES (?, ?)",
                (self._key(text), json.dumps(vector)),
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [self._get_cached(t) for t in texts]
        missing_indices = [i for i, r in enumerate(results) if r is None]
        if missing_indices:
            fresh = validate_embeddings(
                self._underlying.embed_documents([texts[i] for i in missing_indices]),
                len(missing_indices),
            )
            for i, vector in zip(missing_indices, fresh):
                results[i] = vector
        validated = validate_embeddings([vector for vector in results if vector is not None], len(texts))
        for i in missing_indices:
            self._set_cached(texts[i], validated[i])
        return validated

    def embed_query(self, text: str) -> list[float]:
        cached = self._get_cached(text)
        if cached is not None:
            return cached
        vector = validate_embeddings([self._underlying.embed_query(text)], 1)[0]
        self._set_cached(text, vector)
        return vector
