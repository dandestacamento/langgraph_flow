"""JWT authentication for routing_lab3's FastAPI backend (app/api/main.py).

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
from datetime import datetime, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8081/realms/routing-lab3")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "routing-lab3-frontend")

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

    Also stores a per-thread title (the first user message, truncated)
    and a last-activity timestamp, so the conversation list the frontend
    needs (chat-ui-plan1.md Phase E's `GET /threads`) is served from the
    same record that already had to exist for the ownership check -
    no separate "conversations" table to keep in sync.

    In-memory by default. Pass a Postgres connection string (the same
    `CHAT_DB_URL` app/api/main.py uses for `PostgresSaver`) to persist
    ownership records alongside conversation history - both moved to a
    persistent backend together (routing-lab-prod-plan.md section 2.2),
    as this class's own earlier docstring noted they needed to."""

    def __init__(self, conn_string: str | None = None) -> None:
        # thread_id -> {"user_sub", "title", "updated_at" (datetime)}
        self._records: dict[str, dict] = {}
        self._conn_string = conn_string
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string, autocommit=True) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS thread_owners ("
                    "thread_id TEXT PRIMARY KEY, user_sub TEXT NOT NULL, "
                    "title TEXT NOT NULL DEFAULT '', "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                # Pre-Phase-E databases created this table with only the
                # two ownership columns - add the list-view columns in
                # place rather than requiring a wipe of existing
                # conversation ownership records.
                conn.execute(
                    "ALTER TABLE thread_owners "
                    "ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''"
                )
                conn.execute(
                    "ALTER TABLE thread_owners "
                    "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
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
        whether it exists elsewhere), 403 for someone else's."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                row = conn.execute(
                    "SELECT user_sub FROM thread_owners WHERE thread_id = %s", (thread_id,)
                ).fetchone()
            owner = row[0] if row is not None else None
        else:
            record = self._records.get(thread_id)
            owner = record["user_sub"] if record is not None else None

        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown conversation."
            )
        if owner != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
            )

    def list_threads(self, user: str) -> list[dict]:
        """This user's conversations, most recently active first - each
        as {"thread_id", "title", "updated_at" (ISO-8601 string)}."""
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                rows = conn.execute(
                    "SELECT thread_id, title, updated_at FROM thread_owners "
                    "WHERE user_sub = %s ORDER BY updated_at DESC",
                    (user,),
                ).fetchall()
            return [
                {"thread_id": row[0], "title": row[1], "updated_at": row[2].isoformat()}
                for row in rows
            ]

        own = [
            (thread_id, record)
            for thread_id, record in self._records.items()
            if record["user_sub"] == user
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
        """Renames a conversation the caller owns (404/403 otherwise)."""
        self.check_owner(thread_id, user)
        title = title.strip()[:_TITLE_MAX_CHARS]
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute(
                    "UPDATE thread_owners SET title = %s WHERE thread_id = %s",
                    (title, thread_id),
                )
        else:
            self._records[thread_id]["title"] = title

    def delete(self, thread_id: str, user: str) -> None:
        """Removes a conversation's ownership record, provided the caller
        owns it (404/403 otherwise). The checkpointer's conversation
        history is deleted separately by the API layer - see
        app/api/main.py's DELETE /threads/{thread_id}."""
        self.check_owner(thread_id, user)
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string, autocommit=True) as conn:
                conn.execute("DELETE FROM thread_owners WHERE thread_id = %s", (thread_id,))
        else:
            self._records.pop(thread_id, None)

    def _check_and_record_memory(self, thread_id: str, user: str, title: str) -> None:
        record = self._records.get(thread_id)
        if record is None:
            self._records[thread_id] = {
                "user_sub": user,
                "title": title,
                "updated_at": datetime.now(timezone.utc),
            }
            return
        if record["user_sub"] != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
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
                "SELECT user_sub FROM thread_owners WHERE thread_id = %s", (thread_id,)
            ).fetchone()
            if row is not None and row[0] != user:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This conversation belongs to a different user.",
                )
            conn.execute(
                "UPDATE thread_owners SET updated_at = now() WHERE thread_id = %s",
                (thread_id,),
            )
