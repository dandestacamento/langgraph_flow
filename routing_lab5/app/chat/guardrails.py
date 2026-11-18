"""Input/output security scanning for the chat layer
(instructions/learnings/routing-lab-prod-plan.md section 2.4): a
prompt-injection classifier on incoming messages, and a secrets-leakage
scanner on outgoing answers - run *before* either reaches the existing,
unmodified `app.graph.build_graph()` pipeline or the user.

Both are gated behind `ROUTING_LAB_GUARDRAILS_ENABLED=1` (default off),
the same pattern this project already uses for other optional heavy-ML
features (reranking - see `app/rag/reranking.py` and `app/config.py`'s
`RERANK_ENABLED`). `scan_input()`'s model is a real, ~184M-parameter
DeBERTa classifier (`protectai/deberta-v3-base-prompt-injection-v2`,
MIT), not something every dev/test run of `routing_lab3` should be
forced to download - confirmed empirically to correctly distinguish a
normal question from both a classic "ignore previous instructions"
injection and a DAN-style jailbreak attempt, each with >99.99%
confidence, before this was wired into the graph.

Tried `llm-guard` (MIT) first, per routing-lab-prod-plan.md section 2.4's
original "LLM Guard or Guardrails AI" framing - it only declares Python
3.10-3.12 support on PyPI and failed to install on this project's
Python 3.13 environment (an old pinned `sentencepiece` version with no
3.13 wheel, forcing a from-source build with no local build toolchain).
Tried Guardrails AI (Apache-2.0) next - it installs cleanly, but its
`detect_prompt_injection` validator requires an external Pinecone index,
and its own dependency pins forced real version churn (downgrading this
project's `openai` package) for comparatively little unique value over
calling the same underlying classifier model directly. Settled on
calling `transformers` directly instead - already an existing dependency
via `sentence-transformers` (reranking) - for the actual ML-based
defense, plus a small, focused, self-written regex scanner for secrets
(the same "a focused guard, not an over-engineered framework" precedent
`app/tools/sql_query.py`'s SELECT-only check already set in this
project) for the output side, where fixed credential formats don't need
a classifier model the way adversarial prompt-injection phrasing does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import (
    GUARDRAILS_ENABLED,
    GUARDRAILS_INJECTION_CONFIDENCE_THRESHOLD,
    GUARDRAILS_PROMPT_INJECTION_MODEL,
)

try:
    from transformers import pipeline as _hf_pipeline

    _TRANSFORMERS_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover - optional dependency
    _TRANSFORMERS_IMPORT_ERROR = exc


@dataclass
class GuardrailResult:
    blocked: bool
    reason: str | None = None


@lru_cache(maxsize=1)
def _get_prompt_injection_classifier():
    if _TRANSFORMERS_IMPORT_ERROR is not None:
        raise ImportError(
            "Prompt-injection scanning requires the optional 'transformers' "
            "dependency (pip install transformers) - not installed by default "
            "since it downloads a ~184M-parameter model on first use. See "
            "instructions/learnings/routing-lab-prod-plan.md section 2.4."
        ) from _TRANSFORMERS_IMPORT_ERROR
    return _hf_pipeline("text-classification", model=GUARDRAILS_PROMPT_INJECTION_MODEL)


def scan_input(message: str) -> GuardrailResult:
    """Classifies `message` for a prompt-injection/jailbreak attempt
    before it ever reaches `condense_question()` or the routing
    pipeline. A no-op (always "safe") when guardrails are disabled -
    see this module's docstring for why that's the default."""
    if not GUARDRAILS_ENABLED:
        return GuardrailResult(blocked=False)

    classifier = _get_prompt_injection_classifier()
    result = classifier(message)[0]
    if result["label"] == "INJECTION" and result["score"] >= GUARDRAILS_INJECTION_CONFIDENCE_THRESHOLD:
        return GuardrailResult(blocked=True, reason="prompt_injection")
    return GuardrailResult(blocked=False)


# Fixed, well-known credential formats - not adversarial natural-language
# phrasing the way prompt injection is, so a classifier model isn't
# needed here the way it is for scan_input() above.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key IDs
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),  # PEM private keys
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub personal access tokens
]


def scan_output(answer: str) -> GuardrailResult:
    """Scans `answer` for an accidentally-leaked secret/credential
    before it's returned to the user or persisted to
    `conversation_history`. A no-op (always "safe") when guardrails are
    disabled."""
    if not GUARDRAILS_ENABLED:
        return GuardrailResult(blocked=False)

    for pattern in _SECRET_PATTERNS:
        if pattern.search(answer):
            return GuardrailResult(blocked=True, reason="secret_leakage")
    return GuardrailResult(blocked=False)
