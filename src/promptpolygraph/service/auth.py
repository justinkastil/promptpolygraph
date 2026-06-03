"""API-key authentication dependency.

Keys are configured via POLYGRAPH_API_KEYS (comma-separated). Clients send the
key in `X-API-Key` or as a bearer token. When no keys are configured auth is
disabled — convenient for local dev, but set keys before exposing the service.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from .settings import get_settings


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str | None:
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    key = x_api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:]
    if not key or key not in settings.api_key_set:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return key
