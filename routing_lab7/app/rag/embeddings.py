"""Embeddings.

Wraps `langchain_openai.OpenAIEmbeddings` with `app.config.EMBEDDING_MODEL`
(`text-embedding-3-small`) so `retrieval.py` and `scripts/build_index.py`
share one embeddings client configuration. Wrapped in `app.cache.CachedEmbeddings`
(unless disabled via `ROUTING_LAB_CACHE_ENABLED=0`) so repeated embedding
calls for the same text aren't billed twice.

`get_embeddings_client()` used to be `@lru_cache`d (built once per
process) - removed when LiteLLM per-user routing
(instructions/learnings/routing-lab-prod-plan.md section 2.3,
app/llm_gateway.py) was added: a cached client would freeze in whichever
user's virtual key happened to be active the first time this was ever
called, and every other user's embedding calls would then silently bill
against that first user's key/budget instead of their own. Constructing
`OpenAIEmbeddings` is cheap (no network call happens at construction
time), so this costs negligible performance for real correctness.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app import llm_gateway
from app.cache import CACHE_ENABLED, CachedEmbeddings, ValidatedEmbeddings
from app.config import EMBEDDING_MODEL


def get_embeddings_client() -> Embeddings:
    client = OpenAIEmbeddings(model=EMBEDDING_MODEL, **llm_gateway.llm_kwargs())
    if CACHE_ENABLED:
        return ValidatedEmbeddings(CachedEmbeddings(client, model_name=EMBEDDING_MODEL))
    return ValidatedEmbeddings(client)
