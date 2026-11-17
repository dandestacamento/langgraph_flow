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


def test_threads_lists_only_the_current_users_conversations_most_recent_first() -> None:
    """Chat-ui-plan1.md Phase E's exit criterion: a user sees only their
    own past conversations - and in recency order, titled by their
    opening message."""
    user = f"user-{uuid.uuid4()}"
    other_user = f"user-{uuid.uuid4()}"
    first_thread = f"test-{uuid.uuid4()}"
    second_thread = f"test-{uuid.uuid4()}"
    foreign_thread = f"test-{uuid.uuid4()}"

    client.post(
        "/chat",
        json={"thread_id": first_thread, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )
    client.post(
        "/chat",
        json={"thread_id": second_thread, "message": "What is the price of the WM-900 washing machine?"},
        headers=_auth_headers(sub=user),
    )
    client.post(
        "/chat",
        json={"thread_id": foreign_thread, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=other_user),
    )

    response = client.get("/threads", headers=_auth_headers(sub=user))
    assert response.status_code == 200
    threads = response.json()
    assert [t["thread_id"] for t in threads] == [second_thread, first_thread]
    # Titles are LLM-generated after the first turn (chat-ui-plan3.md
    # §1.2) - assert they exist and are short summaries, not the raw
    # opening messages.
    assert all(t["title"] for t in threads)
    assert all(t["updated_at"] for t in threads)


def test_threads_requires_authentication() -> None:
    assert client.get("/threads").status_code == 401


def test_thread_history_returns_the_recorded_turns() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What is the price of the WM-900 washing machine?"},
        headers=_auth_headers(),
    )
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "Is it covered under warranty?"},
        headers=_auth_headers(),
    )

    response = client.get(f"/threads/{thread_id}/history", headers=_auth_headers())
    assert response.status_code == 200
    turns = response.json()
    assert len(turns) == 2
    assert turns[0]["user_message"] == "What is the price of the WM-900 washing machine?"
    assert turns[0]["final_answer"]
    assert turns[1]["user_message"] == "Is it covered under warranty?"


def test_thread_history_rejects_another_users_thread() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub="user-a"),
    )

    response = client.get(f"/threads/{thread_id}/history", headers=_auth_headers(sub="user-b"))
    assert response.status_code == 403


def test_thread_history_is_404_for_an_unknown_thread() -> None:
    response = client.get(f"/threads/test-{uuid.uuid4()}/history", headers=_auth_headers())
    assert response.status_code == 404


def test_conversation_meta_question_is_answered_from_history_not_rag() -> None:
    """chat-ui-plan2.md section 3: 'what was my previous question?' must
    be answered from conversation memory, not sent to knowledge-base
    retrieval (which used to answer 'Insufficient information')."""
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(),
    )

    response = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What was my previous question?"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert "e21" in body["final_answer"].lower()
    assert "insufficient information" not in body["final_answer"].lower()
    # No knowledge-base routing ran for this turn - and the previous
    # turn's routing trace must not leak into it either.
    assert body["routing_summary"]["topics"] == []


def test_rename_thread_updates_the_listed_title() -> None:
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )

    response = client.patch(
        f"/threads/{thread_id}", json={"title": "Washing machine E21"}, headers=_auth_headers(sub=user)
    )
    assert response.status_code == 204

    threads = client.get("/threads", headers=_auth_headers(sub=user)).json()
    assert threads[0]["title"] == "Washing machine E21"


def test_rename_rejects_another_users_thread_and_empty_titles() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub="user-a"),
    )

    forbidden = client.patch(
        f"/threads/{thread_id}", json={"title": "Hijacked"}, headers=_auth_headers(sub="user-b")
    )
    assert forbidden.status_code == 403

    empty = client.patch(
        f"/threads/{thread_id}", json={"title": "   "}, headers=_auth_headers(sub="user-a")
    )
    assert empty.status_code == 422


def test_delete_thread_removes_it_from_the_list_and_its_history() -> None:
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )

    response = client.delete(f"/threads/{thread_id}", headers=_auth_headers(sub=user))
    assert response.status_code == 204

    assert client.get("/threads", headers=_auth_headers(sub=user)).json() == []
    # The ownership record is gone (404, not an empty 200) and the
    # checkpointed history is gone with it.
    assert client.get(f"/threads/{thread_id}/history", headers=_auth_headers(sub=user)).status_code == 404


def test_delete_rejects_another_users_thread() -> None:
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub="user-a"),
    )

    response = client.delete(f"/threads/{thread_id}", headers=_auth_headers(sub="user-b"))
    assert response.status_code == 403


def test_soft_deleted_thread_cannot_be_resumed_and_can_be_restored() -> None:
    """chat-ui-plan3.md §1.1: delete is undo-able - the thread leaves the
    list and rejects resumption while deleted, and restore brings back
    both the list entry and the full history."""
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )

    assert client.delete(f"/threads/{thread_id}", headers=_auth_headers(sub=user)).status_code == 204
    assert client.get("/threads", headers=_auth_headers(sub=user)).json() == []
    resume = client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "Hello again?"},
        headers=_auth_headers(sub=user),
    )
    assert resume.status_code == 404

    assert (
        client.post(f"/threads/{thread_id}/restore", headers=_auth_headers(sub=user)).status_code
        == 204
    )
    threads = client.get("/threads", headers=_auth_headers(sub=user)).json()
    assert [t["thread_id"] for t in threads] == [thread_id]
    history = client.get(f"/threads/{thread_id}/history", headers=_auth_headers(sub=user)).json()
    assert len(history) == 1
    assert history[0]["user_message"] == "What does washing machine error E21 mean?"


def test_restore_rejects_another_users_thread() -> None:
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )
    client.delete(f"/threads/{thread_id}", headers=_auth_headers(sub=user))

    response = client.post(f"/threads/{thread_id}/restore", headers=_auth_headers(sub="user-b"))
    assert response.status_code == 403


def test_permanent_delete_removes_the_thread_for_good() -> None:
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )

    response = client.delete(
        f"/threads/{thread_id}?permanent=true", headers=_auth_headers(sub=user)
    )
    assert response.status_code == 204
    # Not restorable: the ownership record itself is gone.
    assert (
        client.post(f"/threads/{thread_id}/restore", headers=_auth_headers(sub=user)).status_code
        == 404
    )


def test_first_turn_generates_a_short_title_and_rename_still_wins() -> None:
    """chat-ui-plan3.md §1.2: after the first turn the sidebar title is a
    generated summary, not the raw opening message - and a manual rename
    is never overwritten by later turns."""
    user = f"user-{uuid.uuid4()}"
    thread_id = f"test-{uuid.uuid4()}"
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "What does washing machine error E21 mean?"},
        headers=_auth_headers(sub=user),
    )

    threads = client.get("/threads", headers=_auth_headers(sub=user)).json()
    assert threads[0]["title"]
    assert threads[0]["title"] != "What does washing machine error E21 mean?"
    assert len(threads[0]["title"]) <= 80

    client.patch(
        f"/threads/{thread_id}", json={"title": "My E21 saga"}, headers=_auth_headers(sub=user)
    )
    client.post(
        "/chat",
        json={"thread_id": thread_id, "message": "Is it covered under warranty?"},
        headers=_auth_headers(sub=user),
    )
    threads = client.get("/threads", headers=_auth_headers(sub=user)).json()
    assert threads[0]["title"] == "My E21 saga"


def test_client_error_is_logged_and_returns_204(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("ERROR", logger="routing_lab3.client_errors"):
        response = client.post(
            "/client-error",
            json={
                "message": "Deliberate render crash",
                "stack": "Error: Deliberate render crash\n  at Crashing",
                "component_stack": "  at App",
                "url": "http://localhost:5173/",
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 204
    assert "Deliberate render crash" in caplog.text


def test_client_error_requires_authentication() -> None:
    response = client.post("/client-error", json={"message": "crash"})
    assert response.status_code == 401


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

