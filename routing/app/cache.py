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
import os
import sqlite3

from langchain_core.embeddings import Embeddings

from app.config import PROJECT_ROOT

CACHE_DB_PATH = PROJECT_ROOT / ".llm_cache.db"
CACHE_ENABLED = os.environ.get("ROUTING_LAB_CACHE_ENABLED", "1") != "0"

_llm_cache_enabled = False


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
        return json.loads(row[0]) if row else None

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
            fresh = self._underlying.embed_documents([texts[i] for i in missing_indices])
            for i, vector in zip(missing_indices, fresh):
                results[i] = vector
                self._set_cached(texts[i], vector)
        return results  # type: ignore[return-value]

    def embed_query(self, text: str) -> list[float]:
        cached = self._get_cached(text)
        if cached is not None:
            return cached
        vector = self._underlying.embed_query(text)
        self._set_cached(text, vector)
        return vector
