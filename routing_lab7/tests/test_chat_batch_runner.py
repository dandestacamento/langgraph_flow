import csv
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from scripts.run_chat_batch_tests import LocalKeycloakSession, run_batch, score_chat_response


def _case(test_id: str) -> dict:
    return {
        "test_id": test_id, "level": 4, "question": f"Question {test_id}?",
        "expected_topics": ["artificial_intelligence"], "expected_subtopic": "risk_management",
        "expected_source": "manual.pdf", "expected_facts": ["measure", "manage"],
        "expected_answer": "MEASURE and MANAGE.", "graded": ["topic", "subtopic", "source"],
    }


def _response(thread_id: str, answer: str = "MEASURE and MANAGE.") -> dict:
    return {
        "thread_id": thread_id, "self_contained_question": "Question",
        "final_answer": answer, "guardrail_blocked_reason": None,
        "routing_summary": {
            "topics": ["artificial_intelligence"], "subtopics": {"artificial_intelligence": "risk_management"},
            "chapters": {}, "passages": {"artificial_intelligence": [
                {"chapter_id": "manual", "source": "manual.pdf", "page": 3, "text": "MEASURE and MANAGE."}
            ]},
            "tool_results": {}, "is_multi_hop": False, "hop_results": [], "recovery_attempts": {},
        },
    }


def test_one_conversation_is_used_for_all_chat_requests_and_reports(tmp_path):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=_response(body["thread_id"]))

    class Session:
        def token(self):
            return "test-token"

    cases = [_case("N1"), _case("N2")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        details = run_batch(client, Session(), "http://localhost:8000", cases, tmp_path)
    assert [request["message"] for request in requests] == ["Question N1?", "Question N2?"]
    assert requests[0]["thread_id"] == requests[1]["thread_id"]
    assert all(item["scores"]["overall_correct"] for item in details)
    report = (tmp_path / "chat_report.md").read_text(encoding="utf-8")
    assert "Expected answer:" in report and "Actual answer:" in report
    assert "manual.pdf (page 3" in report
    with (tmp_path / "chat_results.csv").open(newline="", encoding="utf-8") as file:
        assert len(list(csv.DictReader(file))) == 2


def test_request_failure_stops_conversation_and_writes_error(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429)

    class Session:
        def token(self):
            return "test-token"

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        details = run_batch(client, Session(), "http://localhost:8000", [_case("N1"), _case("N2")], tmp_path)
    assert len(requests) == 1
    assert "HTTP 429" in details[0]["error"]
    assert "HTTP 429" in (tmp_path / "chat_report.md").read_text(encoding="utf-8")


def test_facts_in_source_labels_do_not_make_answer_pass():
    response = _response("thread", "No answer.\n\nSources: measure-manage.pdf")
    assert score_chat_response(_case("N1"), response)["answer_correct"] is False


def test_local_login_uses_pkce_and_refreshes_token():
    states = []
    grants = []

    def handler(request):
        if request.url.path.endswith("/auth"):
            query = parse_qs(request.url.query.decode())
            states.append(query["state"][0])
            assert query["code_challenge_method"] == ["S256"]
            return httpx.Response(
                200, text='<form id="kc-form-login" action="/login"></form>',
                headers={"set-cookie": "KC_RESTART=test; Path=/; Secure"},
            )
        if request.url.path == "/login":
            assert request.headers["cookie"] == "KC_RESTART=test"
            return httpx.Response(302, headers={"location": f"http://localhost:5173/?state={states[0]}&code=code"})
        data = parse_qs(request.content.decode())
        grants.append(data["grant_type"][0])
        return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 1})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        session = LocalKeycloakSession(client, "demo", "password")
        assert session.token() == "access"
    assert grants == ["authorization_code", "refresh_token"]


def test_local_login_rejects_external_login_action():
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text='<form id="kc-form-login" action="http://example.com/login"></form>')
    )) as client:
        with pytest.raises(ValueError, match="only connects to local"):
            LocalKeycloakSession(client, "demo", "password")
