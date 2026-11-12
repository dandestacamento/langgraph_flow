"""Embeddings.

Wraps `langchain_openai.OpenAIEmbeddings` with `app.config.EMBEDDING_MODEL`
(`text-embedding-3-small`) so `retrieval.py` and `scripts/build_index.py`
share one embeddings client configuration.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embeddings_client() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)
