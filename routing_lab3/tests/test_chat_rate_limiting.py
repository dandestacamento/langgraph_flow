"""Validates per-user rate limiting/cost control
(instructions/learnings/routing-lab-prod-plan.md section 2.3): a
budget-exceeded user is blocked, and a different user's budget is
completely unaffected - verified against the real, full multi-node chat
graph (every LLM/embedding call it makes per turn), not a single raw
LiteLLM call, since the actual implementation risk here was whether
every one of the ~16 ChatOpenAI/OpenAIEmbeddings call sites across
app/routers/, app/agents/, app/chat/condense.py, and
app/rag/embeddings.py actually honors the current request's virtual key
(app/llm_gateway.py).

Skipped unless LITELLM_BASE_URL points at a reachable LiteLLM instance
(`docker compose up -d litellm` from routing_lab3/, which also needs
postgres - see infra/litellm/README.md) - deliberately requires real
infrastructure, like tests/test_chat_persistence.py.
"""

from __future__ import annotations

import os
import uuid

import pytest
from openai import UnprocessableEntityError

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-routing-lab3-dev-master-key")

pytestmark = pytest.mark.skipif(
    not LITELLM_BASE_URL, reason="LITELLM_BASE_URL not set - requires a real LiteLLM instance"
)


def test_a_budget_exceeded_user_is_blocked_without_affecting_another_user() -> None:
    from app import llm_gateway
    from app.chat.graph import build_chat_graph

    # A deliberately tiny budget - small enough that even one real turn
    # (which makes several LLM/embedding calls) exceeds it, proving every
    # one of those calls actually used this key, not just the first one.
    tiny_budget_provisioner = llm_gateway.UserKeyProvisioner(
        base_url=LITELLM_BASE_URL, master_key=LITELLM_MASTER_KEY, max_budget=0.000001
    )
    generous_provisioner = llm_gateway.UserKeyProvisioner(
        base_url=LITELLM_BASE_URL, master_key=LITELLM_MASTER_KEY, max_budget=5.00
    )

    graph = build_chat_graph()
    tiny_budget_key = tiny_budget_provisioner.get_or_create_key(f"test-tiny-{uuid.uuid4()}")
    generous_key = generous_provisioner.get_or_create_key(f"test-generous-{uuid.uuid4()}")

    llm_gateway.set_current_user_api_key(tiny_budget_key)
    with pytest.raises(UnprocessableEntityError, match="Budget has been exceeded"):
        graph.invoke({"user_message": "What does washing machine error E21 mean?"})

    # The budget-exceeded user's own second attempt is still blocked...
    llm_gateway.set_current_user_api_key(tiny_budget_key)
    with pytest.raises(UnprocessableEntityError, match="Budget has been exceeded"):
        graph.invoke({"user_message": "What is the price of the WM-900?"})

    # ...but a different user, with their own budget, is unaffected.
    llm_gateway.set_current_user_api_key(generous_key)
    result = graph.invoke({"user_message": "What does washing machine error E21 mean?"})
    assert "drainage" in result["final_answer"].lower()
