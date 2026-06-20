"""Authentication + RBAC for the service.

A request is resolved to a `Principal` (workspace + role + subject):

1. a per-workspace API key (hashed, minted via the admin API) → its bound role;
2. else a legacy flat `POLYGRAPH_API_KEYS` value → admin of the `default`
   workspace (backward compatible with pre-tenancy deployments);
3. else, when no keys are configured at all, dev mode → admin of `default`.

`require_role(role)` is a dependency factory enforcing admin > editor > viewer.
`get_principal` is the dependency routes use to learn who is calling.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from .settings import get_settings
from .tenancy import DEFAULT_WORKSPACE, Principal, get_tenancy


def _extract_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


async def get_principal(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Principal:
    settings = get_settings()
    key = _extract_key(x_api_key, authorization)
    tenancy = get_tenancy()

    # 1. a real per-workspace API key
    if key:
        principal = tenancy.resolve_api_key(key)
        if principal is not None:
            return principal

    # 2. legacy flat keys -> admin of the default workspace
    if settings.auth_enabled:
        if key and key in settings.api_key_set:
            return Principal(DEFAULT_WORKSPACE, "admin", subject="legacy", via="legacy")
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    # 3. no auth configured at all -> dev mode
    return Principal(DEFAULT_WORKSPACE, "admin", subject="dev", via="dev")


def require_role(role: str):
    """Dependency factory: 403 unless the principal has at least `role`."""
    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(role):
            raise HTTPException(status_code=403,
                                detail=f"requires '{role}' role (you are '{principal.role}')")
        return principal
    return _dep


# Back-compat: routes that only need authentication (any role) depend on this.
# It resolves + authorizes a principal at the lowest (viewer) level.
async def require_api_key(principal: Principal = Depends(get_principal)) -> str | None:
    return principal.subject
