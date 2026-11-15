"""Tool Router: stage 3b of the hybrid routing architecture (Level 8 -
tool selection and execution). For each selected topic, decides whether
answering needs a tool beyond the passages `rag_retriever` already found
for it - and if so, which tool (`calculator`, `sql_query`, or
`metadata_lookup`) and with what input - then executes that tool
immediately (deterministic, no extra LLM call) and records the result.

Most questions still need no tool at all (`needs_tool=false`) - RAG
retrieval alone already answers them, exactly as in Levels 1-7. A tool is
only genuinely needed when the fact isn't in any chapter's prose at all
(`price_aud` is CSV-only, by design - see `app/tools/sql_query.py`), when
answering requires arithmetic rather than a lookup (`calculator`), or when
the question is about the knowledge base's own structure rather than its
content (`metadata_lookup`).

`document_search` is deliberately not offered as a selectable tool here -
see `app/tools/document_search.py` for why (redundant with the always-on
`rag_retriever`, which already runs before this node for every question).

Uses the same per-topic `get_topic_question()` restatement as
`subtopic_router`/`chapter_selector`/`rag_retriever`, so a multi-topic
question's tool decision for one topic is never influenced by another
topic's fragment.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL
from app.state import RoutingState, get_topic_question
from app.tools.calculator import calculate
from app.tools.metadata_lookup import lookup_metadata
from app.tools.sql_query import get_specifications_schema, run_sql_query

ToolNameLiteral = Literal["calculator", "sql_query", "metadata_lookup"]


class ToolSelection(BaseModel):
    """Structured output the LLM must produce for one topic."""

    needs_tool: bool = Field(
        description="True only if answering genuinely requires a tool - most questions don't; "
        "retrieved passages alone already answer them."
    )
    tool_name: ToolNameLiteral | None = Field(
        description="Which tool to use, or null if needs_tool is false."
    )
    tool_input: str | None = Field(
        description="The exact input to pass the chosen tool (see the per-tool format described "
        "above), or null if needs_tool is false."
    )
    reasoning: str = Field(description="One sentence explaining the tool decision.")


def _tool_router_system_prompt(topic: str, subtopic: str, passages: list[dict]) -> str:
    lines = [
        f"You are the Tool Router for the '{topic} / {subtopic}' subtopic in a routing accuracy "
        "test lab. Decide whether answering this question genuinely requires one of the tools "
        "below, beyond the knowledge-base passages already retrieved for it (shown below).",
        "",
        "Available tools:",
        "- calculator: a plain arithmetic expression using + - * / and parentheses only, e.g. "
        "'(5 + 10) / 2'. Use whenever answering needs arithmetic, EVEN IF you could work out the "
        "result yourself while reasoning about the decision - always select this tool for any "
        "arithmetic rather than silently doing the math yourself and reporting needs_tool=false; "
        "the whole point of this tool is to actually execute and verify the computation, not to "
        "trust an LLM's own mental math.",
    ]
    schema = get_specifications_schema(topic, subtopic)
    if schema:
        lines.append(
            "- sql_query: a SQL SELECT query against a table named 'specifications' with one row "
            f"per {subtopic} model and columns: {', '.join(schema)}. Example: "
            "\"SELECT price_aud FROM specifications WHERE model = 'WM-900'\". Use this for exact "
            "spec/price lookups - 'price_aud' in particular is NOT mentioned in any retrieved "
            "chapter's prose, so a price question can only be answered via this tool. Other "
            "columns (capacity, warranty years) usually ARE already in the passages below in "
            "prose form - check there first and prefer needs_tool=false for those, since the "
            "'check passages first' rule below applies specifically to this tool, not to "
            "calculator or metadata_lookup. Always SELECT the column(s) the question actually "
            "needs named in the answer, not just the column being sorted/filtered on - e.g. for "
            "'which model is cheapest?', write \"SELECT model FROM specifications ORDER BY "
            "price_aud ASC LIMIT 1\" (selecting `model`, the thing being asked for), not \"SELECT "
            "price_aud FROM specifications ORDER BY price_aud ASC LIMIT 1\" (which returns a price "
            "with no model name attached to identify which one it is)."
        )
    lines.append(
        "- metadata_lookup: either the literal string 'chapter_count' (how many chapters this "
        "subtopic has) or 'version <chapter_id>' (that chapter's version number, e.g. 'version "
        "chapter_01_policy'). Use whenever the question asks about the knowledge base's own "
        "structure (chapter counts, document versions) rather than its content - this information "
        "is never in the retrieved passages' prose (they're the content, not a structural index of "
        "themselves), so always select this tool for such a question rather than reporting "
        "needs_tool=false."
    )
    lines.append(
        "For sql_query specifically: check the passages below FIRST, and prefer needs_tool=false "
        "if they already state the answer in prose - do not use a tool just because one happens "
        "to be available, and do not assume a fact is missing from the passages without actually "
        "checking them. This 'check passages first' guidance does NOT apply to calculator or "
        "metadata_lookup, which should be used whenever their kind of question arises (arithmetic, "
        "or knowledge-base structure), regardless of what the passages happen to contain."
    )
    lines.append("")
    if passages:
        lines.append("Passages already retrieved for this question:")
        lines.append("\n\n".join(f"[{p['chapter_id']}] {p['text']}" for p in passages))
    else:
        lines.append("(no passages were retrieved for this question)")
    return "\n".join(lines)


def build_tool_router_llm() -> ChatOpenAI:
    return ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(ToolSelection)


def _execute_tool(tool_name: str, tool_input: str, topic: str, subtopic: str) -> tuple[str | None, str | None]:
    """Run the selected tool. Returns (output, error) - exactly one is
    not None, matching `ToolResult`'s shape."""
    try:
        if tool_name == "calculator":
            return str(calculate(tool_input)), None
        if tool_name == "sql_query":
            rows = run_sql_query(tool_input, topic, subtopic)
            return str(rows), None
        if tool_name == "metadata_lookup":
            return lookup_metadata(tool_input, topic, subtopic), None
        return None, f"Unknown tool_name {tool_name!r}."
    except Exception as exc:  # noqa: BLE001 - any tool failure is reported, not raised
        return None, str(exc)


def select_tools(state: RoutingState) -> dict:
    """Router node: for each selected topic, decide whether a tool is
    needed and, if so, execute it immediately."""
    tool_decisions: dict = {}
    tool_results: dict = {}
    log_entries: list[dict] = []

    for topic in state["selected_topics"]:
        subtopic = state["selected_subtopics"].get(topic)
        if subtopic is None:
            continue
        passages = state.get("retrieved_passages", {}).get(topic, [])

        start = time.perf_counter()
        llm = build_tool_router_llm()
        result: ToolSelection = llm.invoke(
            [
                ("system", _tool_router_system_prompt(topic, subtopic, passages)),
                ("human", get_topic_question(state, topic)),
            ]
        )
        duration_ms = (time.perf_counter() - start) * 1000

        decision: dict = {
            "needs_tool": result.needs_tool,
            "tool_name": result.tool_name if result.needs_tool else None,
            "tool_input": result.tool_input if result.needs_tool else None,
            "reasoning": result.reasoning,
        }
        tool_decisions[topic] = decision

        log_output: dict = {"decision": decision}
        if decision["needs_tool"] and decision["tool_name"] and decision["tool_input"]:
            output, error = _execute_tool(decision["tool_name"], decision["tool_input"], topic, subtopic)
            tool_results[topic] = {
                "tool_name": decision["tool_name"],
                "tool_input": decision["tool_input"],
                "output": output,
                "error": error,
            }
            log_output["result"] = tool_results[topic]

        log_entries.append(
            {
                "node": "tool_router",
                "action": f"select_tools[{topic}/{subtopic}]",
                "output": log_output,
                "duration_ms": round(duration_ms, 1),
            }
        )

    return {
        "tool_decisions": tool_decisions,
        "tool_results": tool_results,
        "execution_log": log_entries,
    }
