"""Metadata lookup tool (Level 8 - tool selection and execution): answers
questions about the knowledge base's own structure (how many chapters a
subtopic has, what version a chapter is) using the front-matter metadata
written by `scripts/generate_knowledge_base.py` and parsed by
`app.rag.ingestion`, without needing a vector search or an LLM call to
re-read chapter content.
"""

from __future__ import annotations

from app.rag.ingestion import list_chapter_metadata


def lookup_chapter_count(topic: str, subtopic: str) -> int:
    """How many chapters exist for a (topic, subtopic) pair."""
    return len(list_chapter_metadata(topic, subtopic))


def lookup_chapter_version(topic: str, subtopic: str, chapter_id: str) -> str:
    """The `version` front-matter field of one chapter. Raises
    `ValueError` if no chapter with that `chapter_id` exists in this
    (topic, subtopic)."""
    for chapter in list_chapter_metadata(topic, subtopic):
        if chapter["chapter_id"] == chapter_id:
            return str(chapter["version"])
    raise ValueError(f"No chapter {chapter_id!r} found in {topic}/{subtopic}.")


def lookup_metadata(tool_input: str, topic: str, subtopic: str) -> str:
    """Parse and execute a metadata lookup. `tool_input` must be either
    `"chapter_count"` or `"version <chapter_id>"` (e.g.
    `"version chapter_01_policy"`) - this small fixed mini-syntax (rather
    than a free-form natural-language query) keeps the lookup
    deterministic and keeps the Tool Router's job limited to picking the
    right lookup type and chapter_id, not writing open-ended logic."""
    tool_input = tool_input.strip()
    if tool_input == "chapter_count":
        return str(lookup_chapter_count(topic, subtopic))
    if tool_input.startswith("version "):
        chapter_id = tool_input.removeprefix("version ").strip()
        return lookup_chapter_version(topic, subtopic, chapter_id)
    raise ValueError(
        f"Unrecognized metadata_lookup input {tool_input!r} - expected 'chapter_count' or 'version <chapter_id>'."
    )
