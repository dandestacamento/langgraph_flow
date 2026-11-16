"""Chat-app tests: the FastAPI backend (`app/api/main.py`).

Exercises the HTTP layer directly via `fastapi.testclient.TestClient`
(no real server process needed) - confirms the API correctly wraps
`app.chat.graph.build_chat_graph()`, including that conversation state
persists across requests via `thread_id` the same way it does when
calling the graph directly in `tests/test_chat_condensing.py`.

Auth tests verify against a locally generated RSA key (`app/api/auth.py`'s
`_get_signing_key` is monkeypatched below), not a live Keycloak instance -
deterministic and fast, consistent with this project's testing
conventions elsewhere (e.g. the frontend's e2e tests mock the backend
rather than requiring a live LLM).
"""

from __future__ import annotations

import json
import uuid

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import app.api.auth as auth_module
from app.api.main import app

client = TestClient(app)

_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()


@pytest.fixture(autouse=True)
def _use_test_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_get_signing_key", lambda token: _TEST_PUBLIC_KEY)


def _make_token(sub: str = "test-user", azp: str = auth_module.KEYCLOAK_CLIENT_ID) -> str:
    payload = {"sub": sub, "azp": azp, "iss": auth_module.KEYCLOAK_ISSUER}
    return pyjwt.encode(payload, _TEST_PRIVATE_KEY, algorithm="RS256")


def _auth_headers(sub: str = "test-user") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(sub=sub)}"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_requires_authentication() -> None:
    response = client.post("/chat", json={"thread_id": f"test-{uuid.uuid4()}", "message": "hi"})
    assert response.status_code == 401


def test_chat_rejects_a_malformed_token() -> None:
    response = client.post(
        "/chat",
        json={"thread_id": f"test-{uuid.uuid4()}", "message": "hi"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_chat_rejects_a_token_not_issued_to_this_client() -> None:
    token = _make_token(azp="some-other-client")
    response = client.post(
        "/chat",
        json={"thread_id": f"test-{uuid.uuid4()}", "message": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_chat_endpoint_answers_a_self_contained_question() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    response = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(),
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
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What is the price of the WM-900 washing machine?"},
        headers=_auth_headers(),
    )

    response = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "Is it covered under warranty?"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert "wm-900" in response.json()["self_contained_question"].lower()


def test_thread_ownership_rejects_a_different_user() -> None:
    """Closes the gap flagged in instructions/learnings/chat-ui-plan1.md
    section 6: a thread_id must only be resumable by the user who first
    used it."""
    thread_id = f"test-{uuid.uuid4()}"
    first = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub="user-a"),
    )
    assert first.status_code == 200

    second = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "Hello?"},
        headers=_auth_headers(sub="user-b"),
    )
    assert second.status_code == 403


def test_chat_stream_endpoint_emits_status_then_answer_events() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    with client.stream(
        "POST",
        "/chat/stream",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(),
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

