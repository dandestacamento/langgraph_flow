"""Validates durable persistence
(instructions/learnings/routing-lab-prod-plan.md section 2.2): a
conversation's history and its thread_id ownership record must survive
a fresh process - simulated here by building a brand new
PostgresSaver/graph/ThreadOwnershipRegistry instance for the second
"turn," reusing nothing in-process from the first, rather than actually
killing and restarting a server (which this phase's manual testing did
do once, for real, via a running uvicorn process - see
instructions/learnings/routing-lab-prod-plan.md section 2.2's write-up).

Skipped unless CHAT_DB_URL points at a reachable Postgres instance
(`docker compose up -d postgres` from routing_lab6/) - these two tests
deliberately require real infrastructure, unlike the rest of this
project's fast, infra-free test suite, which is why they're kept in
their own file rather than folded into test_chat_api.py.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import HTTPException

CHAT_DB_URL = os.environ.get("CHAT_DB_URL")

pytestmark = pytest.mark.skipif(
    not CHAT_DB_URL, reason="CHAT_DB_URL not set - requires a real Postgres instance"
)


def _build_fresh_graph():
    from langgraph.checkpoint.postgres import PostgresSaver

    from app.chat.graph import build_chat_graph

    # Keeping a reference to the context manager itself (not just the
    # PostgresSaver it yields) is required - see app/api/main.py's
    # `_postgres_checkpointer_cm` docstring for the real bug this
    # guards against (premature garbage collection closing the
    # connection via an implicit GeneratorExit).
    checkpointer_cm = PostgresSaver.from_conn_string(CHAT_DB_URL)
    checkpointer = checkpointer_cm.__enter__()
    checkpointer.setup()
    return build_chat_graph(checkpointer=checkpointer), checkpointer_cm


def test_conversation_history_survives_a_fresh_process() -> None:
    thread_id = f"persistence-test-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    graph_1, _cm_1 = _build_fresh_graph()
    graph_1.invoke(
        {"user_message": "What's the price of the WM-900 washing machine?"}, config=config
    )

    # A brand new PostgresSaver/graph instance - nothing in-process is
    # reused from the first turn, simulating a fresh server process.
    graph_2, _cm_2 = _build_fresh_graph()
    result = graph_2.invoke({"user_message": "Is it covered under warranty?"}, config=config)

    assert "wm-900" in result["self_contained_question"].lower()


def test_thread_ownership_survives_a_fresh_process() -> None:
    from app.api.auth import ThreadOwnershipRegistry

    thread_id = f"persistence-test-{uuid.uuid4()}"
    registry_1 = ThreadOwnershipRegistry(conn_string=CHAT_DB_URL)
    registry_1.check_and_record(thread_id, "user-a")

    # A brand new registry instance - simulates a fresh process reading
    # back ownership recorded by a previous one.
    registry_2 = ThreadOwnershipRegistry(conn_string=CHAT_DB_URL)
    with pytest.raises(HTTPException) as exc_info:
        registry_2.check_and_record(thread_id, "user-b")
    assert exc_info.value.status_code == 403
