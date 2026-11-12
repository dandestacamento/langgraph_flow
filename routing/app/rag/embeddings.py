"""Embeddings.

Wraps `langchain_openai.OpenAIEmbeddings` with `app.config.EMBEDDING_MODEL`
(`text-embedding-3-small`) so `retrieval.py` and `scripts/build_index.py`
share one embeddings client configuration. Wrapped in `app.cache.CachedEmbeddings`
(unless disabled via `ROUTING_LAB_CACHE_ENABLED=0`) so repeated embedding
calls for the same text aren't billed twice.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.cache import CACHE_ENABLED, CachedEmbeddings
from app.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embeddings_client() -> Embeddings:
    client = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    if CACHE_ENABLED:
        return CachedEmbeddings(client, model_name=EMBEDDING_MODEL)
    return client
