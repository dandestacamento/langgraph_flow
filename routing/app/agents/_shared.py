"""Shared helper for the six topic agents (appliance, azure, data
engineering, python, finance, customer_support).

Level 4 (RAG retrieval) grounds every agent in the passages retrieved by
`app.rag.retrieval.retrieve_evidence` for that topic (`retrieved_passages`
in state) instead of answering from the LLM's own general knowledge -
per instructions/Langgraph_routing/7_to_8_routing_configuration.md section
3 ("Do not generate unsupported answers. If evidence is insufficient,
request clarification or explicitly report insufficient information.").
Citations are appended by this code (listing every retrieved chapter_id),
not self-reported by the LLM, so a citation is never hallucinated - it
always reflects what was actually retrieved.

Level 10 adds one bounded recovery retry (see `run_topic_agent`'s
docstring) when the first attempt declines or a selected tool failed.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import AGENT_MODEL, TOPIC_SUBTOPICS
from app.rag.retrieval import retrieve
from app.routers.tool_router import _execute_tool
from app.state import RoutingState, get_topic_question
from app.tools.sql_query import get_specifications_schema

INSUFFICIENT_INFO_MARKER = "Insufficient information in the knowledge base to answer this question."

_AGENT_SYSTEM_PROMPTS = {
    "appliances": (
        "You are the Appliances Agent for SmartHome Appliances, answering questions about "
        "refrigerators, washing machines, and dishwashers: models, features, warranty terms, and "
        "fault/error codes. Be precise about model numbers - warranty and capacity differ by model."
    ),
    "azure_cloud": (
        "You are the Azure Cloud Agent, answering questions about Azure networking, compute, "
        "security, and storage: VNets, subnets, NSGs, VMs, RBAC, managed identity, Key Vault, and "
        "Blob/Table storage."
    ),
    "data_engineering": (
        "You are the Data Engineering Agent, answering questions about Apache Spark, Databricks, "
        "and Azure Data Factory: partitions, shuffles, Delta Lake, jobs, pipelines, and triggers."
    ),
    "python": (
        "You are the Python Agent, answering questions about Python fundamentals, OOP, and "
        "concurrency: functions, decorators, classes, inheritance, threading, and asyncio."
    ),
    "finance": (
        "You are the Finance Agent, answering general personal-finance questions about budgeting, "
        "loans/amortization, and investment returns and risk. Do not give individualized financial "
        "advice - explain general concepts only."
    ),
    "customer_support": (
        "You are the Customer Support Agent for SmartHome Appliances, answering questions about "
        "order placement/tracking/cancellation, refund policy, and delivery/shipping."
    ),
}


def _build_context_block(passages: list[dict]) -> str:
    if not passages:
        return "(no passages retrieved)"
    return "\n\n".join(f"[{p['chapter_id']}] {p['text']}" for p in passages)


def _generate_answer(topic: str, question: str, passages: list[dict], tool_result: dict | None) -> tuple[str, bool]:
    """One answer-generation attempt: build the prompt from `passages`
    and `tool_result`, invoke the LLM once, and return `(answer, is_insufficient)`.
    Pulled out of `run_topic_agent` so Level 10's retry can call this a
    second time with improved `passages`/`tool_result` without
    duplicating the prompt-construction logic."""
    # Only a *successful* tool result is surfaced to the agent - a failed
    # tool call (tool_result["error"] set) falls back to passages alone,
    # exactly as if no tool had run, rather than showing the agent a
    # broken result it might otherwise try to explain or apologize for.
    has_tool_result = bool(tool_result and tool_result.get("error") is None)

    tool_block = (
        f"\n\nTool result ({tool_result['tool_name']} on input {tool_result['tool_input']!r}): "
        f"{tool_result['output']}"
        if has_tool_result
        else ""
    )
    tool_note = (
        " A tool result is also provided below the knowledge base excerpts - treat it as an "
        "additional authoritative source exactly like an excerpt, and cite it in your Sources "
        "line as 'tool:<name>' (e.g. 'tool:sql_query') alongside any chapter_ids. The tool result "
        "directly answers the question whenever the question is asking exactly what the tool "
        "computed or looked up - for example, if a calculator tool computed a sum and the question "
        "asked for that sum, simply state the number as part of your own natural sentence (e.g. "
        "'The total is 4.'), and if a metadata_lookup tool found a chapter count of 3 and the "
        "question asked how many chapters a subtopic has, simply state 'It has 3 chapters.' Do NOT "
        "copy the literal 'Tool result (<name> on input <input>): <output>' line into your answer - "
        "that line is for your own reference only, not something to echo back to the user; always "
        "phrase the number into a normal, natural sentence answering the question."
        if has_tool_result
        else ""
    )
    decline_condition = (
        "NONE of the excerpts or the tool result address the question at all"
        if has_tool_result
        else "NONE of the excerpts address the question at all"
    )

    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    system_prompt = (
        f"{_AGENT_SYSTEM_PROMPTS[topic]} Relevant subtopics: {', '.join(TOPIC_SUBTOPICS[topic])}.\n\n"
        "Answer using ONLY the knowledge base excerpts below - do not use any outside knowledge, "
        "even general knowledge you already have about this subject. Each excerpt is labeled with "
        "its chapter_id. If ANY excerpt directly addresses the question, answer confidently from "
        "it, even if other excerpts are irrelevant - do not decline just because some excerpts "
        f"don't apply.{tool_note} Only respond with the exact sentence below, and nothing else, if "
        f'{decline_condition}: "{INSUFFICIENT_INFO_MARKER}"\n\n'
        f"Knowledge base excerpts:\n{_build_context_block(passages)}{tool_block}"
    )
    response = llm.invoke(
        [
            ("system", system_prompt),
            ("human", question),
        ]
    )
    answer = response.content.strip()

    is_insufficient = INSUFFICIENT_INFO_MARKER.lower() in answer.lower()
    if not is_insufficient and (passages or has_tool_result):
        cited_chapters = sorted({p["chapter_id"] for p in passages})
        if has_tool_result:
            cited_chapters.append(f"tool:{tool_result['tool_name']}")
        answer = f"{answer}\n\nSources: {', '.join(cited_chapters)}"

    return answer, is_insufficient


class _CorrectedToolInput(BaseModel):
    """Structured output for the Level 10 tool-error retry."""

    corrected_input: str = Field(description="A corrected input for the same tool, fixing the error.")


def _retry_tool(topic: str, subtopic: str, tool_name: str, original_input: str, error: str) -> tuple[str | None, str | None]:
    """Level 10: ask the LLM to self-correct a failed tool call's input
    given the error message, then execute the corrected input once.
    Returns `(output, error)`, matching `_execute_tool`'s shape - the
    caller treats a non-None `error` here as "recovery did not fix it",
    not as a reason to retry again (a single bounded retry only)."""
    lines = [
        f"A {tool_name} call failed. Given the original input and the error, produce a corrected "
        "input for the SAME tool that fixes the error.",
        f"Original input: {original_input!r}",
        f"Error: {error}",
    ]
    if tool_name == "sql_query":
        schema = get_specifications_schema(topic, subtopic)
        if schema:
            lines.append(f"The 'specifications' table's actual columns are: {', '.join(schema)}.")
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0).with_structured_output(_CorrectedToolInput)
    result: _CorrectedToolInput = llm.invoke([("system", "\n".join(lines)), ("human", "Correct the input.")])
    return _execute_tool(tool_name, result.corrected_input, topic, subtopic)


def run_topic_agent(topic: str, state: RoutingState) -> dict:
    """Shared node body for every topic agent: answer the question using
    ONLY the passages retrieved for this topic (plus a tool result, if
    `tool_router.select_tools` ran one for this topic - Level 8), falling
    back to INSUFFICIENT_INFO_MARKER when neither actually supports an
    answer, and record the result (with appended source citations,
    including a `tool:<name>` citation when a tool result was used) under
    `agent_responses[topic]`.

    For a multi-topic question (Level 7), the agent answers
    `topic_decision.topic_questions[topic]` - the Topic Router's own
    restatement containing only this topic's relevant part - rather than
    the full original question. An earlier approach kept the full
    question and merely *instructed* the agent to "answer only your part,
    ignore the rest"; direct testing showed that was unreliable (the
    agent sometimes declined its own part entirely once it could see the
    other topic's fragment was unaddressed by its excerpts), even with an
    added worked example. Restating the question per topic removes the
    other topic's fragment from what this agent ever sees, which is more
    robust than instructing the model to ignore text it can still see -
    and keeps this function's prompt byte-identical to Levels 1-6 for the
    single-topic case, since there's nothing to restate.

    Level 10 adds one bounded recovery retry: if the first attempt
    declines (or a selected tool failed), retries exactly once with a
    self-corrected tool input (if a tool failed) and retrieval broadened
    to the whole topic (dropping the subtopic filter, in case the
    original subtopic guess was wrong) before regenerating the answer.
    Recorded in `recovery_attempts[topic]` regardless of outcome, so "no
    recovery was needed" (the common case) is a visible fact, not an
    absence to infer."""
    start = time.perf_counter()
    passages = state.get("retrieved_passages", {}).get(topic, [])
    question = get_topic_question(state, topic)
    tool_result = state.get("tool_results", {}).get(topic)
    tool_decision = state.get("tool_decisions", {}).get(topic, {})

    answer, is_insufficient = _generate_answer(topic, question, passages, tool_result)

    # Level 10: one bounded recovery retry, only when the first attempt
    # actually needed one - a failed tool call, or a decline despite
    # having *some* evidence to reconsider (broadening retrieval can
    # recover from e.g. a wrong subtopic guess). A single attempt only,
    # per Stage 5's "strict retry limit" - no further retries after this,
    # even if it also fails, so a genuinely unanswerable question still
    # correctly reports insufficient information rather than looping.
    tool_failed = bool(tool_decision.get("needs_tool") and tool_result and tool_result.get("error"))
    recovery: dict = {"attempted": False, "reason": None, "succeeded": None}

    if tool_failed or is_insufficient:
        recovery["attempted"] = True
        recovery["reason"] = "tool_error" if tool_failed else "insufficient_info"

        if tool_failed:
            subtopic = state.get("selected_subtopics", {}).get(topic)
            corrected_output, corrected_error = _retry_tool(
                topic, subtopic, tool_decision["tool_name"], tool_decision["tool_input"], tool_result["error"]
            )
            if corrected_error is None:
                tool_result = {
                    "tool_name": tool_decision["tool_name"],
                    "tool_input": tool_decision["tool_input"],
                    "output": corrected_output,
                    "error": None,
                }

        # Broaden retrieval to the whole topic (dropping the subtopic
        # filter) - recovers from a possibly-wrong subtopic guess without
        # needing to know whether that's actually what went wrong.
        broadened_passages = retrieve(question, topic=topic, subtopic=None)
        if broadened_passages:
            passages = broadened_passages

        answer, is_insufficient = _generate_answer(topic, question, passages, tool_result)
        recovery["succeeded"] = not is_insufficient

    duration_ms = (time.perf_counter() - start) * 1000
    has_tool_result = bool(tool_result and tool_result.get("error") is None)

    return {
        "agent_responses": {topic: answer},
        "recovery_attempts": {topic: recovery},
        "execution_log": [
            {
                "node": f"{topic}_agent",
                "action": "answer",
                "output": {
                    "answer_preview": answer[:200],
                    "insufficient_info": is_insufficient,
                    "retrieved_chapters": [p["chapter_id"] for p in passages],
                    "used_tool_result": has_tool_result,
                    "recovery": recovery,
                },
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }

