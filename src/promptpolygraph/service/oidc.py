"""OIDC / OAuth2 bearer-token verification for human SSO.

An IdP (Okta, Entra ID, Keycloak, Auth0, …) issues a signed JWT; the service
verifies it against the IdP's published JWKS and maps the token's identity (its
email / subject) to a workspace member's role. This is the human-login path;
per-workspace API keys remain the credential for CI / service accounts.

Verification checks the signature (against a cached JWKS), the issuer, the
audience, and expiry; MFA can be required via the ``amr`` claim. Needs the
``[oidc]`` extra (PyJWT); when OIDC is not configured the verifier is inert and
API-key auth is unchanged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


def oidc_available() -> bool:
    try:
        import jwt  # noqa: F401
        return True
    except Exception:
        return False


@dataclass
class OIDCClaims:
    subject: str
    email: Optional[str]
    raw: dict[str, Any]

    def identity(self, email_claim: str = "email") -> str:
        return self.raw.get(email_claim) or self.email or self.subject


class OIDCError(Exception):
    pass


class OIDCVerifier:
    """Verifies IdP bearer JWTs. JWKS is fetched from the issuer's well-known
    metadata (or an explicit URL) and cached for `jwks_ttl` seconds."""

    def __init__(self, *, issuer: str, audience: str | None, jwks_url: str | None = None,
                 email_claim: str = "email", require_mfa: bool = False,
                 jwks_ttl: int = 3600, leeway: int = 60):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self._jwks_url = jwks_url
        self.email_claim = email_claim
        self.require_mfa = require_mfa
        self.jwks_ttl = jwks_ttl
        self.leeway = leeway
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at = 0.0

    # ── JWKS ──────────────────────────────────────────────────────────────
    def jwks_url(self) -> str:
        if self._jwks_url:
            return self._jwks_url
        return f"{self.issuer}/.well-known/jwks.json"

    def _fetch_jwks(self) -> dict[str, Any]:
        import httpx

        disco = f"{self.issuer}/.well-known/openid-configuration"
        url = self._jwks_url
        try:
            if not url:
                meta = httpx.get(disco, timeout=5).json()
                url = meta.get("jwks_uri") or self.jwks_url()
            return httpx.get(url, timeout=5).json()
        except Exception as e:  # noqa: BLE001
            raise OIDCError(f"could not fetch JWKS: {e}") from e

    def _get_jwks(self, *, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        if self._jwks is None or (now - self._jwks_fetched_at) > self.jwks_ttl:
            self._jwks = self._fetch_jwks()
            self._jwks_fetched_at = now
        return self._jwks

    def set_jwks(self, jwks: dict[str, Any]) -> None:
        """Inject a JWKS (used in tests / for an air-gapped pinned key set)."""
        self._jwks = jwks
        self._jwks_fetched_at = time.time()

    # ── verify ────────────────────────────────────────────────────────────
    def verify(self, token: str) -> OIDCClaims:
        if not oidc_available():
            raise OIDCError("OIDC requires the [oidc] extra (pip install 'promptpolygraph[oidc]')")
        import jwt
        from jwt import PyJWKClient
        from jwt.algorithms import RSAAlgorithm, ECAlgorithm

        try:
            header = jwt.get_unverified_header(token)
        except Exception as e:  # noqa: BLE001
            raise OIDCError(f"malformed token: {e}") from e
        kid = header.get("kid")

        key = None
        jwks = self._get_jwks()
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid or kid is None:
                kty = jwk.get("kty")
                if kty == "RSA":
                    key = RSAAlgorithm.from_jwk(jwk)
                elif kty == "EC":
                    key = ECAlgorithm.from_jwk(jwk)
                break
        if key is None:
            raise OIDCError("no matching signing key in JWKS")

        opts = {"require": ["exp", "iss"]}
        try:
            claims = jwt.decode(
                token, key=key, algorithms=["RS256", "ES256"],
                audience=self.audience, issuer=self.issuer,
                leeway=self.leeway, options={**opts, "verify_aud": bool(self.audience)},
            )
        except Exception as e:  # noqa: BLE001
            raise OIDCError(f"token verification failed: {e}") from e

        if self.require_mfa and not _has_mfa(claims):
            raise OIDCError("multi-factor authentication required (amr/acr)")

        return OIDCClaims(subject=str(claims.get("sub", "")),
                          email=claims.get("email"), raw=claims)


def _has_mfa(claims: dict[str, Any]) -> bool:
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if any(str(a).lower() in ("mfa", "otp", "hwk", "swk", "phr", "phrh") for a in amr):
        return True
    acr = str(claims.get("acr", ""))
    return acr.endswith("mfa") or acr in ("urn:mace:incommon:iap:silver",) or "loa2" in acr.lower()


from functools import lru_cache


@lru_cache
def get_verifier() -> Optional[OIDCVerifier]:
    """Build the verifier from settings, or None when OIDC is not configured."""
    from .settings import get_settings

    s = get_settings()
    if not getattr(s, "oidc_issuer", ""):
        return None
    return OIDCVerifier(
        issuer=s.oidc_issuer, audience=s.oidc_audience or None,
        jwks_url=s.oidc_jwks_url or None, email_claim=s.oidc_email_claim,
        require_mfa=s.oidc_require_mfa,
    )
