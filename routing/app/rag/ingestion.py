"""Document ingestion.

Level 3 (chapter routing) needs per-chapter metadata (topic, subtopic,
chapter_id, document_id, title, and a short content preview) to build the
Chapter Selector's prompt and to score chapter-routing accuracy -
implemented here via `list_chapter_metadata`, which parses the YAML front
matter written by `scripts/generate_knowledge_base.py`, each chapter's H1
title, and a short preview of its body. (Titles alone proved insufficient
during Level 3 testing - e.g. "which refrigerator has a water dispenser"
was misrouted to the "Features" chapter by title alone, when the fact
actually lives in "Overview" - so a short preview is included to give the
Chapter Selector real content signal, not just a title to pattern-match.)

Level 4 (RAG retrieval) extends this with full document body loading and
the chunking/embedding/indexing pipeline (`chunking.py`, `embeddings.py`,
`retrieval.py`), not yet implemented - `load_knowledge_base_documents`
below is still a Level 4 stub.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import KNOWLEDGE_BASE_DIR, TOPIC_SUBTOPICS

_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_PREVIEW_CHARS = 400


def parse_chapter_file(path: Path) -> dict:
    """Parse one chapter Markdown file's YAML front matter, H1 title, and
    a short preview of the body text (post-heading). Raises ValueError if
    the file is missing the expected front matter block (every chapter
    written by generate_knowledge_base.py has one)."""
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path} is missing the expected '---' YAML front matter block")

    front_matter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    title_match = _H1_RE.search(body)
    title = title_match.group(1).strip() if title_match else path.stem

    body_after_heading = body[title_match.end():] if title_match else body
    preview_text = " ".join(body_after_heading.split())
    preview = preview_text[:_PREVIEW_CHARS].rstrip()
    if len(preview_text) > _PREVIEW_CHARS:
        preview += "..."

    return {**front_matter, "title": title, "preview": preview, "path": str(path)}


@lru_cache(maxsize=1)
def _all_chapter_metadata() -> tuple[dict, ...]:
    """Every chapter's metadata across the whole knowledge base, cached for
    the process lifetime - the knowledge base is static at runtime; re-run
    scripts/generate_knowledge_base.py and restart the process to pick up
    content changes."""
    chapters: list[dict] = []
    for topic, subtopics in TOPIC_SUBTOPICS.items():
        for subtopic in subtopics:
            directory = KNOWLEDGE_BASE_DIR / topic / subtopic
            for md_path in sorted(directory.glob("*.md")):
                chapters.append(parse_chapter_file(md_path))
    return tuple(chapters)


def list_chapter_metadata(topic: str, subtopic: str) -> list[dict]:
    """Chapter metadata (chapter_id, document_id, version, title) for one
    (topic, subtopic) pair, in filename order."""
    return [c for c in _all_chapter_metadata() if c["topic"] == topic and c["subtopic"] == subtopic]


def load_knowledge_base_documents():
    raise NotImplementedError(
        "Full document body loading for RAG is implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/2_routing_scenarios.md). Level 3 only needs "
        "chapter metadata - see list_chapter_metadata() above."
    )
