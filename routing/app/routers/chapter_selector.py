"""Chapter Selector: stage 2c of the hybrid routing architecture (Level 3 -
chapter routing). Takes each selected (topic, subtopic) pair and narrows it
down to a specific chapter_id within that subtopic, using the real
front-matter metadata parsed by `app.rag.ingestion.list_chapter_metadata`.

One structured-output LLM call is made per selected topic (using the
subtopic chosen by `subtopic_router` for that topic), each constrained to
that subtopic's own chapter_id list - same pattern as `subtopic_router`,
one level deeper. Chapter titles *and* a short content preview are
included in the prompt, since titles alone proved insufficient during
testing (e.g. "which refrigerator has a water dispenser" was misrouted to
the "Features" chapter by title, when the fact actually lives in
"Overview") - a preview gives the model real content to discriminate
between chapters instead of guessing from the ID/title alone.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import Field, create_model

from app.config import ROUTER_MODEL
from app.rag.ingestion import list_chapter_metadata
from app.state import RoutingState


def _chapter_system_prompt(topic: str, subtopic: str, chapters: list[dict]) -> str:
    lines = [
        f"You are the Chapter Selector for the '{topic} / {subtopic}' subtopic in a routing "
        "accuracy test lab. The question has already been classified into this topic and "
        "subtopic - classify it into exactly one of these chapters. Use the content preview, not "
        "just the title - a specific fact can live in a chapter whose title alone wouldn't suggest it "
        "(e.g. a product's standard features are sometimes listed in an 'Overview' chapter rather "
        "than a 'Features' chapter):",
        "",
    ]
    for chapter in chapters:
        lines.append(f"- {chapter['chapter_id']} ({chapter['title']}): {chapter['preview']}")
    lines.append("")
    lines.append("Pick the single chapter whose content actually contains the answer to the question.")
    return "\n".join(lines)


def _build_chapter_output_model(chapter_ids: list[str]):
    """Build a one-off Pydantic model whose `chapter_id` field is
    restricted (via an enum constraint) to this subtopic's own chapters."""
    return create_model(
        "ChapterOutput",
        chapter_id=(str, Field(description="The selected chapter_id.", json_schema_extra={"enum": chapter_ids})),
        confidence=(float, Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")),
        reasoning=(str, Field(description="One sentence explaining the classification.")),
    )


def select_chapter(state: RoutingState) -> dict:
    """Router node: for each selected topic, classify the question into
    one chapter of the subtopic chosen by subtopic_router."""
    chapter_decisions: dict = {}
    selected_chapters: dict = {}
    log_entries: list[dict] = []

    for topic in state["selected_topics"]:
        subtopic = state["selected_subtopics"][topic]
        chapters = list_chapter_metadata(topic, subtopic)
        chapter_ids = [c["chapter_id"] for c in chapters]

        start = time.perf_counter()
        model = _build_chapter_output_model(chapter_ids)
        llm = ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(model)
        result = llm.invoke(
            [
                ("system", _chapter_system_prompt(topic, subtopic, chapters)),
                ("human", state["question"]),
            ]
        )
        duration_ms = (time.perf_counter() - start) * 1000

        chapter_id = result.chapter_id if result.chapter_id in chapter_ids else chapter_ids[0]
        decision = {
            "chapter_id": chapter_id,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
        chapter_decisions[topic] = decision
        selected_chapters[topic] = chapter_id
        log_entries.append(
            {
                "node": "chapter_selector",
                "action": f"select_chapter[{topic}/{subtopic}]",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        )

    return {
        "chapter_decisions": chapter_decisions,
        "selected_chapters": selected_chapters,
        "execution_log": log_entries,
    }
