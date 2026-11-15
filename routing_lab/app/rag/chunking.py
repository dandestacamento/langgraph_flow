"""Markdown-aware chunking.

Splits each chapter's body (as loaded by `ingestion.load_knowledge_base_documents`)
into paragraph-level chunks along blank-line boundaries. The knowledge base
chapters are short (one or two paragraphs each - see
`scripts/generate_knowledge_base.py`), so most chapters produce 1-2 chunks;
this is enough to be a real chunking step (not a no-op) without needing a
token-aware splitter for content this size.

Every chunk inherits the chapter's full metadata (topic, subtopic,
chapter_id, document_id, version, title) plus its own `chunk_index`, so a
retrieved chunk can always be traced back to its exact source chapter -
the citation requirement from
instructions/Langgraph_routing/7_to_8_routing_configuration.md section 3.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")

# Metadata keys from ingestion.load_knowledge_base_documents() that belong
# on every chunk; "body" and "preview" are chapter-level, not chunk-level.
_METADATA_KEYS = ("topic", "subtopic", "chapter_id", "document_id", "version", "title", "path")


def chunk_document(document: dict) -> list[dict]:
    """Split one chapter document (as returned by
    `ingestion.load_knowledge_base_documents`) into chunks, each a dict
    with `text`, `chunk_index`, and the chapter's metadata."""
    metadata = {key: document[key] for key in _METADATA_KEYS if key in document}
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(document["body"]) if p.strip()]

    return [
        {**metadata, "chunk_index": i, "text": paragraph}
        for i, paragraph in enumerate(paragraphs)
    ]


def chunk_all_documents(documents: list[dict]) -> list[dict]:
    """Chunk every document in `documents`, flattened into one list."""
    chunks: list[dict] = []
    for document in documents:
        chunks.extend(chunk_document(document))
    return chunks
