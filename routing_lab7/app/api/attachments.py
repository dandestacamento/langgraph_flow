"""Attachment storage & extraction for routing_lab7's chat API
(instructions/learnings/chat-ui-plan4.md Phase A).

Attachments are extracted ONCE at upload time (a vision call for
images - `AGENT_MODEL`/gpt-4o-mini accepts image input, no new model),
and the stored `extracted_text` is what later chat turns consume - the
chat turn itself adds no extra latency and the same attachment can be
referenced across turns for free.

Storage mirrors `ThreadOwnershipRegistry`'s dual mode: a Postgres table
when a connection string is given (BYTEA content - uploads are capped
small, and plan4 §1.1 deliberately avoids new object-store
infrastructure for v1), in-memory otherwise.

`_extract_image_text` is a module-level, monkeypatchable indirection -
same pattern as app/api/auth.py's `_get_signing_key` - so API tests can
exercise the full upload->chat flow deterministically without a live
vision call.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app import llm_gateway
from app.config import AGENT_MODEL

# Phase A allowlist: images. Phase B adds documents (PDF + UTF-8 text
# family). SVG is deliberately excluded - it's scriptable content, not a
# bitmap.
IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
DOCUMENT_MEDIA_TYPES = ("application/pdf", "text/plain")
SUPPORTED_MEDIA_TYPES = IMAGE_MEDIA_TYPES + DOCUMENT_MEDIA_TYPES
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 4
MAX_EXTRACTED_CHARS = 8000

_VISION_PROMPT = (
    "Describe what this image shows, concisely and factually. Transcribe any visible text, "
    "error codes, model numbers, or display readouts verbatim - those details matter most. "
    "Do not speculate beyond what is visible."
)


def sniff_media_type(content: bytes) -> str | None:
    """Determines the media type from the content itself - the
    client-supplied content type is never trusted (plan4 §1.3). Images
    and PDFs by magic bytes; anything else that cleanly decodes as UTF-8
    text is accepted as text/plain (text has no magic bytes)."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # A NUL byte means binary data mislabeled as text - reject it.
    return None if "\x00" in decoded else "text/plain"


def _default_extract_image_text(content: bytes, media_type: str) -> str:
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0, **llm_gateway.llm_kwargs())
    data_url = f"data:{media_type};base64,{base64.b64encode(content).decode()}"
    result = llm.invoke(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": _VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
            )
        ]
    )
    return str(result.content).strip()[:MAX_EXTRACTED_CHARS]


# Test-only hook (see tests/test_chat_api.py): monkeypatched so the
# upload->chat integration is deterministic without a live vision call.
_extract_image_text: Callable[[bytes, str], str] = _default_extract_image_text


def extract_document_text(content: bytes, media_type: str) -> str:
    """Extracts a document's text locally - no LLM call (plan4 §1.2).
    PDF pages are separated by blank lines so ingestion can chunk them
    separately. A scanned/image-only PDF yields an empty string; the API
    surfaces that honestly (`extracted_chars` in the upload response)
    instead of letting a later turn hallucinate a summary."""
    if media_type == "application/pdf":
        import io

        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:  # noqa: BLE001 - a malformed PDF is "no text", not a 500
            return ""
        return text.strip()[:MAX_EXTRACTED_CHARS]
    # text/plain family - sniff_media_type already proved it decodes.
    return content.decode("utf-8", errors="replace").strip()[:MAX_EXTRACTED_CHARS]


def extract_text(content: bytes, media_type: str) -> str:
    """Dispatches extraction by media type: vision for images (via the
    monkeypatchable indirection above), local parsing for documents."""
    if media_type in IMAGE_MEDIA_TYPES:
        return _extract_image_text(content, media_type)
    return extract_document_text(content, media_type)


class AttachmentStore:
    """Per-thread attachment storage - Postgres (BYTEA) or in-memory,
    the same dual-mode pattern as ThreadOwnershipRegistry."""

    def __init__(self, conn_string: str | None = None) -> None:
        # attachment_id -> record dict (in-memory mode)
        self._records: dict[str, dict] = {}
        self._conn_string = conn_string
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string, autocommit=True) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS thread_attachments ("
                    "attachment_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, "
                    "filename TEXT NOT NULL, media_type TEXT NOT NULL, "
                    "size_bytes INTEGER NOT NULL, content BYTEA NOT NULL, "
                    "extracted_text TEXT NOT NULL DEFAULT '', "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS thread_attachments_thread_idx "
                    "ON thread_attachments (thread_id)"
                )

    def save(
        self, thread_id: str, filename: str, media_type: str, content: bytes, extracted_text: str
    ) -> dict:
        """Stores an attachment and returns its metadata (no content)."""
        attachment_id = str(uuid.uuid4())
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "INSERT INTO thread_attachments "
                    "(attachment_id, thread_id, filename, media_type, size_bytes, content, "
                    "extracted_text) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (attachment_id, thread_id, filename, media_type, len(content), content,
                     extracted_text),
                )
        else:
            self._records[attachment_id] = {
                "thread_id": thread_id,
                "filename": filename,
                "media_type": media_type,
                "size_bytes": len(content),
                "content": content,
                "extracted_text": extracted_text,
                "created_at": datetime.now(timezone.utc),
            }
        return {
            "attachment_id": attachment_id,
            "filename": filename,
            "media_type": media_type,
            "size_bytes": len(content),
        }

    def get_content(self, thread_id: str, attachment_id: str) -> tuple[bytes, str] | None:
        """(content, media_type) - None when the id is unknown OR belongs
        to a different thread (no cross-thread reads, plan4 §1.1)."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                row = conn.execute(
                    "SELECT content, media_type FROM thread_attachments "
                    "WHERE attachment_id = %s AND thread_id = %s",
                    (attachment_id, thread_id),
                ).fetchone()
            return (bytes(row[0]), row[1]) if row is not None else None
        record = self._records.get(attachment_id)
        if record is None or record["thread_id"] != thread_id:
            return None
        return record["content"], record["media_type"]

    def get_meta_for_chat(self, thread_id: str, attachment_ids: list[str]) -> list[dict]:
        """Metadata + extracted text for a chat turn's attachments.
        404s if any id is unknown or belongs to a different thread."""
        metas: list[dict] = []
        for attachment_id in attachment_ids:
            if self._conn_string:
                import psycopg

                with psycopg.connect(self._conn_string, autocommit=True) as conn:
                    row = conn.execute(
                        "SELECT filename, media_type, extracted_text FROM thread_attachments "
                        "WHERE attachment_id = %s AND thread_id = %s",
                        (attachment_id, thread_id),
                    ).fetchone()
                record = (
                    {"filename": row[0], "media_type": row[1], "extracted_text": row[2]}
                    if row is not None
                    else None
                )
            else:
                stored = self._records.get(attachment_id)
                record = (
                    {
                        "filename": stored["filename"],
                        "media_type": stored["media_type"],
                        "extracted_text": stored["extracted_text"],
                    }
                    if stored is not None and stored["thread_id"] == thread_id
                    else None
                )
            if record is None:
                raise HTTPException(
                    status_code=404, detail=f"Unknown attachment for this conversation: {attachment_id}"
                )
            metas.append({"attachment_id": attachment_id, **record})
        return metas
