"""Vector index build: Level 4 (RAG retrieval).

Loads every chapter via `app.rag.ingestion.load_knowledge_base_documents`,
splits them into chunks via `app.rag.chunking.chunk_all_documents`,
embeds them, and persists the result to a local Chroma collection under
`routing/.chroma/` (see `app.config.CHROMA_PERSIST_DIR`).

Idempotent: deletes and recreates the collection each run, so re-running
after editing `scripts/generate_knowledge_base.py` + regenerating the
knowledge base always reflects the current content exactly (no stale
chunks left behind from a previous version of a chapter).

Usage:
    python scripts/build_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from app.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR  # noqa: E402
from app.rag.chunking import chunk_all_documents  # noqa: E402
from app.rag.embeddings import get_embeddings_client  # noqa: E402
from app.rag.ingestion import load_knowledge_base_documents  # noqa: E402


def main() -> None:
    documents = load_knowledge_base_documents()
    chunks = chunk_all_documents(documents)
    print(f"Loaded {len(documents)} chapters -> {len(chunks)} chunks")

    langchain_docs = [
        Document(
            page_content=chunk["text"],
            metadata={
                "topic": chunk["topic"],
                "subtopic": chunk["subtopic"],
                "chapter_id": chunk["chapter_id"],
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
            },
        )
        for chunk in chunks
    ]
    ids = [f"{c['document_id']}:{c['chapter_id']}:{c['chunk_index']}" for c in chunks]

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    store = Chroma(
        collection_name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embeddings_client(),
        persist_directory=str(CHROMA_PERSIST_DIR),
    )
    # Rebuild from scratch each run so stale chunks from an older version
    # of the knowledge base never linger in the index.
    existing_ids = store.get()["ids"]
    if existing_ids:
        store.delete(ids=existing_ids)

    store.add_documents(langchain_docs, ids=ids)
    print(f"Indexed {len(langchain_docs)} chunks into Chroma collection "
          f"'{CHROMA_COLLECTION_NAME}' at {CHROMA_PERSIST_DIR}")


if __name__ == "__main__":
    main()
