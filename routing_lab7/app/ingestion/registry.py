"""Document registry for the ingestion pipeline (chat-ui-plan5.md §6).

Tracks every ingested document's identity (content hash - the dedup
key), classification, processing status, error, resulting vector-chunk
ids (so updates/deletes can surgically replace exactly this document's
chunks), and a per-node event log that will power the later Ingestion
Inspector UI.

Dual-mode Postgres/in-memory, the same pattern as
app/api/auth.py's ThreadOwnershipRegistry and app/api/attachments.py's
AttachmentStore: Postgres when `CHAT_DB_URL` is set, in-memory (lost on
restart) otherwise - which is also what the test suite uses.

Statuses:
    processing   - upload accepted, ingestion graph running
    indexed      - published; chunks are live in the vector index
    needs_review - classification was invalid/low-confidence; parked for
                   the Phase C human-review flow (visible via the API,
                   not indexed)
    failed       - a node failed; `error` says which and why
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

VALID_STATUSES = ("processing", "indexed", "needs_review", "failed")

# Columns that are JSON-encoded in Postgres / kept as objects in memory.
_JSON_FIELDS = ("chapters", "chunk_ids", "events", "pending", "cleanup_ids")


def new_document_id() -> str:
    return f"DOC-{uuid.uuid4().hex[:8]}"


class DocumentRegistry:
    def __init__(self, conn_string: str | None = None) -> None:
        self._records: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._conn_string = conn_string
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string, autocommit=True) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS knowledge_documents ("
                    "document_id TEXT PRIMARY KEY, filename TEXT NOT NULL, "
                    "media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, "
                    "content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, "
                    "status TEXT NOT NULL, uploaded_by TEXT NOT NULL DEFAULT '', "
                    "topic TEXT, subtopic TEXT, chapters TEXT NOT NULL DEFAULT '[]', "
                    "classification_confidence REAL, error TEXT, "
                    "chunk_count INTEGER NOT NULL DEFAULT 0, "
                    "chunk_ids TEXT NOT NULL DEFAULT '[]', "
                    "events TEXT NOT NULL DEFAULT '[]', "
                    "stored_path TEXT NOT NULL DEFAULT '', "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                conn.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS pending TEXT")
                conn.execute(
                    "ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS cleanup_ids TEXT NOT NULL DEFAULT '[]'"
                )

    def create(
        self,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_hash: str,
        uploaded_by: str,
        stored_path: str = "",
    ) -> dict:
        record = {
            "document_id": new_document_id(),
            "filename": filename,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "version": 1,
            "status": "processing",
            "uploaded_by": uploaded_by,
            "topic": None,
            "subtopic": None,
            "chapters": [],
            "classification_confidence": None,
            "error": None,
            "chunk_count": 0,
            "chunk_ids": [],
            "events": [],
            "pending": None,
            "cleanup_ids": [],
            "stored_path": stored_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "INSERT INTO knowledge_documents (document_id, filename, media_type, "
                    "size_bytes, content_hash, version, status, uploaded_by, chapters, "
                    "chunk_ids, events, stored_path) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        record["document_id"], filename, media_type, size_bytes, content_hash,
                        1, "processing", uploaded_by, "[]", "[]", "[]", stored_path,
                    ),
                )
        else:
            self._records[record["document_id"]] = record
        return dict(record)

    def update(self, document_id: str, **fields) -> None:
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._conn_string:
            import psycopg

            assignments = []
            values = []
            for key, value in fields.items():
                assignments.append(f"{key} = %s")
                values.append(json.dumps(value) if key in _JSON_FIELDS else value)
            values.append(document_id)
            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    f"UPDATE knowledge_documents SET {', '.join(assignments)} "
                    "WHERE document_id = %s",
                    values,
                )
        else:
            record = self._records.get(document_id)
            if record is not None:
                record.update(fields)

    def append_event(self, document_id: str, node: str, elapsed_ms: int, detail: str = "") -> None:
        """Adds one step to the document's processing log - the raw
        material for the later Ingestion Inspector."""
        event = {
            "node": node,
            "elapsed_ms": elapsed_ms,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        record = self.get(document_id)
        if record is None:
            return
        self.update(document_id, events=[*record["events"], event])

    def get(self, document_id: str) -> dict | None:
        if self._conn_string:
            result = self._fetch("document_id = %s", (document_id,), one=True)
            return result  # type: ignore[return-value]
        record = self._records.get(document_id)
        return dict(record) if record is not None else None

    def find_by_hash(self, content_hash: str) -> dict | None:
        """The dedup lookup: the same bytes uploaded again should point
        at the existing document instead of reprocessing/reindexing."""
        if self._conn_string:
            result = self._fetch("content_hash = %s", (content_hash,), one=True)
            return result  # type: ignore[return-value]
        for record in self._records.values():
            if record["content_hash"] == content_hash:
                return dict(record)
        return None

    def begin_replacement(
        self, document_id: str, version: int, pending: dict, *, indexed_only: bool = False
    ) -> bool:
        """Reserve one replacement attempt without changing the published version."""
        now = datetime.now(timezone.utc).isoformat()
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                row = conn.execute(
                    "UPDATE knowledge_documents SET pending = %s, status = 'processing', "
                    "error = NULL, updated_at = %s WHERE document_id = %s AND version = %s "
                    "AND (status = 'indexed' OR (status = 'failed' AND pending IS NOT NULL)) "
                    "AND (NOT %s OR (status = 'indexed' AND (pending IS NULL OR pending = 'null'))) "
                    "RETURNING document_id",
                    (json.dumps(pending), now, document_id, version, indexed_only),
                ).fetchone()
                return row is not None
        with self._lock:
            record = self._records.get(document_id)
            if (
                record is None or record["version"] != version
                or not (record["status"] == "indexed" or (record["status"] == "failed" and record["pending"]))
                or (indexed_only and (record["status"] != "indexed" or record["pending"]))
            ):
                return False
            record.update(pending=pending, status="processing", error=None, updated_at=now)
            return True

    def resume_replacement(self, document_id: str, statuses: tuple[str, ...]) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                row = conn.execute(
                    "UPDATE knowledge_documents SET status = 'processing', error = NULL, updated_at = %s "
                    "WHERE document_id = %s AND pending IS NOT NULL AND pending <> 'null' "
                    "AND status = ANY(%s) RETURNING document_id",
                    (now, document_id, list(statuses)),
                ).fetchone()
                return row is not None
        with self._lock:
            record = self._records.get(document_id)
            if record is None or not record["pending"] or record["status"] not in statuses:
                return False
            record.update(status="processing", error=None, updated_at=now)
            return True

    def recover_interrupted_replacements(self) -> None:
        """Mark abandoned replacements for retry when the sole backend starts."""
        message = "Replacement interrupted by backend restart; upload the changed file again to retry."
        now = datetime.now(timezone.utc).isoformat()
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "UPDATE knowledge_documents SET status = 'failed', error = %s, updated_at = %s "
                    "WHERE status = 'processing' AND pending IS NOT NULL AND pending <> 'null'",
                    (message, now),
                )
            return
        with self._lock:
            for record in self._records.values():
                if record["status"] == "processing" and record["pending"]:
                    record.update(status="failed", error=message, updated_at=now)

    def list_documents(self) -> list[dict]:
        if self._conn_string:
            return self._fetch("TRUE", (), one=False)  # type: ignore[return-value]
        records = [dict(r) for r in self._records.values()]
        records.sort(key=lambda r: r["created_at"], reverse=True)
        return records

    def active_versions(self) -> tuple[tuple[str, int], ...]:
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                rows = conn.execute(
                    "SELECT document_id, version FROM knowledge_documents WHERE chunk_count > 0 ORDER BY document_id"
                ).fetchall()
            return tuple(rows)
        return tuple(sorted(
            (record["document_id"], record["version"])
            for record in self._records.values() if record["chunk_count"] > 0
        ))

    _COLUMNS = (
        "document_id", "filename", "media_type", "size_bytes", "content_hash", "version",
        "status", "uploaded_by", "topic", "subtopic", "chapters",
        "classification_confidence", "error", "chunk_count", "chunk_ids", "events",
        "stored_path", "created_at", "updated_at", "pending", "cleanup_ids",
    )

    def _fetch(self, where: str, params: tuple, one: bool):
        import psycopg

        query = (
            f"SELECT {', '.join(self._COLUMNS)} FROM knowledge_documents "
            f"WHERE {where} ORDER BY created_at DESC"
        )
        with psycopg.connect(self._conn_string, autocommit=True) as conn:
            rows = conn.execute(query, params).fetchall()

        def to_record(row) -> dict:
            record = dict(zip(self._COLUMNS, row))
            for key in _JSON_FIELDS:
                if isinstance(record[key], str):
                    record[key] = json.loads(record[key])
            for key in ("created_at", "updated_at"):
                if hasattr(record[key], "isoformat"):
                    record[key] = record[key].isoformat()
            return record

        if one:
            return to_record(rows[0]) if rows else None
        return [to_record(row) for row in rows]
