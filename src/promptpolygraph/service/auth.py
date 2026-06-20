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


def _looks_like_jwt(token: str | None) -> bool:
    return bool(token) and token.count(".") == 2 and not token.startswith("ppg_")


def _principal_from_oidc(token: str, workspace_hint: str | None) -> Principal | None:
    """Verify an IdP bearer JWT and map its identity to a workspace member.
    Returns None when OIDC is not configured (so other paths handle the token)."""
    from .oidc import OIDCError, get_verifier

    verifier = get_verifier()
    if verifier is None:
        return None
    try:
        claims = verifier.verify(token)
    except OIDCError as e:
        raise HTTPException(status_code=401, detail=f"OIDC: {e}") from e

    subject = claims.identity(get_settings().oidc_email_claim)
    memberships = get_tenancy().member_workspaces(subject)
    if not memberships:
        raise HTTPException(status_code=403,
                            detail=f"'{subject}' is authenticated but not a member of any workspace")
    chosen = next((m for m in memberships if m["workspace_id"] == workspace_hint), memberships[0])
    return Principal(chosen["workspace_id"], chosen["role"], subject=subject, via="oidc")


async def get_principal(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_workspace: str | None = Header(default=None),
) -> Principal:
    settings = get_settings()
    key = _extract_key(x_api_key, authorization)
    tenancy = get_tenancy()

    # 1. a real per-workspace API key
    if key:
        principal = tenancy.resolve_api_key(key)
        if principal is not None:
            return principal

    # 2. an OIDC/SSO bearer JWT (only when OIDC is configured)
    if _looks_like_jwt(key):
        principal = _principal_from_oidc(key, x_workspace)
        if principal is not None:
            return principal

    # 3. legacy flat keys -> admin of the default workspace
    if settings.auth_enabled:
        if key and key in settings.api_key_set:
            return Principal(DEFAULT_WORKSPACE, "admin", subject="legacy", via="legacy")
        raise HTTPException(status_code=401, detail="invalid or missing API key")

    # 4. no auth configured at all -> dev mode
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
