"""Topic Router: stage 2 of the hybrid routing architecture. Classifies a
question into one or more of the six knowledge-base topics using
structured LLM output plus the topic/subtopic metadata from
`app/config.py`.

The output is always a list (`topics`) rather than a single label so the
same router and the same `RoutingState.selected_topics` field support
Level 1 (always exactly one topic) through Level 7 (multiple topics,
routed in parallel via `app.graph.route_to_agents`) without changing the
schema later.

Level 7 also adds `topic_questions`: a per-topic restatement of only the
relevant part of a multi-topic question, produced by this same structured
output call (no extra LLM call). Each topic agent (`app/agents/_shared.py`)
uses its own restated question instead of the full original one when more
than one topic is selected - direct testing showed that handing a topic
agent the full, unmodified multi-part question and merely *instructing*
it to "answer only your part, ignore the rest" was unreliable (it
sometimes declined its own part entirely when the other part's fragment
was also present in the prompt), even with an added worked example.
Restating the question per topic removes the other topic's fragment from
what that agent ever sees, which is more robust than instructing the
model to ignore text it can still see.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL, TOPIC_SUBTOPICS
from app.state import RoutingState

TopicLiteral = Literal[
    "appliances",
    "azure_cloud",
    "data_engineering",
    "python",
    "finance",
    "customer_support",
]

_TOPIC_DESCRIPTIONS = {
    "appliances": "Refrigerators, washing machines, dishwashers: models, features, warranty, fault codes.",
    "azure_cloud": "Azure networking, compute, security, storage: VNets, VMs, RBAC, Blob/Table storage.",
    "data_engineering": "Spark, Databricks, Azure Data Factory: partitions, pipelines, Delta Lake, jobs.",
    "python": "Python fundamentals, OOP, concurrency: functions, decorators, classes, asyncio.",
    "finance": "Personal finance: budgeting, loans/amortization, investment returns and risk.",
    "customer_support": "Customer support policies: orders, refunds, delivery/shipping.",
}


def _topic_router_system_prompt() -> str:
    lines = [
        "You are the Topic Router for a routing accuracy test lab. Classify the user's question "
        "into one or more of these topics (most questions need exactly one):",
        "",
    ]
    for topic, subtopics in TOPIC_SUBTOPICS.items():
        lines.append(f"- {topic}: {_TOPIC_DESCRIPTIONS[topic]} (subtopics: {', '.join(subtopics)})")
    lines.append("")
    lines.append(
        "Watch for overlapping terminology that means different things in different topics - for "
        "example 'partition' refers to a Spark compute partition, an Azure Table Storage partition, "
        "or a physical warehouse storage partition depending on context. Use the surrounding context "
        "of the question, not keyword matching alone, to choose the topic. Business-process anchors "
        "(SmartHome, shipping, warehouses, orders, refunds, customers) are stronger signals than a "
        "generic technical term like 'partition' or 'node' that also appears in cloud/data-engineering "
        "chapters - a question about 'storage partitions in a shipping warehouse' is about "
        "customer_support logistics, not data_engineering or azure_cloud, even though it uses the word "
        "'partition'."
    )
    lines.append(
        "Most questions need EXACTLY ONE topic. Only include a second topic if the question "
        "explicitly asks about something that genuinely requires a different topic AREA (e.g. "
        "appliances AND customer_support together, where one part needs a product spec/fault code "
        "and the other part explicitly asks about an order/refund/return/delivery). NEVER invent "
        "or imagine a second question that wasn't actually asked just to justify adding a topic - "
        "`topics` must only ever reflect what the question literally asks, nothing more. If you are "
        "not sure a second topic is truly needed, do not include it - a wrong single topic is a "
        "smaller error than an unnecessary second one, and over-splitting hurts efficiency without "
        "improving accuracy.\n"
        "A compound question that stays entirely within ONE topic's own subtopics is still ONE "
        "topic, not two, even if it needs two chapters to answer fully:\n"
        "  - If the second part of the question is just asking MORE about the SAME specific "
        "product/model/fault code already named in the first part (not explicitly asking about a "
        "refund, return, or shipment), the whole question is ONE topic - that product's own topic "
        "covers all of its own warranty/coverage questions too. Only split into customer_support as "
        "well when a refund, return, cancellation, or delivery is EXPLICITLY asked about in the "
        "question's own words, not merely because a word like 'covered' or 'policy' appears.\n"
        "  - Two subtopics of the same topic are still one topic: 'what's included in White Glove "
        "delivery, and how is warehouse inventory organized?' is entirely customer_support (both "
        "the delivery and warehouse-operations content live under customer_support) - it is NOT "
        "data_engineering, even though 'inventory organization' sounds like it could be a data topic.\n"
        "  - A warranty, fault code, or spec question about a product is entirely appliances, even "
        "if it uses words like 'warranty', 'covered', 'repair', or 'policy' that also appear in "
        "customer_support's refund chapters: 'what does error E05 mean, and what's the compressor "
        "warranty?' and 'what does E21 mean on the WM-500, and what is its standard warranty term?' "
        "are BOTH entirely appliances (both parts are about the SAME product's own fault code and "
        "warranty terms, not about a refund) - a NAMED product/fault code's warranty coverage (how "
        "long a part is covered) is appliances content, found in that product's own chapters; "
        "customer_support's 'refunds' subtopic is a DIFFERENT concept (returning an item for money "
        "back) and is NOT the right topic just because the wording sounds service-related ('repair', "
        "'covered') - it isn't about a refund at all.\n"
        "  - Re-check the overlapping-terminology guidance above before adding a second topic: a "
        "warehouse/inventory/partition question grounded in shipping, orders, or customers is "
        "customer_support, not data_engineering, no matter how technical the wording sounds."
    )
    lines.append(
        "When you include more than one topic, also fill in `topic_questions`: for each topic, a "
        "short standalone restatement containing ONLY the part of the question relevant to that "
        "topic, phrased as a complete question a specialist in that topic alone could fully "
        "answer, with no mention of the other topic(s)' part at all."
    )
    lines.append("")
    lines.append(
        "Also decide: is this question ambiguous? Only set is_ambiguous=true when the question uses "
        "a vague, unresolved reference with NO identifiable subject at all - e.g. 'it'/'this'/'that' "
        "with nothing to anchor what it refers to - or when the SAME question, asked about two "
        "different products/models/orders, would have two DIFFERENT correct answers, and the "
        "question doesn't say which one it means (e.g. 'how long is the warranty?' - warranty "
        "length genuinely varies by product, so the answer depends on which product is meant). Do "
        "NOT set is_ambiguous=true just because a question is general, or phrased as a personal "
        "request ('can I...?') rather than an abstract policy question ('what is the policy...?') - "
        "what matters is ONLY whether the answer would differ depending on unstated specifics. "
        "'What is the refund policy for change-of-mind returns?' and 'can I cancel my order after "
        "it's packed?' both have ONE deterministic answer no matter which specific product or order "
        "is meant, so NEITHER is ambiguous. 'Can I get a refund or replacement?' and 'how long is "
        "the warranty?' genuinely depend on unstated specifics (which item, its condition, which "
        "model) that would change the answer, so BOTH are ambiguous - even though the first is "
        "phrased just as much like a personal request as the cancellation example. Still pick your "
        "best-guess topics even when ambiguous. A question that spans multiple topics (needing more "
        "than one topic to fully answer) is NOT, by itself, ambiguous - judge each part "
        "independently using the same test above (does the answer depend on unstated specifics?): "
        "if every part either names what it needs, or has one deterministic answer regardless of "
        "specifics, the whole question is NOT ambiguous even though it needs multiple topics (e.g. "
        "'what's included in White Glove delivery, and what's the warranty on the WM-300's motor?' "
        "names both a specific service and a specific model, so it is NOT ambiguous)."
    )
    return "\n".join(lines)


TOPIC_ROUTER_SYSTEM_PROMPT = _topic_router_system_prompt()


class TopicQuestionItem(BaseModel):
    """One (topic, restated question) pair. Used as a list rather than a
    `dict[str, str]` because OpenAI's strict structured-output schema
    mode doesn't support free-form-keyed objects (confirmed by a direct
    400 error: "Invalid schema ... Extra required key 'topic_questions'
    supplied" when `topic_questions` was typed as `dict[str, str]`) - a
    list of fixed-shape objects is strict-schema compatible."""

    topic: TopicLiteral
    question: str = Field(
        description="A standalone restatement containing ONLY the part of the original question "
        "relevant to this topic, phrased as a complete question a specialist in this topic alone "
        "could fully answer, with no mention of any other topic's part."
    )


class TopicOutput(BaseModel):
    """Structured output the LLM must produce."""

    is_ambiguous: bool = Field(
        description="True only if the question has no identifiable subject or needs a specific "
        "product/model/order/error code that isn't given - not just because it's a general question."
    )
    topics: list[TopicLiteral] = Field(
        description="Best-guess topic(s) needed to answer the question, most specific/relevant first, "
        "even if is_ambiguous is true."
    )
    topic_questions: list[TopicQuestionItem] = Field(
        description="One entry per topic in `topics` - see TopicQuestionItem.question. If there is "
        "only one topic, its question can just be the original question unchanged."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")
    reasoning: str = Field(description="One sentence explaining the classification and ambiguity decision.")


def build_topic_llm() -> ChatOpenAI:
    return ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(TopicOutput)


def classify_topic(state: RoutingState) -> dict:
    """Router node: classify the question into one or more topics, and
    flag whether it's too ambiguous to route confidently."""
    start = time.perf_counter()
    llm = build_topic_llm()
    result: TopicOutput = llm.invoke(
        [
            ("system", TOPIC_ROUTER_SYSTEM_PROMPT),
            ("human", state["question"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    topics = list(dict.fromkeys(result.topics)) or ["customer_support"]
    topic_question_map = {item.topic: item.question for item in result.topic_questions}
    topic_questions = {t: topic_question_map.get(t, state["question"]) for t in topics}
    decision: dict = {
        "topics": topics,
        "is_ambiguous": result.is_ambiguous,
        "topic_questions": topic_questions,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }

    return {
        "topic_decision": decision,
        "selected_topics": topics,
        "execution_log": [
            {
                "node": "topic_router",
                "action": "classify_topic",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
