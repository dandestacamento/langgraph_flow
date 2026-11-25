"""Routes every ChatOpenAI/OpenAIEmbeddings call in this project through
LiteLLM (instructions/learnings/routing-lab-prod-plan.md section 2.3) -
a self-hosted gateway giving each authenticated chat user their own
virtual API key with an independent budget, instead of every call
sharing one raw `OPENAI_API_KEY` with no per-user cost control at all.

`llm_kwargs()` is a no-op (returns `{}`) unless `LITELLM_BASE_URL` is
set, so nothing changes for `routing_lab/`, `routing_lab2/`, or anyone
running `routing_lab7/` without LiteLLM - every one of the 16 call
sites below is unconditionally safe to spread `**llm_kwargs()` into.

Per-user routing uses a `contextvars.ContextVar`, not a process-global
env var: `app/api/main.py` serves many users from one process, often
concurrently, and `os.environ` is shared across every in-flight request
in that process - mutating it per-request would race between users.
`ContextVar` is correctly isolated per request even across FastAPI's
threadpool-executed sync endpoints (Starlette/anyio propagate context
vars into worker threads)."""

from __future__ import annotations

import contextvars
import os

import httpx

_current_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "litellm_user_api_key", default=None
)


def set_current_user_api_key(api_key: str | None) -> None:
    """Scopes every ChatOpenAI/OpenAIEmbeddings call made for the rest of
    the current request (or until called again) to this virtual key -
    call once per request, immediately after authenticating the user
    (see app/api/main.py)."""
    _current_api_key.set(api_key)


def llm_kwargs() -> dict:
    """The `base_url`/`api_key` kwargs every ChatOpenAI/OpenAIEmbeddings
    call site should spread into its constructor. Returns `{}` (meaning:
    talk to OpenAI directly, using whatever `OPENAI_API_KEY` the
    environment already provides) unless `LITELLM_BASE_URL` is set."""
    base_url = os.environ.get("LITELLM_BASE_URL")
    if not base_url:
        return {}
    api_key = _current_api_key.get() or os.environ.get("LITELLM_MASTER_KEY")
    return {"base_url": base_url, "api_key": api_key}


class UserKeyProvisioner:
    """Mints one LiteLLM virtual key per authenticated user (via
    `/key/generate`, using the master key), the first time that user's
    Keycloak `sub` is seen, with a small demo budget - see
    instructions/learnings/routing-lab-prod-plan.md section 2.3 and
    infra/litellm/README.md for why this is a demo-sized budget, not a
    real product-informed one.

    Caches the sub -> virtual-key mapping the same way
    `app.api.auth.ThreadOwnershipRegistry` caches thread ownership:
    persisted in Postgres when `conn_string` is given (so the same user
    keeps the same key, and its accumulated spend, across a restart -
    rather than silently minting a fresh key and losing track of prior
    spend every time the process restarts), in-memory otherwise."""

    def __init__(
        self,
        base_url: str,
        master_key: str,
        conn_string: str | None = None,
        max_budget: float = 0.05,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._master_key = master_key
        self._conn_string = conn_string
        self._max_budget = max_budget
        self._keys: dict[str, str] = {}
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string, autocommit=True) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS user_llm_keys ("
                    "user_sub TEXT PRIMARY KEY, litellm_key TEXT NOT NULL)"
                )

    def get_or_create_key(self, user_sub: str) -> str:
        existing = self._lookup(user_sub)
        if existing:
            return existing

        response = httpx.post(
            f"{self._base_url}/key/generate",
            headers={"Authorization": f"Bearer {self._master_key}"},
            json={
                "max_budget": self._max_budget,
                "metadata": {"user_sub": user_sub},
            },
            timeout=10.0,
        )
        response.raise_for_status()
        key = response.json()["key"]
        self._store(user_sub, key)
        return key

    def _lookup(self, user_sub: str) -> str | None:
        if not self._conn_string:
            return self._keys.get(user_sub)

        import psycopg

        with psycopg.connect(self._conn_string, autocommit=True) as conn:
            row = conn.execute(
                "SELECT litellm_key FROM user_llm_keys WHERE user_sub = %s", (user_sub,)
            ).fetchone()
        return row[0] if row else None

    def _store(self, user_sub: str, key: str) -> None:
        if not self._conn_string:
            self._keys[user_sub] = key
            return

        import psycopg

        with psycopg.connect(self._conn_string, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO user_llm_keys (user_sub, litellm_key) VALUES (%s, %s) "
                "ON CONFLICT (user_sub) DO NOTHING",
                (user_sub, key),
            )
