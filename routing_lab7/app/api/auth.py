"""JWT authentication for routing_lab7's FastAPI backend (app/api/main.py).

Verifies Keycloak-issued access tokens
(instructions/learnings/routing-lab-prod-plan.md section 2.1) against the
realm's own JWKS endpoint - no Keycloak admin/service-account
credentials needed on this side, just the public signing keys any
client can fetch. `get_current_user` is a FastAPI dependency applied to
every authenticated route; its one job is extracting a stable user
identifier (the `sub` claim) other code can trust.

`_get_signing_key` is a module-level, monkeypatchable indirection
specifically so tests can verify tokens signed with a locally generated
test key, without needing a live Keycloak instance or faking its JWKS
HTTP response shape - see tests/test_chat_api.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8081/realms/routing-lab6")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "routing-lab6-frontend")

_bearer_scheme = HTTPBearer(auto_error=True)
_jwks_client = jwt.PyJWKClient(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs")


def _default_get_signing_key(token: str):
    return _jwks_client.get_signing_key_from_jwt(token).key


# Test-only hook (see tests/test_chat_api.py): monkeypatched to a
# `lambda token: <test public key>` so auth can be verified against a
# locally generated RSA key instead of requiring a live Keycloak
# instance during routine test runs.
_get_signing_key: Callable[[str], object] = _default_get_signing_key


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> str:
    """Verifies the bearer token's signature and issuer, and that it was
    issued to this project's own frontend client (`azp`), then returns
    its `sub` claim - the stable identifier `ThreadOwnershipRegistry`
    below uses. Raises 401 for anything missing/invalid/expired/wrong."""
    token = credentials.credentials
    try:
        signing_key = _get_signing_key(token)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            # Keycloak's default access-token audience is "account", not
            # this client - `azp` (the client the token was actually
            # issued to) is the correct check for a public SPA client,
            # done explicitly below instead of relying on `aud`.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {exc}",
        ) from exc

    if payload.get("azp") != KEYCLOAK_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was not issued to the expected client.",
        )

    return payload["sub"]


# Conversation titles are the first user message, truncated - enough for
# a list view, without storing a second full copy of the message.
_TITLE_MAX_CHARS = 80


class ThreadOwnershipRegistry:
    """Fixes the gap flagged in instructions/learnings/chat-ui-plan1.md
    section 6: before this existed, any authenticated caller could
    resume *any* thread_id, including one started by a different user.
    Records which user first used each thread_id and rejects (403) a
    later request for that thread_id from anyone else.

    Also stores a per-thread title (the first user message, truncated,
    replaced by an LLM-generated one after the first turn unless the
    user renamed it - `title_is_custom`), a last-activity timestamp, and
    a soft-delete marker (`deleted_at` - chat-ui-plan3.md §1.1: deletes
    are undo-able for a grace period before being purged for real), so
    the conversation list the frontend needs is served from the same
    record that already had to exist for the ownership check -
    no separate "conversations" table to keep in sync.

    In-memory by default. Pass a Postgres connection string (the same
    `CHAT_DB_URL` app/api/main.py uses for `PostgresSaver`) to persist
    ownership records alongside conversation history - both moved to a
    persistent backend together (routing-lab-prod-plan.md section 2.2),
    as this class's own earlier docstring noted they needed to."""

    def __init__(self, conn_string: str | None = None) -> None:
        # thread_id -> {"user_sub", "title", "title_is_custom",
        #               "updated_at" (datetime), "deleted_at" (datetime|None)}
        self._records: dict[str, dict] = {}
        self._conn_string = conn_string
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string, autocommit=True) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS thread_owners ("
                    "thread_id TEXT PRIMARY KEY, user_sub TEXT NOT NULL, "
                    "title TEXT NOT NULL DEFAULT '', "
                    "title_is_custom BOOLEAN NOT NULL DEFAULT FALSE, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "deleted_at TIMESTAMPTZ)"
                )
                # Earlier phases created this table with fewer columns -
                # add the newer ones in place rather than requiring a
                # wipe of existing conversation ownership records.
                conn.execute(
                    "ALTER TABLE thread_owners "
                    "ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''"
                )
                conn.execute(
                    "ALTER TABLE thread_owners "
                    "ADD COLUMN IF NOT EXISTS title_is_custom BOOLEAN NOT NULL DEFAULT FALSE"
                )
                conn.execute(
                    "ALTER TABLE thread_owners "
                    "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                )
                conn.execute(
                    "ALTER TABLE thread_owners ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
                )

    def check_and_record(self, thread_id: str, user: str, title: str = "") -> None:
        """403s unless `user` owns (or is the first user of) `thread_id`.
        Records the title on first use only (it's the conversation's
        opening message) and bumps the last-activity timestamp on every
        successful call."""
        title = title.strip()[:_TITLE_MAX_CHARS]
        if self._conn_string:
            self._check_and_record_db(thread_id, user, title)
        else:
            self._check_and_record_memory(thread_id, user, title)

    def check_owner(self, thread_id: str, user: str) -> None:
        """Read-only ownership check for `GET` endpoints: 404 for a
        thread_id this registry has never seen (nothing to leak about
        whether it exists elsewhere), 403 for someone else's. A
        soft-deleted conversation is 404 for its owner - it behaves as
        gone unless/until restored."""
        owner, deleted = self._lookup(thread_id)
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown conversation."
            )
        if owner != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
            )
        if deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="This conversation was deleted."
            )

    def _lookup(self, thread_id: str) -> tuple[str | None, bool]:
        """(owner, is_soft_deleted) - owner None when never seen."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                row = conn.execute(
                    "SELECT user_sub, deleted_at FROM thread_owners WHERE thread_id = %s",
                    (thread_id,),
                ).fetchone()
            if row is None:
                return None, False
            return row[0], row[1] is not None
        record = self._records.get(thread_id)
        if record is None:
            return None, False
        return record["user_sub"], record["deleted_at"] is not None

    def list_threads(self, user: str) -> list[dict]:
        """This user's non-deleted conversations, most recently active
        first - each as {"thread_id", "title", "updated_at" (ISO-8601
        string)}."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                rows = conn.execute(
                    "SELECT thread_id, title, updated_at FROM thread_owners "
                    "WHERE user_sub = %s AND deleted_at IS NULL ORDER BY updated_at DESC",
                    (user,),
                ).fetchall()
            return [
                {"thread_id": row[0], "title": row[1], "updated_at": row[2].isoformat()}
                for row in rows
            ]

        own = [
            (thread_id, record)
            for thread_id, record in self._records.items()
            if record["user_sub"] == user and record["deleted_at"] is None
        ]
        own.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        return [
            {
                "thread_id": thread_id,
                "title": record["title"],
                "updated_at": record["updated_at"].isoformat(),
            }
            for thread_id, record in own
        ]

    def rename(self, thread_id: str, user: str, title: str) -> None:
        """Renames a conversation the caller owns (404/403 otherwise).
        Marks the title user-chosen, so the automatic title generation
        (set_generated_title) never overwrites it."""
        self.check_owner(thread_id, user)
        title = title.strip()[:_TITLE_MAX_CHARS]
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "UPDATE thread_owners SET title = %s, title_is_custom = TRUE "
                    "WHERE thread_id = %s",
                    (title, thread_id),
                )
        else:
            self._records[thread_id]["title"] = title
            self._records[thread_id]["title_is_custom"] = True

    def set_generated_title(self, thread_id: str, title: str) -> None:
        """Applies an LLM-generated title (chat-ui-plan3.md §1.2) -
        a no-op for a title the user has renamed themselves."""
        title = title.strip()[:_TITLE_MAX_CHARS]
        if not title:
            return
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "UPDATE thread_owners SET title = %s "
                    "WHERE thread_id = %s AND NOT title_is_custom",
                    (title, thread_id),
                )
        else:
            record = self._records.get(thread_id)
            if record is not None and not record["title_is_custom"]:
                record["title"] = title

    def delete(self, thread_id: str, user: str, permanent: bool = False) -> None:
        """Soft-deletes a conversation the caller owns (404/403
        otherwise): it disappears from the list and can't be resumed,
        but `restore` can undo it (chat-ui-plan3.md §1.1). With
        `permanent=True`, removes the ownership record outright - the
        checkpointer's conversation history is deleted separately by the
        API layer (see app/api/main.py's DELETE /threads/{thread_id})."""
        self.check_owner(thread_id, user)
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                if permanent:
                    conn.execute("DELETE FROM thread_owners WHERE thread_id = %s", (thread_id,))
                else:
                    conn.execute(
                        "UPDATE thread_owners SET deleted_at = now() WHERE thread_id = %s",
                        (thread_id,),
                    )
        elif permanent:
            self._records.pop(thread_id, None)
        else:
            self._records[thread_id]["deleted_at"] = datetime.now(timezone.utc)

    def restore(self, thread_id: str, user: str) -> None:
        """Undoes a soft delete, provided the caller owns the thread.
        404 for an unknown thread, 403 for someone else's; restoring a
        thread that isn't deleted is a harmless no-op."""
        owner, _deleted = self._lookup(thread_id)
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown conversation."
            )
        if owner != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
            )
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "UPDATE thread_owners SET deleted_at = NULL WHERE thread_id = %s",
                    (thread_id,),
                )
        else:
            self._records[thread_id]["deleted_at"] = None

    def purge_soft_deleted(self, older_than_days: int = 30) -> list[str]:
        """Hard-deletes records soft-deleted more than `older_than_days`
        ago and returns their thread_ids, so the caller can delete the
        corresponding checkpointed histories too. Called at API startup
        (app/api/main.py) - a scheduled job would also work, but a
        startup sweep needs no extra infrastructure."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                rows = conn.execute(
                    "DELETE FROM thread_owners "
                    "WHERE deleted_at IS NOT NULL AND deleted_at < now() - make_interval(days => %s) "
                    "RETURNING thread_id",
                    (older_than_days,),
                ).fetchall()
            return [row[0] for row in rows]

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        purged = [
            thread_id
            for thread_id, record in self._records.items()
            if record["deleted_at"] is not None and record["deleted_at"] < cutoff
        ]
        for thread_id in purged:
            del self._records[thread_id]
        return purged

    def _check_and_record_memory(self, thread_id: str, user: str, title: str) -> None:
        record = self._records.get(thread_id)
        if record is None:
            self._records[thread_id] = {
                "user_sub": user,
                "title": title,
                "title_is_custom": False,
                "updated_at": datetime.now(timezone.utc),
                "deleted_at": None,
            }
            return
        if record["user_sub"] != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
            )
        if record["deleted_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="This conversation was deleted."
            )
        record["updated_at"] = datetime.now(timezone.utc)

    def _check_and_record_db(self, thread_id: str, user: str, title: str) -> None:
        import psycopg

        # ON CONFLICT DO NOTHING makes "insert the owner if this
        # thread_id is new" atomic and race-safe across concurrent
        # requests - a single round trip, no separate
        # check-then-insert that could race between two replicas (a
        # real possibility once app/api/main.py is horizontally scaled,
        # per routing-lab-prod-plan.md section 2.6).
        with psycopg.connect(self._conn_string, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO thread_owners (thread_id, user_sub, title) VALUES (%s, %s, %s) "
                "ON CONFLICT (thread_id) DO NOTHING",
                (thread_id, user, title),
            )
            row = conn.execute(
                "SELECT user_sub, deleted_at FROM thread_owners WHERE thread_id = %s",
                (thread_id,),
            ).fetchone()
            if row is not None and row[0] != user:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This conversation belongs to a different user.",
                )
            if row is not None and row[1] is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="This conversation was deleted.",
                )
            conn.execute(
                "UPDATE thread_owners SET updated_at = now() WHERE thread_id = %s",
                (thread_id,),
            )
