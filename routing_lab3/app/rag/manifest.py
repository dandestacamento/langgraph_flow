"""Change-detection manifest for incremental index updates.

Lets `scripts/build_index.py` skip re-chunking/re-embedding chapters that
haven't changed since the last run, instead of always doing a full
delete-everything/add-everything rebuild. Adapted from
reference/rag_krish/rag/manifest.py - see
instructions/learnings/routing-lab2-learnings.md section 4 (P2) for the
full reasoning - but deliberately simplified for this project:

- No per-chunk content hashing: this project's chunk ids are already
  stable per unchanged file (`{document_id}:{chapter_id}:{chunk_index}`,
  see `app/rag/chunking.py`), so a changed file's whole chunk set can just
  be replaced atomically - there's no need for rag_krish's
  content-addressed SHA-256 chunk_id scheme.
- No rename/move detection: the knowledge base is generated wholesale by
  `scripts/generate_knowledge_base.py`, not hand-edited file by file, so
  renames don't happen in practice - the FAISS-specific
  `index.reconstruct`-based vector-reuse trick this would require isn't
  worth porting here (it also doesn't map onto Chroma; see the learnings
  doc for the full comparison).
"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST_VERSION = 1


def scan_chapter_stats(knowledge_base_dir: Path) -> dict[str, dict]:
    """relative_path (posix-style, '/'-separated) -> {mtime_ns, size} for
    every *.md chapter file under knowledge_base_dir - a cheap stat-only
    pass so unchanged chapters can be recognized before any (comparatively
    expensive) parsing/chunking/embedding happens."""
    stats: dict[str, dict] = {}
    for path in sorted(knowledge_base_dir.rglob("*.md")):
        file_stat = path.stat()
        rel = str(path.relative_to(knowledge_base_dir)).replace("\\", "/")
        stats[rel] = {"mtime_ns": file_stat.st_mtime_ns, "size": file_stat.st_size}
    return stats


def load_manifest(path: Path) -> dict:
    """Returns {"version": ..., "ingest_signature": None, "files": {}} if
    no manifest exists yet (e.g. an index predating this feature) - the
    empty `files` dict is itself the signal `scripts/build_index.py` uses
    to fall back to a full rebuild."""
    if not path.exists():
        return {"version": MANIFEST_VERSION, "ingest_signature": None, "files": {}}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_manifest(path: Path, data: dict) -> None:
    """Write via a temp file + atomic replace so a crash mid-write (e.g.
    the process killed between the Chroma write and the manifest write)
    never leaves a corrupt/partial manifest.json behind - at worst, the
    old manifest is stale and the next run re-processes a few files it
    didn't strictly need to, which is safe; a corrupt manifest could
    otherwise silently skip files that actually changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    tmp_path.replace(path)
