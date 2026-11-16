"""Chat-app tests: the FastAPI backend (`app/api/main.py`).

Exercises the HTTP layer directly via `fastapi.testclient.TestClient`
(no real server process needed) - confirms the API correctly wraps
`app.chat.graph.build_chat_graph()`, including that conversation state
persists across requests via `thread_id` the same way it does when
calling the graph directly in `tests/test_chat_condensing.py`.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_answers_a_self_contained_question() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    response = client.post(
        "/chat", json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "drainage" in body["final_answer"].lower()
    assert "appliances" in body["routing_summary"]["topics"]
    assert body["routing_summary"]["chapters"]["appliances"]
    assert body["routing_summary"]["passages"]["appliances"], "expected at least one cited passage"


def test_chat_endpoint_resolves_a_follow_up_across_requests() -> None:
    """The defining behavior of the whole chat layer: a follow-up in a
    second, separate HTTP request must still resolve correctly, proving
    conversation_history actually persists via the checkpointer and
    thread_id - not just within one process-local graph.invoke() call."""
    thread_id = f"test-{uuid.uuid4()}"
    client.post("/chat", json={"thread_id": thread_id, "message": "What is the price of the WM-900 washing machine?"})

    response = client.post("/chat", json={"thread_id": thread_id, "message": "Is it covered under warranty?"})
    assert response.status_code == 200
    assert "wm-900" in response.json()["self_contained_question"].lower()


def test_chat_stream_endpoint_emits_status_then_answer_events() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    with client.stream(
        "POST", "/chat/stream", json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"}
    ) as response:
        assert response.status_code == 200
        events: list[tuple[str, dict]] = []
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: ") and event_name:
                events.append((event_name, json.loads(line.removeprefix("data: "))))

    event_names = [name for name, _ in events]
    assert "status" in event_names
    assert "answer" in event_names
    answer_payload = next(data for name, data in events if name == "answer")
    assert "drainage" in answer_payload["final_answer"].lower()
    assert "appliances" in answer_payload["routing_summary"]["topics"]
