"""FastAPI backend for the routing-lab6 chat application.

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

import hashlib
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

import os  # noqa: E402

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import Response, StreamingResponse  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from openai import RateLimitError, UnprocessableEntityError  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app import llm_gateway  # noqa: E402
from app.api import attachments as attachments_module  # noqa: E402
from app.api.attachments import (  # noqa: E402
    IMAGE_MEDIA_TYPES,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    SUPPORTED_MEDIA_TYPES,
    AttachmentStore,
    sniff_media_type,
)
from app.api.auth import ThreadOwnershipRegistry, get_current_user  # noqa: E402
from app.cache import enable_llm_cache  # noqa: E402
from app.chat.condense import generate_conversation_title  # noqa: E402
from app.chat.graph import build_chat_graph  # noqa: E402
from app.chat.routing_summary import build_routing_summary  # noqa: E402
from app.ingestion.graph import run_ingestion  # noqa: E402
from app.ingestion.registry import DocumentRegistry  # noqa: E402
from app.ingestion.storage import LocalDocumentStorage  # noqa: E402
from app.ingestion.taxonomy import taxonomy_store  # noqa: E402
from app.rag.retrieval import configure_document_registry, get_vector_store  # noqa: E402

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


_chat_checkpointer = _build_checkpointer()
_chat_graph = build_chat_graph(checkpointer=_chat_checkpointer)

# Persists alongside conversation history in the same Postgres database
# when CHAT_DB_URL is set (see ThreadOwnershipRegistry's own docstring,
# app/api/auth.py); in-memory (and lost together with conversation
# history on restart) otherwise.
_thread_ownership = ThreadOwnershipRegistry(conn_string=_CHAT_DB_URL)

# Attachment storage (chat-ui-plan4.md Phase A) - same dual-mode
# Postgres/in-memory pattern as the ownership registry above.
_attachment_store = AttachmentStore(conn_string=_CHAT_DB_URL)

# Knowledge-ingestion pipeline (chat-ui-plan5.md Phase A): document
# registry + immutable original storage under data/ (gitignored).
_document_registry = DocumentRegistry(conn_string=_CHAT_DB_URL)
_document_registry.recover_interrupted_replacements()
configure_document_registry(lambda: _document_registry)
_document_storage = LocalDocumentStorage(PROJECT_ROOT / "data")

# Ingestion documents are text knowledge, not chat snapshots - images are
# deliberately NOT accepted here (that's the chat attachment flow).
_INGESTABLE_MEDIA_TYPES = ("application/pdf", "text/plain")

# Startup sweep (chat-ui-plan3.md §1.1): conversations soft-deleted more
# than 30 days ago are purged for real - ownership record and
# checkpointed history together.
for _purged_thread_id in _thread_ownership.purge_soft_deleted(older_than_days=30):
    _chat_checkpointer.delete_thread(_purged_thread_id)


def _maybe_generate_title(thread_id: str, user_message: str, final_answer: str, turn_count: int) -> None:
    """After a conversation's *first* turn, replace the raw-message title
    with a short LLM-generated one (chat-ui-plan3.md §1.2). Never raises:
    a title is cosmetic, and must not fail a turn that already succeeded.
    `set_generated_title` itself skips user-renamed titles."""
    if turn_count != 1:
        return
    try:
        title = generate_conversation_title(user_message, final_answer)
        _thread_ownership.set_generated_title(thread_id, title)
    except Exception:  # noqa: BLE001 - see docstring
        _client_error_logger.warning("Title generation failed for thread %s", thread_id)

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
    # Previously uploaded attachment ids this message references
    # (chat-ui-plan4.md §1.4). Must belong to the same thread - 404
    # otherwise.
    attachment_ids: list[str] = []


class ThreadSummary(BaseModel):
    """One row of the conversation list (chat-ui-plan1.md Phase E) -
    served straight from `ThreadOwnershipRegistry`'s records."""

    thread_id: str
    title: str
    updated_at: str


class ThreadHistoryTurn(BaseModel):
    """One past turn of a conversation, restored from the checkpointer's
    `conversation_history` (app/chat/state.py's ChatTurn). Includes the
    per-turn routing summary and attachment metadata so citations and
    attachment pills survive a page refresh; turns recorded before those
    fields existed return `{}`/`[]` (the frontend renders them as plain
    messages)."""

    user_message: str
    final_answer: str
    routing_summary: dict = {}
    attachments: list[dict] = []


class ClientErrorReport(BaseModel):
    """What the frontend's error boundary (src/components/
    ErrorBoundary.tsx) reports when it catches a render crash."""

    message: str
    stack: str | None = None
    component_stack: str | None = None
    url: str | None = None


class ThreadRenameRequest(BaseModel):
    title: str


class AttachmentMeta(BaseModel):
    """Metadata returned by the upload endpoint - mirrored by the
    frontend's `AttachmentMeta` (chat-ui-plan4.md Phase A/B).
    `extracted_chars == 0` on a document means no readable text (e.g. a
    scanned PDF) - the UI warns instead of a later turn hallucinating."""

    attachment_id: str
    filename: str
    media_type: str
    size_bytes: int
    extracted_chars: int = 0


class PendingKnowledgeDocument(BaseModel):
    version: int
    topic: str | None = None
    subtopic: str | None = None
    classification_confidence: float | None = None


class KnowledgeDocument(BaseModel):
    """One ingested document's registry view (chat-ui-plan5.md Phase A) -
    classification, status, chunk count, and the per-node event log that
    the later Ingestion Inspector will render."""

    document_id: str
    filename: str
    media_type: str
    size_bytes: int
    version: int
    status: str
    topic: str | None = None
    subtopic: str | None = None
    chapters: list[str] = []
    classification_confidence: float | None = None
    error: str | None = None
    chunk_count: int = 0
    chunk_ids: list[str] = []
    events: list[dict] = []
    created_at: str
    updated_at: str
    pending: PendingKnowledgeDocument | None = None
    # True on an upload response when these exact bytes were already
    # ingested - the existing document is returned, nothing reprocessed.
    duplicate: bool = False


def _knowledge_document(record: dict, duplicate: bool = False) -> KnowledgeDocument:
    return KnowledgeDocument(
        **{key: record[key] for key in KnowledgeDocument.model_fields if key in record},
        duplicate=duplicate,
    )


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


@app.get("/threads", response_model=list[ThreadSummary])
def list_threads(user: str = Depends(get_current_user)) -> list[ThreadSummary]:
    """The authenticated user's conversations, most recently active
    first - only ever their own (chat-ui-plan1.md Phase E's exit
    criterion), since the registry filters by the token's `sub`."""
    return [ThreadSummary(**thread) for thread in _thread_ownership.list_threads(user)]


@app.get("/threads/{thread_id}/history", response_model=list[ThreadHistoryTurn])
def thread_history(thread_id: str, user: str = Depends(get_current_user)) -> list[ThreadHistoryTurn]:
    """Past turns of one conversation, so the frontend can restore a
    switched-to (or refreshed) conversation's messages. 404 for a
    thread_id the registry has never seen, 403 for another user's -
    read-only, so this never *records* ownership the way /chat does."""
    _thread_ownership.check_owner(thread_id, user)
    snapshot = _chat_graph.get_state({"configurable": {"thread_id": thread_id}})
    turns = (snapshot.values or {}).get("conversation_history", [])
    return [
        ThreadHistoryTurn(
            user_message=turn["user_message"],
            final_answer=turn["final_answer"],
            routing_summary=turn.get("routing_summary", {}),
            attachments=turn.get("attachments", []),
        )
        for turn in turns
    ]


@app.patch("/threads/{thread_id}", status_code=204)
def rename_thread(
    thread_id: str, request: ThreadRenameRequest, user: str = Depends(get_current_user)
) -> Response:
    """Renames one of the authenticated user's own conversations."""
    if not request.title.strip():
        raise HTTPException(status_code=422, detail="Title must not be empty.")
    _thread_ownership.rename(thread_id, user, request.title)
    return Response(status_code=204)


@app.delete("/threads/{thread_id}", status_code=204)
def delete_thread(
    thread_id: str, permanent: bool = False, user: str = Depends(get_current_user)
) -> Response:
    """Soft-deletes one of the authenticated user's own conversations:
    it leaves the list and can't be resumed, but POST
    /threads/{id}/restore undoes it within the purge window
    (chat-ui-plan3.md §1.1). `?permanent=true` removes the ownership
    record AND the checkpointed history immediately - the old
    unrecoverable behavior, now opt-in."""
    _thread_ownership.delete(thread_id, user, permanent=permanent)
    if permanent:
        _chat_checkpointer.delete_thread(thread_id)
    return Response(status_code=204)


@app.post("/threads/{thread_id}/restore", status_code=204)
def restore_thread(thread_id: str, user: str = Depends(get_current_user)) -> Response:
    """Undoes a soft delete of the user's own conversation - the
    frontend's Undo toast (chat-ui-plan3.md §1.1)."""
    _thread_ownership.restore(thread_id, user)
    return Response(status_code=204)


@app.post("/threads/{thread_id}/attachments", response_model=AttachmentMeta)
async def upload_attachment(
    thread_id: str, file: UploadFile, user: str = Depends(get_current_user)
) -> AttachmentMeta:
    """Uploads one attachment to the user's own conversation
    (chat-ui-plan4.md: images in Phase A, PDF/text documents in Phase B).
    Claims a brand-new thread_id the same way /chat does, so a file can
    be attached before the conversation's first message. The media type
    is sniffed from the content - the client's content type and filename
    are never trusted - and extraction (a vision call for images, local
    parsing for documents) happens here, once, not on every chat turn
    that references the attachment."""
    _thread_ownership.check_and_record(thread_id, user)
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large - the limit is {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.",
        )
    media_type = sniff_media_type(content)
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Supported: {', '.join(SUPPORTED_MEDIA_TYPES)}.",
        )
    if media_type in IMAGE_MEDIA_TYPES:
        _scope_llm_calls_to(user)  # the vision extraction is an LLM call
    extracted_text = attachments_module.extract_text(content, media_type)
    meta = _attachment_store.save(
        thread_id, file.filename or "attachment", media_type, content, extracted_text
    )
    return AttachmentMeta(**meta, extracted_chars=len(extracted_text))


@app.get("/threads/{thread_id}/attachments/{attachment_id}")
def get_attachment(
    thread_id: str, attachment_id: str, user: str = Depends(get_current_user)
) -> Response:
    """Streams an attachment's bytes back (image thumbnails in restored
    history) - ownership-checked like every thread route, and the id
    must belong to this very thread."""
    _thread_ownership.check_owner(thread_id, user)
    stored = _attachment_store.get_content(thread_id, attachment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Unknown attachment for this conversation.")
    content, media_type = stored
    return Response(content=content, media_type=media_type)


def _cleanup_previous_chunks(existing: dict) -> dict:
    if not existing["cleanup_ids"]:
        return existing
    try:
        get_vector_store().delete(ids=existing["cleanup_ids"])
    except Exception as exc:
        _document_registry.update(existing["document_id"], error=f"Old chunk cleanup failed: {exc}")
        raise HTTPException(status_code=503, detail="Previous version cleanup failed; retry the upload.") from exc
    _document_registry.update(existing["document_id"], cleanup_ids=[], error=None)
    return _document_registry.get(existing["document_id"]) or existing


def _start_document_replacement(
    existing: dict, content: bytes, media_type: str, background_tasks: BackgroundTasks, user: str,
    *, indexed_only: bool = False,
) -> KnowledgeDocument:
    if not existing["chunk_ids"]:
        raise HTTPException(status_code=409, detail="The existing document is not indexed; resolve it before replacing it.")
    content_hash = hashlib.sha256(content).hexdigest()
    previous_pending = existing.get("pending")
    next_version = max(existing["version"], previous_pending["version"] if previous_pending else 0) + 1
    abandoned_versions = (
        [*previous_pending.get("abandoned_versions", []), previous_pending["version"]]
        if previous_pending and existing["status"] == "failed" else []
    )
    pending = {
        "version": next_version, "content_hash": content_hash, "media_type": media_type,
        "size_bytes": len(content), "stored_path": "", "topic": None, "subtopic": None,
        "classification_confidence": None, "chapters": [], "abandoned_versions": abandoned_versions,
    }
    if not _document_registry.begin_replacement(
        existing["document_id"], existing["version"], pending, indexed_only=indexed_only,
    ):
        raise HTTPException(status_code=409, detail="Another replacement is processing or awaiting review.")
    if abandoned_versions:
        try:
            store = get_vector_store()
            for version in abandoned_versions:
                abandoned = store.get(where={"$and": [
                    {"document_id": existing["document_id"]}, {"version": version},
                ]})["ids"]
                if abandoned:
                    store.delete(ids=abandoned)
        except Exception as exc:
            _document_registry.update(existing["document_id"], status="failed", error=f"Replacement cleanup failed: {exc}")
            raise HTTPException(status_code=503, detail="Failed replacement cleanup failed; retry the upload.") from exc
        pending["abandoned_versions"] = []
    try:
        pending["stored_path"] = _document_storage.save_original(
            existing["document_id"], next_version, existing["filename"], content
        )
    except OSError as exc:
        _document_registry.update(existing["document_id"], status="failed", error=f"Replacement storage failed: {exc}")
        raise HTTPException(status_code=500, detail="Could not store the replacement; the indexed version remains available.") from exc
    _document_registry.update(existing["document_id"], pending=pending)
    replacement = {
        **existing, "version": next_version, "media_type": media_type,
        "is_replacement": True,
    }
    _scope_llm_calls_to(user)
    background_tasks.add_task(run_ingestion, _document_registry, replacement, content)
    return _knowledge_document(_document_registry.get(existing["document_id"]) or existing)


@app.post("/knowledge/documents", response_model=KnowledgeDocument)
async def upload_knowledge_document(
    file: UploadFile, background_tasks: BackgroundTasks, user: str = Depends(get_current_user)
) -> KnowledgeDocument:
    """Uploads one document into the knowledge-ingestion pipeline
    (chat-ui-plan5.md Phase A). The upload returns immediately with
    status 'processing'; the ingestion LangGraph workflow (validate ->
    extract -> classify -> chunk -> index -> validate retrieval ->
    publish) runs as a background task so it never blocks chat traffic.
    Identical bytes uploaded twice return the existing document with
    `duplicate: true` - nothing is reprocessed or reindexed."""
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large - the limit is {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.",
        )
    media_type = sniff_media_type(content)
    if media_type not in _INGESTABLE_MEDIA_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported knowledge-document type. Supported: PDF and UTF-8 text "
                "(md/txt/csv/json/log)."
            ),
        )

    content_hash = hashlib.sha256(content).hexdigest()
    filename = file.filename or "document"
    matches = [r for r in _document_registry.list_documents() if r["filename"] == filename]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Multiple documents have this filename; automatic replacement is ambiguous.")
    if matches:
        existing = _cleanup_previous_chunks(matches[0])
        pending = existing.get("pending")
        if content_hash == existing["content_hash"] or (pending and content_hash == pending["content_hash"] and existing["status"] != "failed"):
            return _knowledge_document(existing, duplicate=True)
        return _start_document_replacement(existing, content, media_type, background_tasks, user)

    existing = _document_registry.find_by_hash(content_hash)
    if existing is not None:
        return _knowledge_document(existing, duplicate=True)

    record = _document_registry.create(
        filename=filename,
        media_type=media_type,
        size_bytes=len(content),
        content_hash=content_hash,
        uploaded_by=user,
    )
    stored_path = _document_storage.save_original(
        record["document_id"], record["version"], record["filename"], content
    )
    _document_registry.update(record["document_id"], stored_path=stored_path)

    _scope_llm_calls_to(user)  # classification is an LLM call billed to the uploader
    background_tasks.add_task(run_ingestion, _document_registry, record, content)
    return _knowledge_document({**record, "stored_path": stored_path})


@app.post("/knowledge/documents/{document_id}/reindex", response_model=KnowledgeDocument)
def reindex_knowledge_document(
    document_id: str, background_tasks: BackgroundTasks, user: str = Depends(get_current_user),
) -> KnowledgeDocument:
    record = _document_registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown document.")
    if record["status"] != "indexed" or record.get("pending") or not record["chunk_ids"]:
        raise HTTPException(status_code=409, detail="Only an indexed document without a pending replacement can be re-indexed.")
    try:
        content = _document_storage.read_original(document_id, record["version"], record["filename"])
    except OSError as exc:
        raise HTTPException(status_code=409, detail="The indexed document's stored original is unavailable.") from exc
    if hashlib.sha256(content).hexdigest() != record["content_hash"]:
        raise HTTPException(status_code=409, detail="The stored original does not match the indexed document.")
    original_version = record["version"]
    record = _cleanup_previous_chunks(record)
    if record["version"] != original_version:
        raise HTTPException(status_code=409, detail="The indexed document changed; retry re-indexing.")
    return _start_document_replacement(
        record, content, record["media_type"], background_tasks, user, indexed_only=True,
    )


@app.get("/knowledge/documents", response_model=list[KnowledgeDocument])
def list_knowledge_documents(user: str = Depends(get_current_user)) -> list[KnowledgeDocument]:
    """Every ingested document with its status - the Knowledge Base
    Manager's job list. Knowledge is shared across authenticated users
    (per-document permissions are a later plan5 phase)."""
    return [_knowledge_document(record) for record in _document_registry.list_documents()]


@app.get("/knowledge/documents/{document_id}", response_model=KnowledgeDocument)
def get_knowledge_document(
    document_id: str, user: str = Depends(get_current_user)
) -> KnowledgeDocument:
    """One document's full detail, including the per-node event log."""
    record = _document_registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown document.")
    return _knowledge_document(record)


class ManualClassificationRequest(BaseModel):
    topic: str
    subtopic: str
    create_missing: bool = False


@app.get("/knowledge/taxonomy")
def get_knowledge_taxonomy(user: str = Depends(get_current_user)) -> dict[str, list[str]]:
    """The curated and approved topic -> subtopic taxonomy."""
    return taxonomy_store().get()


@app.post("/knowledge/documents/{document_id}/suggestion", response_model=KnowledgeDocument)
def refresh_classification_suggestion(
    document_id: str,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
) -> KnowledgeDocument:
    record = _document_registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown document.")
    if record["status"] != "needs_review":
        raise HTTPException(status_code=409, detail="Only documents awaiting review can be reclassified.")
    pending = record.get("pending")
    version = pending["version"] if pending else record["version"]
    content = _document_storage.read_original(record["document_id"], version, record["filename"])
    if pending:
        if not _document_registry.resume_replacement(document_id, ("needs_review",)):
            raise HTTPException(status_code=409, detail="Replacement is no longer awaiting review.")
        record = {**record, "version": version, "media_type": pending["media_type"], "is_replacement": True}
    else:
        _document_registry.update(document_id, status="processing", error=None)
    _scope_llm_calls_to(user)
    background_tasks.add_task(run_ingestion, _document_registry, record, content)
    return _knowledge_document(_document_registry.get(document_id) or record)


@app.post("/knowledge/documents/{document_id}/classification", response_model=KnowledgeDocument)
def override_classification(
    document_id: str,
    request: ManualClassificationRequest,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
) -> KnowledgeDocument:
    """Manually (re)classifies a document (plan5 Phase B's override):
    validates the chosen taxonomy, removes any chunks indexed under the
    old classification, and re-runs the ingestion workflow from the
    stored original with the human-supplied topic/subtopic - which also
    un-parks `needs_review` documents."""
    record = _document_registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown document.")
    if record["status"] == "processing":
        raise HTTPException(status_code=409, detail="Document is still being processed.")
    taxonomy = taxonomy_store().get()
    if request.subtopic not in taxonomy.get(request.topic, []):
        if not request.create_missing:
            raise HTTPException(status_code=422, detail="Unknown topic or subtopic; creation requires approval.")
        try:
            taxonomy_store().add(request.topic, request.subtopic)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    pending = record.get("pending")
    if pending:
        content = _document_storage.read_original(record["document_id"], pending["version"], record["filename"])
        if not _document_registry.resume_replacement(document_id, ("needs_review", "failed")):
            raise HTTPException(status_code=409, detail="Replacement is no longer awaiting review.")
        replacement = {
            **record, "version": pending["version"], "media_type": pending["media_type"], "is_replacement": True,
        }
        _scope_llm_calls_to(user)
        background_tasks.add_task(
            run_ingestion, _document_registry, replacement, content, request.topic, request.subtopic,
        )
        return _knowledge_document(_document_registry.get(document_id) or record)

    # Surgical removal of the previous classification's chunks (if any)
    # before reindexing under the corrected one.
    if record["chunk_ids"]:
        get_vector_store().delete(ids=record["chunk_ids"])
    _document_registry.update(
        document_id, status="processing", error=None, chunk_ids=[], chunk_count=0,
        events=[*record["events"], {
            "node": "manual_override",
            "elapsed_ms": 0,
            "detail": f"reclassified by user as {request.topic}/{request.subtopic}",
        }],
    )
    content = _document_storage.read_original(
        record["document_id"], record["version"], record["filename"]
    )
    _scope_llm_calls_to(user)
    background_tasks.add_task(
        run_ingestion,
        _document_registry,
        record,
        content,
        request.topic,
        request.subtopic,
    )
    return _knowledge_document(_document_registry.get(document_id) or record)


_client_error_logger = logging.getLogger("routing_lab6.client_errors")


@app.post("/client-error", status_code=204)
def report_client_error(
    report: ClientErrorReport, user: str = Depends(get_current_user)
) -> Response:
    """Receives the frontend error boundary's crash reports and emits
    them through standard Python logging - once the self-hosted
    Grafana/Loki stack (routing-lab-prod-plan.md section 2.5) is live,
    this process's log stream (and therefore these entries) flows into
    it with no change here; deliberately not a proprietary SaaS SDK."""
    _client_error_logger.error(
        "Frontend error from user %s at %s: %s\nStack: %s\nComponent stack: %s",
        user,
        report.url or "<unknown url>",
        report.message,
        report.stack or "<none>",
        report.component_stack or "<none>",
    )
    return Response(status_code=204)


def _load_turn_attachments(request: ChatRequest) -> list[dict]:
    """This turn's attachment metadata + extracted text for the graph -
    404s on ids that don't belong to the thread, 422 over the cap."""
    if len(request.attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message.",
        )
    if not request.attachment_ids:
        return []
    return _attachment_store.get_meta_for_chat(request.thread_id, request.attachment_ids)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, user: str = Depends(get_current_user)) -> ChatResponse:
    """One synchronous turn: invokes the chat graph and returns the full
    result. Simpler to call/test than `/chat/stream` - use this for
    anything that doesn't need incremental progress updates."""
    _thread_ownership.check_and_record(request.thread_id, user, title=request.message)
    turn_attachments = _load_turn_attachments(request)
    _scope_llm_calls_to(user)
    config = {"configurable": {"thread_id": request.thread_id}}
    try:
        output = _chat_graph.invoke(
            {"user_message": request.message, "attachments": turn_attachments}, config=config
        )
    except (RateLimitError, UnprocessableEntityError) as exc:
        # LiteLLM returns HTTP 422 (UnprocessableEntityError in the
        # openai SDK's exception hierarchy, not RateLimitError) for a
        # budget-exceeded virtual key specifically - confirmed
        # empirically while validating this phase, not assumed from
        # docs. RateLimitError/429 is also caught for an actual RPM/TPM
        # cap, which LiteLLM does return as a genuine 429.
        raise HTTPException(status_code=429, detail="LLM budget exceeded for this user.") from exc
    _maybe_generate_title(
        request.thread_id,
        request.message,
        output["final_answer"],
        turn_count=len(output.get("conversation_history", [])),
    )
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
    _thread_ownership.check_and_record(request.thread_id, user, title=request.message)
    turn_attachments = _load_turn_attachments(request)
    _scope_llm_calls_to(user)
    config = {"configurable": {"thread_id": request.thread_id}}

    def event_stream():
        final_answer = ""
        routing_result: dict = {}
        guardrail_blocked_reason = None
        # Per-node wall-clock timings for the frontend's execution
        # timeline (chat-ui-plan3.md §2.2) - each status event carries
        # the time spent since the previous one, i.e. roughly that
        # node's own duration.
        previous_event_time = time.perf_counter()
        try:
            for update in _chat_graph.stream(
                {"user_message": request.message, "attachments": turn_attachments},
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in update.items():
                    now = time.perf_counter()
                    elapsed_ms = round((now - previous_event_time) * 1000)
                    previous_event_time = now
                    yield (
                        "event: status\n"
                        f"data: {json.dumps({'node': node_name, 'elapsed_ms': elapsed_ms})}\n\n"
                    )
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
            # After the answer is already on the wire (so this adds no
            # perceived latency), generate the conversation title for a
            # first turn - chat-ui-plan3.md §1.2.
            snapshot = _chat_graph.get_state(config)
            _maybe_generate_title(
                request.thread_id,
                request.message,
                final_answer,
                turn_count=len((snapshot.values or {}).get("conversation_history", [])),
            )
        except (RateLimitError, UnprocessableEntityError):
            # See the /chat endpoint's comment above for why both
            # exception types are caught here too.
            error_payload = {"detail": "LLM budget exceeded for this user."}
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
