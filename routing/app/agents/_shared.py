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
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from app.config import AGENT_MODEL, TOPIC_SUBTOPICS
from app.state import RoutingState, get_topic_question

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
    single-topic case, since there's nothing to restate."""
    start = time.perf_counter()
    passages = state.get("retrieved_passages", {}).get(topic, [])
    question = get_topic_question(state, topic)
    tool_result = state.get("tool_results", {}).get(topic)
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

    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "agent_responses": {topic: answer},
        "execution_log": [
            {
                "node": f"{topic}_agent",
                "action": "answer",
                "output": {
                    "answer_preview": answer[:200],
                    "insufficient_info": is_insufficient,
                    "retrieved_chapters": [p["chapter_id"] for p in passages],
                    "used_tool_result": has_tool_result,
                },
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
