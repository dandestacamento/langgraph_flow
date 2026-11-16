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

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.cache import enable_llm_cache  # noqa: E402
from app.chat.graph import build_chat_graph  # noqa: E402

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
# docstring. Swap InMemorySaver() for a PostgresSaver per
# instructions/learnings/routing-lab-prod-plan.md section 2.2 once
# durable, multi-replica persistence is needed - no other code here
# changes, build_chat_graph() just takes a different checkpointer.
_chat_graph = build_chat_graph(checkpointer=InMemorySaver())


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    self_contained_question: str
    final_answer: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """One synchronous turn: invokes the chat graph and returns the full
    result. Simpler to call/test than `/chat/stream` - use this for
    anything that doesn't need incremental progress updates."""
    config = {"configurable": {"thread_id": request.thread_id}}
    output = _chat_graph.invoke({"user_message": request.message}, config=config)
    return ChatResponse(
        thread_id=request.thread_id,
        self_contained_question=output["self_contained_question"],
        final_answer=output["final_answer"],
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Streams this turn's progress as Server-Sent Events: a `status`
    event each time a graph node (`condense`/`invoke_routing_pipeline`/
    `record_turn`) finishes, then a final `answer` event with the
    complete response."""
    config = {"configurable": {"thread_id": request.thread_id}}

    def event_stream():
        for update in _chat_graph.stream(
            {"user_message": request.message}, config=config, stream_mode="updates"
        ):
            for node_name, node_output in update.items():
                yield f"event: status\ndata: {json.dumps({'node': node_name})}\n\n"
                if node_name == "invoke_routing_pipeline":
                    answer_payload = {"final_answer": node_output.get("final_answer", "")}
                    yield f"event: answer\ndata: {json.dumps(answer_payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
