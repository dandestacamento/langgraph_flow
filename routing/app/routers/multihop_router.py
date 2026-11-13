"""Multi-Hop Router: stage 1b of the hybrid routing architecture (Level 9
- complex multi-hop reasoning). Runs right after `complexity_router` and
decides whether a question is genuinely multi-hop: does answering it
require a sequential dependency, where a later sub-question literally
cannot be fully phrased until an earlier sub-question's answer is known?

This is a different thing from every prior level's "compound question"
handling:
- Level 6 (multi-chapter): two facts from different chapters of the
  SAME already-known subject - both facts are independently retrievable
  right away, no dependency.
- Level 7 (multi-topic): two facts from different topics, about
  already-named subjects - independently resolvable in parallel, no
  dependency either.
- Level 9 (multi-hop): the second fact's SUBJECT isn't named at all -
  it's a pronoun/reference ("its", "that model") standing in for
  whatever hop 1 turns out to identify. "Which washing machine model has
  the largest capacity, and what's its price?" cannot be split into two
  independent questions up front, because "its price" doesn't name a
  model until hop 1 resolves "which model has the largest capacity".

Only a genuine Level 9 case should set `is_multi_hop=true` - a question
that merely has multiple parts but where every part already names its
own subject is Level 6/7/8 territory and must stay on the existing
single-pass pipeline unchanged (see `app/graph.py`'s conditional edge).
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL
from app.state import RoutingState

MULTIHOP_SYSTEM_PROMPT = """You are the Multi-Hop Router for a routing accuracy test lab. The \
overwhelming majority of questions are NOT multi-hop - default to is_multi_hop=false, and only set \
it true after this question passes BOTH checks below.

CHECK 1 - structure: does the question contain an explicit "and" (or similar) joining TWO \
separate question-like clauses? A single clause is NEVER multi-hop, no matter how long, specific, \
or technical it sounds - e.g. "What's the compressor warranty length for SmartHome refrigerators?" \
is ONE clause (one question about one named product category) and must be is_multi_hop=false, even \
though "compressor warranty length for SmartHome refrigerators" is a long, detailed phrase.

CHECK 2 - identification query: is the FIRST clause itself phrased as a "which" (or equivalent) \
query that asks you to IDENTIFY ONE WINNING entity via a comparison/superlative criterion - e.g. \
"which model has the largest/smallest/longest/shortest X", "which fault code indicates Y"? This is \
a narrow, specific pattern. If the first clause is instead a direct fact-lookup, yes/no question, \
or statement about a subject already given by name (e.g. "what does error E05 mean", "is the \
DW-400 quiet", "what's included in White Glove delivery", "what format does an order number use", \
"what shipping methods are available", "are final-sale items eligible for a refund") - ANY of \
these patterns, even followed by "and" plus a second clause using "its"/"that"/"it" - is NOT \
multi-hop. The first clause must be a genuine comparison/identification lookup with an unknown \
winner, not merely a fact-lookup, yes/no check, or list query about something already specified.

Examples that ARE multi-hop (both checks pass - first clause is a "which ... has/is CRITERION" \
identification query with no entity named anywhere):
- "Which washing machine model has the largest capacity, and what's its price?"
- "Which dishwasher model has the most place settings, and what is its standard warranty?"
- "Which washing machine fault code indicates a drainage problem, and is a repair for that cause \
typically covered under warranty?" - the first clause identifies an unknown fault code via its \
symptom, not a fact-lookup about an already-named code.

Examples that are NOT multi-hop (fail CHECK 1 or CHECK 2):
- "What's the compressor warranty length for SmartHome refrigerators?" - one clause (CHECK 1).
- "Why is using a mutable default argument considered a Python pitfall?" - one clause (CHECK 1).
- "Is the DW-400 quiet, and what's needed for its 1-hour express cycle to work well?" - first \
clause is a yes/no fact-check about an already-named model (CHECK 2), not an identification query.
- "What does the ORD- order number format mean, and can I still cancel after it's packed?" - \
first clause is "what does X mean", a fact-lookup, not an identification query (CHECK 2).
- "What shipping methods are available, and when does a redelivery fee apply?" - first clause \
asks for a LIST of options, not identification of one winning entity via a criterion (CHECK 2).
- "What's included in White Glove delivery, and how is warehouse inventory organized?" - first \
clause is a fact-lookup about an already-named service, not an identification query (CHECK 2).
- "What's the price of the WM-900, and what does error E42 indicate?" - first clause is a \
fact-lookup about an already-named model (CHECK 2).
- "My WM-500 has error E21, and what's the refund policy?" - first clause is a statement, not \
even a question, let alone an identification query (CHECK 2).
- "What does refrigerator error E05 mean, and what's the compressor warranty?" - first clause is \
"what does X mean", a fact-lookup about an already-named code, not an identification query \
(CHECK 2) - even though the second clause reads awkwardly alone, that's an incomplete phrasing to \
answer directly from the same retrieved context, not a genuine unresolved-entity dependency.
- "What format does a SmartHome order number use, and what does the E10 washing machine fault \
code mean?" - first clause is a fact-lookup, not an identification query (CHECK 2); E10 is also \
already named in the second clause itself.
- "Are final-sale items eligible for a refund, and what does refrigerator error E05 mean?" - first \
clause is a yes/no question about a named category, not an identification query (CHECK 2).

When is_multi_hop is true, also produce:
- hop1_question: the first, fully self-contained sub-question (identify the subject).
- hop2_question_template: the second sub-question, rephrased as a complete question with the \
literal placeholder text "{hop1_answer}" standing in for the subject hop 1 will identify. ALWAYS \
include the product/category context from the original question in this template alongside the \
placeholder (e.g. "What is the price of the refrigerator model {hop1_answer}?", not just "What is \
the price of {hop1_answer}?") - a bare model code or fault code on its own can be ambiguous \
(e.g. "RF-700" could plausibly be several kinds of product without that context), while the \
original question's own wording already makes the category clear, so carry it over explicitly. \
Do not resolve or guess the subject's identity yourself - leave the placeholder for the pipeline \
to fill in after hop 1 actually runs.

When is_multi_hop is false, hop1_question and hop2_question_template should both be null."""


class MultiHopPlan(BaseModel):
    """Structured output the LLM must produce."""

    is_multi_hop: bool = Field(
        description="True only if the question passes BOTH checks in the system prompt: an "
        "explicit 'and' joining two clauses, AND the first clause is itself a 'which ... has/is "
        "CRITERION' identification query (not a fact-lookup about an already-named subject)."
    )
    hop1_question: str | None = Field(
        description="The first, fully self-contained sub-question, or null if not multi-hop."
    )
    hop2_question_template: str | None = Field(
        description="The second sub-question with a literal '{hop1_answer}' placeholder, or null "
        "if not multi-hop."
    )
    reasoning: str = Field(description="One sentence explaining the multi-hop decision.")


def build_multihop_llm() -> ChatOpenAI:
    return ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(MultiHopPlan)


def classify_multihop(state: RoutingState) -> dict:
    """Router node: decide whether the question is genuinely multi-hop
    and, if so, produce its two-hop decomposition plan."""
    start = time.perf_counter()
    llm = build_multihop_llm()
    result: MultiHopPlan = llm.invoke(
        [
            ("system", MULTIHOP_SYSTEM_PROMPT),
            ("human", state["question"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    hop_plan = (
        {
            "hop1_question": result.hop1_question,
            "hop2_question_template": result.hop2_question_template,
            "reasoning": result.reasoning,
        }
        if result.is_multi_hop
        else None
    )

    return {
        "is_multi_hop": result.is_multi_hop,
        "hop_plan": hop_plan,
        "execution_log": [
            {
                "node": "multihop_router",
                "action": "classify_multihop",
                "output": {
                    "is_multi_hop": result.is_multi_hop,
                    "hop_plan": hop_plan,
                    "reasoning": result.reasoning,
                },
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
