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


class ThreadOwnershipRegistry:
    """Fixes the gap flagged in instructions/learnings/chat-ui-plan1.md
    section 6: before this existed, any authenticated caller could
    resume *any* thread_id, including one started by a different user.
    Records which user first used each thread_id and rejects (403) a
    later request for that thread_id from anyone else.

    In-memory only, matching the current InMemorySaver checkpointer's
    own non-durability (app/api/main.py) - both need to move to a
    persistent backend together (routing-lab-prod-plan.md section 2.2),
    not this registry alone."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def check_and_record(self, thread_id: str, user: str) -> None:
        owner = self._owners.setdefault(thread_id, user)
        if owner != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This conversation belongs to a different user.",
            )
