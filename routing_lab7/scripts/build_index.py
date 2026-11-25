"""Vector index build: Level 4 (RAG retrieval), now incremental.

Loads every chapter via `app.rag.ingestion.load_knowledge_base_documents`,
splits them into chunks via `app.rag.chunking`, embeds them, and persists
the result to a local Chroma collection under `routing_lab2/.chroma/`
(see `app.config.CHROMA_PERSIST_DIR`).

Incremental by default (see `app/rag/manifest.py` and
instructions/learnings/routing-lab2-learnings.md section 4, P2): a
manifest tracks each chapter file's mtime/size plus the chunk ids it
produced, so only chapters that were actually added, modified, or deleted
since the last run are re-chunked/re-embedded/replaced in the index -
everything else is left untouched, and a rerun with no content changes is
a true no-op. Falls back to a full rebuild if there's no manifest yet (an
index built before this feature existed), the knowledge base's chunking
strategy or embedding model changed (`INGEST_SIGNATURE` - old chunk ids
would no longer line up with current chunk boundaries/vectors), or
`--rebuild` is passed explicitly. Full rebuilds preserve uploaded
documents and stop if their existing index signature is unknown or changed.

Usage:
    python scripts/build_index.py              # incremental (default)
    python scripts/build_index.py --rebuild     # force a full rebuild
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from app.config import (  # noqa: E402
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    KNOWLEDGE_BASE_DIR,
)
from app.rag.chunking import chunk_all_documents, chunk_document  # noqa: E402
from app.rag.embeddings import get_embeddings_client  # noqa: E402
from app.rag.ingestion import load_knowledge_base_documents  # noqa: E402
from app.rag.manifest import load_manifest, save_manifest, scan_chapter_stats  # noqa: E402

MANIFEST_PATH = CHROMA_PERSIST_DIR / "manifest.json"

# Bumped (by changing this string) whenever a change to chunking.py's
# splitting logic or EMBEDDING_MODEL would make previously-computed chunk
# ids/vectors stale - any change forces a full rebuild instead of silently
# leaving chunks from the old logic mixed in with the new ones.
INGEST_SIGNATURE = f"paragraph:{EMBEDDING_MODEL}"


def _relative_path(path_str: str) -> str:
    return str(Path(path_str).resolve().relative_to(KNOWLEDGE_BASE_DIR.resolve())).replace("\\", "/")


def _chunk_ids(chunks: list[dict]) -> list[str]:
    return [f"{c['document_id']}:{c['chapter_id']}:{c['chunk_index']}" for c in chunks]


def _to_langchain_documents(chunks: list[dict]) -> list[Document]:
    return [
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


def _get_store() -> Chroma:
    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embeddings_client(),
        persist_directory=str(CHROMA_PERSIST_DIR),
    )


def _full_rebuild(
    store: Chroma, documents: list[dict], current_stats: dict[str, dict], manifest: dict,
) -> None:
    chunks = chunk_all_documents(documents)
    print(f"Loaded {len(documents)} chapters -> {len(chunks)} chunks")

    ids = _chunk_ids(chunks)

    chunk_ids_by_path: dict[str, list[str]] = defaultdict(list)
    for chunk, chunk_id in zip(chunks, ids):
        chunk_ids_by_path[_relative_path(chunk["path"])].append(chunk_id)

    manifest_files = {
        rel: {**current_stats[rel], "chunk_ids": chunk_ids}
        for rel, chunk_ids in chunk_ids_by_path.items()
    }

    existing = store.get(include=["metadatas"])
    existing_ids = existing["ids"]
    metadatas = existing["metadatas"]
    if metadatas is None or len(metadatas) != len(existing_ids):
        raise RuntimeError("Cannot rebuild: existing vector metadata is unavailable.")
    known_curated_ids = set(ids)
    for entry in manifest.get("files", {}).values():
        known_curated_ids.update(entry["chunk_ids"])
    uploaded_ids = set()
    curated_ids = []
    for chunk_id, metadata in zip(existing_ids, metadatas):
        if metadata and metadata.get("ingested") is True:
            uploaded_ids.add(chunk_id)
        elif not metadata or "source" in metadata or chunk_id not in known_curated_ids:
            raise RuntimeError("Cannot rebuild: unrecognized vector records require investigation.")
        else:
            curated_ids.append(chunk_id)
    if uploaded_ids & known_curated_ids:
        raise RuntimeError("Cannot rebuild: uploaded and curated vector IDs overlap.")
    if uploaded_ids and manifest.get("ingest_signature") != INGEST_SIGNATURE:
        raise RuntimeError(
            "Cannot rebuild: uploaded vectors have an unknown or changed embedding/index signature. "
            "Use a separate index and migrate the uploads before changing the signature."
        )

    save_manifest(MANIFEST_PATH, {**manifest, "rebuild_in_progress": True})
    if curated_ids:
        store.delete(ids=curated_ids)
    store.add_documents(_to_langchain_documents(chunks), ids=ids)
    save_manifest(
        MANIFEST_PATH,
        {"version": 1, "ingest_signature": INGEST_SIGNATURE, "files": manifest_files},
    )
    print(
        f"Indexed {len(chunks)} chunks into Chroma collection "
        f"'{CHROMA_COLLECTION_NAME}' at {CHROMA_PERSIST_DIR}"
    )


def _incremental_update(
    store: Chroma,
    manifest_files: dict[str, dict],
    current_stats: dict[str, dict],
) -> None:
    changed = sorted(
        rel
        for rel, stat in current_stats.items()
        if rel not in manifest_files
        or manifest_files[rel]["mtime_ns"] != stat["mtime_ns"]
        or manifest_files[rel]["size"] != stat["size"]
    )
    deleted = sorted(set(manifest_files) - set(current_stats))

    if not changed and not deleted:
        total_chunks = sum(len(f["chunk_ids"]) for f in manifest_files.values())
        print(f"No chapters changed - index already up to date ({total_chunks} chunks).")
        return

    print(f"Incremental update: {len(changed)} changed/added, {len(deleted)} deleted chapter(s).")

    documents_by_path = {_relative_path(doc["path"]): doc for doc in load_knowledge_base_documents()}

    ids_to_delete: list[str] = []
    ids_to_add: list[str] = []
    docs_to_add: list[Document] = []
    next_files = dict(manifest_files)

    for rel in changed:
        ids_to_delete.extend(manifest_files.get(rel, {}).get("chunk_ids", []))
        chunks = chunk_document(documents_by_path[rel])
        new_ids = _chunk_ids(chunks)
        ids_to_add.extend(new_ids)
        docs_to_add.extend(_to_langchain_documents(chunks))
        next_files[rel] = {**current_stats[rel], "chunk_ids": new_ids}

    for rel in deleted:
        ids_to_delete.extend(manifest_files.get(rel, {}).get("chunk_ids", []))
        next_files.pop(rel, None)

    if ids_to_delete:
        store.delete(ids=sorted(set(ids_to_delete)))
    if docs_to_add:
        store.add_documents(docs_to_add, ids=ids_to_add)

    save_manifest(
        MANIFEST_PATH,
        {"version": 1, "ingest_signature": INGEST_SIGNATURE, "files": next_files},
    )
    print(
        f"Added/replaced {len(ids_to_add)} chunk(s) across {len(changed)} changed chapter(s), "
        f"removed {len(ids_to_delete)} stale chunk(s) ({len(deleted)} chapter(s) fully deleted)."
    )


def main(force_rebuild: bool = False) -> None:
    store = _get_store()
    current_stats = scan_chapter_stats(KNOWLEDGE_BASE_DIR)
    manifest = load_manifest(MANIFEST_PATH)
    manifest_files = manifest.get("files", {})

    if manifest.get("rebuild_in_progress"):
        reason = "previous rebuild was interrupted"
    elif force_rebuild:
        reason = "--rebuild flag"
    elif not manifest_files:
        reason = "no manifest found"
    elif manifest.get("ingest_signature") != INGEST_SIGNATURE:
        reason = f"ingest signature changed ({manifest.get('ingest_signature')!r} -> {INGEST_SIGNATURE!r})"
    else:
        reason = None

    if reason is not None:
        print(f"Full rebuild ({reason}).")
        _full_rebuild(store, load_knowledge_base_documents(), current_stats, manifest)
        return

    _incremental_update(store, manifest_files, current_stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--rebuild", action="store_true", help="Force a curated-index rebuild while preserving uploads."
    )
    args = parser.parse_args()
    main(force_rebuild=args.rebuild)
