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
    ONLY the passages retrieved for this topic, falling back to
    INSUFFICIENT_INFO_MARKER when they don't actually support an answer,
    and record the result (with appended source citations) under
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

    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    system_prompt = (
        f"{_AGENT_SYSTEM_PROMPTS[topic]} Relevant subtopics: {', '.join(TOPIC_SUBTOPICS[topic])}.\n\n"
        "Answer using ONLY the knowledge base excerpts below - do not use any outside knowledge, "
        "even general knowledge you already have about this subject. Each excerpt is labeled with "
        "its chapter_id. If ANY excerpt directly addresses the question, answer confidently from "
        "it, even if other excerpts are irrelevant - do not decline just because some excerpts "
        "don't apply. Only respond with the exact sentence below, and nothing else, if NONE of "
        f'the excerpts address the question at all: "{INSUFFICIENT_INFO_MARKER}"\n\n'
        f"Knowledge base excerpts:\n{_build_context_block(passages)}"
    )
    response = llm.invoke(
        [
            ("system", system_prompt),
            ("human", question),
        ]
    )
    answer = response.content.strip()

    is_insufficient = INSUFFICIENT_INFO_MARKER.lower() in answer.lower()
    if not is_insufficient and passages:
        cited_chapters = sorted({p["chapter_id"] for p in passages})
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
                },
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
