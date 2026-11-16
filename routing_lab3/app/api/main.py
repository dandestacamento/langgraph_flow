"""FastAPI backend for the routing-lab3 chat application.

A small, custom, permissively-licensed API layer directly on top of the
MIT-licensed `langgraph` library - deliberately NOT using LangGraph's
packaged Agent Server (`langgraph-api`), which requires a paid Enterprise
license key for production self-hosting (Elastic License 2.0) - see
instructions/learnings/routing-lab-prod-plan.md section 0/2.10 for the
full reasoning. This module is that "small, from-scratch alternative."

One `build_chat_graph()` instance, with one shared checkpointer, serves
every request - conversations are isolated by `thread_id`, which is the
client's responsibility to generate and track (e.g. one per browser
session, the same pattern `smarthome-csr/app.py` already uses with
Streamlit's `st.session_state`).

`/chat` and `/chat/stream` require a valid Keycloak-issued bearer token
(see app/api/auth.py) and enforce that a `thread_id` can only be resumed
by the user who first used it (`ThreadOwnershipRegistry`) - closing the
gap flagged in instructions/learnings/chat-ui-plan1.md section 6.

Conversation history is durable (survives a process/container restart)
when `CHAT_DB_URL` is set - see `_build_checkpointer()` below and
instructions/learnings/routing-lab-prod-plan.md section 2.2. Without it,
falls back to `InMemorySaver` (lost on restart), which is what this
project's own tests use, to stay fast/deterministic without requiring a
live Postgres instance for every test run.

Every LLM/embedding call made on behalf of a request goes through that
user's own LiteLLM virtual key (app/llm_gateway.py) when `LITELLM_BASE_URL`
is set - instructions/learnings/routing-lab-prod-plan.md section 2.3 -
so one user exceeding their budget is rejected (429) without affecting
anyone else's.

Exposes two endpoints:
- `POST /chat` - synchronous, returns the full turn's result as JSON.
- `POST /chat/stream` - Server-Sent Events, one `status` event per graph
  node as it completes, then a final `answer` event - deliberately a
  simpler contract than the official LangGraph Server API's token-level
  streaming (which this project isn't using, per the licensing decision
  above), but enough for a frontend to show incremental progress instead
  of one long blocking wait.

Run with:
    uvicorn app.api.main:app --reload
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

import os  # noqa: E402

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from openai import RateLimitError, UnprocessableEntityError  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app import llm_gateway  # noqa: E402
from app.api.auth import ThreadOwnershipRegistry, get_current_user  # noqa: E402
from app.cache import enable_llm_cache  # noqa: E402
from app.chat.graph import build_chat_graph  # noqa: E402
from app.chat.routing_summary import build_routing_summary  # noqa: E402

enable_llm_cache()

app = FastAPI(title="Routing Lab Chat API", version="0.1.0")

# Only needed when the frontend is served from a different origin than
# this API (e.g. the Vite dev server without its proxy, or a separately
# deployed production frontend container). Defaults to the Vite dev
# server's own origin; override with a comma-separated list via
# CHAT_API_CORS_ORIGINS for other deployments.
_cors_origins = os.environ.get("CHAT_API_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# A single shared checkpointer for the process lifetime - see module
# docstring and _build_checkpointer() below for the InMemorySaver vs.
# PostgresSaver decision. build_chat_graph() just takes whichever
# checkpointer is built - no other code here needs to change based on
# which one is active.
_CHAT_DB_URL = os.environ.get("CHAT_DB_URL")

# Holds a reference to PostgresSaver.from_conn_string(...)'s own context
# manager object (not just the PostgresSaver it yields) for the whole
# process lifetime - without this, nothing keeps that object alive once
# _build_checkpointer() returns, so Python garbage-collects it, which
# closes the (paused-mid-generator) underlying connection via an
# implicit GeneratorExit - a real bug hit and fixed during this phase's
# own testing (manifested as `psycopg.OperationalError: the connection
# is closed` the moment the first query ran). Unused directly - its
# mere existence as a live reference is what matters.
_postgres_checkpointer_cm = None


def _build_checkpointer():
    """Durable (PostgresSaver) if CHAT_DB_URL is set, otherwise
    in-memory (lost on restart) - instructions/learnings/
    routing-lab-prod-plan.md section 2.2. The connection is opened once
    here and kept open for the process lifetime (not explicitly closed
    on shutdown - acceptable for this phase, since the OS reclaims the
    socket when the process exits either way; a cleaner lifespan-based
    teardown is a reasonable future improvement, not done here to keep
    this change bounded)."""
    global _postgres_checkpointer_cm

    if not _CHAT_DB_URL:
        return InMemorySaver()

    from langgraph.checkpoint.postgres import PostgresSaver

    _postgres_checkpointer_cm = PostgresSaver.from_conn_string(_CHAT_DB_URL)
    checkpointer = _postgres_checkpointer_cm.__enter__()
    checkpointer.setup()
    return checkpointer


_chat_graph = build_chat_graph(checkpointer=_build_checkpointer())

# Persists alongside conversation history in the same Postgres database
# when CHAT_DB_URL is set (see ThreadOwnershipRegistry's own docstring,
# app/api/auth.py); in-memory (and lost together with conversation
# history on restart) otherwise.
_thread_ownership = ThreadOwnershipRegistry(conn_string=_CHAT_DB_URL)

# None (meaning: every call uses OPENAI_API_KEY directly, no per-user
# budget) unless LITELLM_BASE_URL is set - instructions/learnings/
# routing-lab-prod-plan.md section 2.3.
_LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL")
_user_key_provisioner = (
    llm_gateway.UserKeyProvisioner(
        base_url=_LITELLM_BASE_URL,
        master_key=os.environ["LITELLM_MASTER_KEY"],
        conn_string=_CHAT_DB_URL,
    )
    if _LITELLM_BASE_URL
    else None
)


def _scope_llm_calls_to(user: str) -> None:
    """Sets the per-request virtual API key (app/llm_gateway.py) every
    ChatOpenAI/OpenAIEmbeddings call made for the rest of this request
    will use - a no-op when LiteLLM isn't configured."""
    if _user_key_provisioner is not None:
        llm_gateway.set_current_user_api_key(_user_key_provisioner.get_or_create_key(user))


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    self_contained_question: str
    final_answer: str
    # Trimmed per-turn routing/retrieval/tool trace for generative UI -
    # see app/chat/routing_summary.py for exactly what this contains and
    # what's deliberately left out.
    routing_summary: dict
    # "prompt_injection" | "secret_leakage" | None - set by
    # app.chat.graph's check_input/check_output nodes
    # (app.chat.guardrails.py, instructions/learnings/
    # routing-lab-prod-plan.md section 2.4) when this turn's
    # final_answer is a safe fallback rather than the pipeline's real
    # output. Always None when ROUTING_LAB_GUARDRAILS_ENABLED isn't set.
    guardrail_blocked_reason: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, user: str = Depends(get_current_user)) -> ChatResponse:
    """One synchronous turn: invokes the chat graph and returns the full
    result. Simpler to call/test than `/chat/stream` - use this for
    anything that doesn't need incremental progress updates."""
    _thread_ownership.check_and_record(request.thread_id, user)
    _scope_llm_calls_to(user)
    config = {"configurable": {"thread_id": request.thread_id}}
    try:
        output = _chat_graph.invoke({"user_message": request.message}, config=config)
    except (RateLimitError, UnprocessableEntityError) as exc:
        # LiteLLM returns HTTP 422 (UnprocessableEntityError in the
        # openai SDK's exception hierarchy, not RateLimitError) for a
        # budget-exceeded virtual key specifically - confirmed
        # empirically while validating this phase, not assumed from
        # docs. RateLimitError/429 is also caught for an actual RPM/TPM
        # cap, which LiteLLM does return as a genuine 429.
        raise HTTPException(status_code=429, detail="LLM budget exceeded for this user.") from exc
    return ChatResponse(
        thread_id=request.thread_id,
        self_contained_question=output["self_contained_question"],
        final_answer=output["final_answer"],
        routing_summary=build_routing_summary(output.get("routing_result", {})),
        guardrail_blocked_reason=output.get("guardrail_blocked_reason"),
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest, user: str = Depends(get_current_user)) -> StreamingResponse:
    """Streams this turn's progress as Server-Sent Events: a `status`
    event each time a graph node (`check_input`/`condense`/
    `invoke_routing_pipeline`/`check_output`/`record_turn`) finishes,
    then one final `answer` event with the complete response - or an
    `error` event if the LLM gateway rejects a call mid-stream (e.g. a
    budget-exceeded user). An `error` event, not an HTTP status code, is
    used for this because streaming has already started (with a 200) by
    the time such a rejection can happen.

    The `answer` event is deliberately emitted only once, after the
    whole graph finishes - not as soon as `invoke_routing_pipeline`
    completes - because `check_output`
    (app.chat.guardrails.scan_output, instructions/learnings/
    routing-lab-prod-plan.md section 2.4) runs *after* it and can
    replace a leaked-secret answer with a safe fallback; emitting at
    `invoke_routing_pipeline` would stream the unredacted answer before
    that guardrail ever got a chance to run. `check_input` can also
    short-circuit straight to `record_turn` without
    `invoke_routing_pipeline` ever running (a blocked prompt-injection
    attempt), so the running `final_answer`/`routing_result` are tracked
    across every node update rather than read off one specific node."""
    _thread_ownership.check_and_record(request.thread_id, user)
    _scope_llm_calls_to(user)
    config = {"configurable": {"thread_id": request.thread_id}}

    def event_stream():
        final_answer = ""
        routing_result: dict = {}
        guardrail_blocked_reason = None
        try:
            for update in _chat_graph.stream(
                {"user_message": request.message}, config=config, stream_mode="updates"
            ):
                for node_name, node_output in update.items():
                    yield f"event: status\ndata: {json.dumps({'node': node_name})}\n\n"
                    # `node_output` is None, not {}, for a node that
                    # returned no state update at all (e.g. check_input/
                    # check_output when nothing was blocked) - a real
                    # bug hit while wiring these guardrail nodes in.
                    if not node_output:
                        continue
                    if "final_answer" in node_output:
                        final_answer = node_output["final_answer"]
                    if "routing_result" in node_output:
                        routing_result = node_output["routing_result"]
                    if "guardrail_blocked_reason" in node_output:
                        guardrail_blocked_reason = node_output["guardrail_blocked_reason"]
            answer_payload = {
                "final_answer": final_answer,
                "routing_summary": build_routing_summary(routing_result),
                "guardrail_blocked_reason": guardrail_blocked_reason,
            }
            yield f"event: answer\ndata: {json.dumps(answer_payload)}\n\n"
        except (RateLimitError, UnprocessableEntityError):
            # See the /chat endpoint's comment above for why both
            # exception types are caught here too.
            error_payload = {"detail": "LLM budget exceeded for this user."}
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
