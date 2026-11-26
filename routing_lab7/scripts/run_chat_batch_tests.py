"""Run a dataset against the real chat API, in one or separate conversations."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_batch_tests import (  # noqa: E402
    load_questions,
    merge_manual_review,
    score_case,
    write_manual_review_csv,
    write_results_csv,
)

ISSUER = "http://localhost:8082/realms/routing-lab6"
CLIENT_ID = "routing-lab6-frontend"
REDIRECT_URI = "http://localhost:5173/"


class _TokenSession(Protocol):
    def token(self) -> str: ...


class LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    if parts.username or parts.password or parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("The chat regression runner only connects to local HTTP services.")
    return parts.scheme, parts.hostname, parts.port


def _require_success(response: httpx.Response, operation: str) -> None:
    if not response.is_success:
        raise RuntimeError(f"{operation} failed with HTTP {response.status_code}.")


class LocalKeycloakSession:
    """Local Keycloak authorization-code login with PKCE and token refresh."""

    def __init__(self, client: httpx.Client, username: str, password: str) -> None:
        self.client = client
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(24)
        response = client.get(
            f"{ISSUER}/protocol/openid-connect/auth",
            params={
                "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
                "response_type": "code", "response_mode": "query", "scope": "openid",
                "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            },
        )
        _require_success(response, "Keycloak login page")
        form = LoginFormParser()
        form.feed(response.text)
        if not form.action:
            raise RuntimeError("Keycloak did not return the expected login form.")
        action = urljoin(str(response.url), form.action)
        if _origin(action) != _origin(ISSUER):
            raise RuntimeError("Keycloak login form points to an unexpected origin.")
        # Browsers treat localhost as secure; httpx otherwise omits Keycloak's Secure cookies over local HTTP.
        cookies = [
            f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar
            if cookie.domain.lstrip(".") in {"localhost", "localhost.local"}
            and urlsplit(action).path.startswith(cookie.path) and not cookie.is_expired()
        ]
        response = client.post(
            action, data={"username": username, "password": password},
            headers={"Cookie": "; ".join(cookies)} if cookies else None,
        )
        if response.status_code not in (302, 303):
            raise RuntimeError("Keycloak login failed; check the username and password.")
        redirect = urlsplit(response.headers.get("location", ""))
        expected = urlsplit(REDIRECT_URI)
        if (redirect.scheme, redirect.netloc, redirect.path) != (expected.scheme, expected.netloc, expected.path):
            raise RuntimeError("Keycloak returned an unexpected login redirect.")
        params = parse_qs(redirect.query)
        if params.get("state") != [state] or len(params.get("code", [])) != 1:
            raise RuntimeError("Keycloak returned an invalid authorization response.")
        self._set_tokens(client.post(
            f"{ISSUER}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code", "client_id": CLIENT_ID,
                "code": params["code"][0], "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
            },
        ))

    def _set_tokens(self, response: httpx.Response) -> None:
        _require_success(response, "Keycloak token request")
        tokens = response.json()
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens["refresh_token"]
        self.expires_at = time.monotonic() + float(tokens["expires_in"])

    def token(self) -> str:
        if time.monotonic() >= self.expires_at - 30:
            self._set_tokens(self.client.post(
                f"{ISSUER}/protocol/openid-connect/token",
                data={"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": self.refresh_token},
            ))
        return self.access_token


def score_chat_response(case: dict, response: dict) -> dict:
    summary = response["routing_summary"]
    output = {
        "selected_topics": summary["topics"],
        "selected_subtopics": summary["subtopics"],
        "selected_chapters": summary["chapters"],
        "retrieved_passages": summary["passages"],
        "tool_results": summary["tool_results"],
        "is_multi_hop": summary["is_multi_hop"],
        "hop_results": summary["hop_results"],
        "recovery_attempts": summary["recovery_attempts"],
        "final_answer": response["final_answer"],
    }
    return score_case(case, output)


def render_report(details: list[dict], thread_id: str, selected_count: int, fresh_conversations: bool = False) -> str:
    lines = [
        "# Chat API regression report", "",
        "Conversation mode: separate conversations" if fresh_conversations else f"Conversation: `{thread_id}`",
        f"Processed {len(details)} of {selected_count} selected questions.",
        "Questions were sent to the real chat API in separate conversations." if fresh_conversations
        else "Questions were sent in order to the real chat API in one conversation.",
        "Fact checks are substring checks, not semantic judgments; review answers and passages manually.",
        "Retrieved sources are not verified citations. Token usage and cost are not available from the API.",
        "",
    ]
    for detail in details:
        case, response, scores = detail["case"], detail.get("response"), detail.get("scores")
        lines.extend([f"## {case['test_id']}: {case['question']}", "",
                      f"**Expected answer:** {case.get('expected_answer', '')}", ""])
        if fresh_conversations:
            lines.extend([f"**Conversation:** `{detail['thread_id']}`", ""])
        if detail.get("error"):
            lines.extend([f"**Request error:** {detail['error']}", ""])
            continue
        summary = response["routing_summary"]
        lines.extend([
            f"**Actual answer:** {response['final_answer']}", "",
            f"**Self-contained question:** {response['self_contained_question']}", "",
            f"**Expected route:** {case.get('expected_topics')} / {case.get('expected_subtopic')}",
            f"**Actual route:** {summary['topics']} / {summary['subtopics']}",
            f"**Expected source:** {case.get('expected_source')}",
            f"**Expected evidence:** {case.get('expected_evidence')}",
            f"**Guardrail blocked reason:** {response.get('guardrail_blocked_reason')}",
            f"**Checks:** {scores}", "",
            "**Retrieved passages:**", "",
        ])
        for topic, passages in summary["passages"].items():
            for passage in passages:
                lines.extend([
                    f"- {topic}: {passage.get('source') or passage.get('chapter_id')} "
                    f"(page {passage.get('page')}, score {passage.get('score')}): "
                    f"{' '.join((passage.get('text') or '').split())}",
                ])
        lines.append("")
    return "\n".join(lines)


def write_reports(
    output_dir: Path, cases: list[dict], details: list[dict], thread_id: str, fresh_conversations: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "chat_details.json").write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "chat_report.md").write_text(
        render_report(details, thread_id, len(cases), fresh_conversations), encoding="utf-8"
    )
    rows = [{
        "test_id": d["case"]["test_id"], "level": d["case"]["level"], "question": d["case"]["question"],
        **(d.get("scores") or {"routing_correct": False, "answer_correct": False, "overall_correct": False}),
        "latency_ms": d["latency_ms"], "total_tokens": None, "cost_usd": None, "error": d.get("error") or "",
    } for d in details]
    write_results_csv(output_dir / "chat_results.csv", [
        {"test_id": r["test_id"], "level": r["level"], "question": r["question"],
         "scores": r, "latency_ms": r["latency_ms"], "total_tokens": None, "cost_usd": None, "error": r["error"]}
        for r in rows
    ])
    write_manual_review_csv(output_dir / "manual_review.csv", merge_manual_review(output_dir / "manual_review.csv", cases))


def run_batch(
    client: httpx.Client, session: _TokenSession, api_url: str, cases: list[dict],
    output_dir: Path, fresh_conversations: bool = False,
) -> list[dict]:
    _origin(api_url)
    shared_thread_id = f"chat-regression-{uuid.uuid4()}"
    details = []
    for case in cases:
        thread_id = f"chat-regression-{uuid.uuid4()}" if fresh_conversations else shared_thread_id
        started = time.perf_counter()
        try:
            response = client.post(
                f"{api_url.rstrip('/')}/chat",
                headers={"Authorization": f"Bearer {session.token()}"},
                json={"thread_id": thread_id, "message": case["question"], "attachment_ids": []},
            )
            _require_success(response, "Chat request")
            body = response.json()
            if body["thread_id"] != thread_id:
                raise ValueError("Chat API returned a different conversation ID.")
            scores = score_chat_response(case, body)
            detail = {"case": case, "response": body, "scores": scores}
            print(f"{case['test_id']}: routing={scores['routing_correct']} answer={scores['answer_correct']}", flush=True)
        except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
            detail = {"case": case, "error": f"{type(exc).__name__}: {exc}"}
            print(f"{case['test_id']}: {detail['error']}", file=sys.stderr, flush=True)
        detail["thread_id"] = thread_id
        detail["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        details.append(detail)
        write_reports(output_dir, cases, details, shared_thread_id, fresh_conversations)
        if detail.get("error"):
            break
    conversation_label = "Separate conversations" if fresh_conversations else f"Conversation {shared_thread_id}"
    print(f"{conversation_label}; reports: {output_dir}", flush=True)
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "datasets" / "nist_questions.json")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "nist_chat_regression")
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--username", default="demo")
    parser.add_argument(
        "--fresh-conversations", action="store_true",
        help="Use a separate new conversation for each question rather than one shared conversation.",
    )
    args = parser.parse_args()
    _origin(args.api_url)
    cases = load_questions(args.dataset, args.ids)
    if not cases:
        raise SystemExit("No questions selected.")
    unsupported = {dimension for case in cases for dimension in case.get("graded", [])} - {"topic", "subtopic", "source"}
    if unsupported:
        raise SystemExit(f"Chat API reports cannot score these dimensions: {sorted(unsupported)}")
    password = os.environ.get("ROUTING_CHAT_PASSWORD") or getpass.getpass("Keycloak password: ")
    with httpx.Client(timeout=180, follow_redirects=False, trust_env=False) as client:
        session = LocalKeycloakSession(client, args.username, password)
        details = run_batch(client, session, args.api_url, cases, args.output_dir, args.fresh_conversations)
    if len(details) != len(cases) or any(d.get("error") or d["scores"]["overall_correct"] is not True for d in details):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
