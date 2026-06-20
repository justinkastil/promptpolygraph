"""OIDC/SSO bearer-token verification + membership mapping.

Fully offline: an RSA keypair stands in for the IdP, a signed JWT for the token,
and an injected JWKS for the IdP's published keys (no network)."""

from __future__ import annotations

import json
import time

import pytest

from promptpolygraph.service import oidc

pytest.importorskip("jwt")  # the [oidc] extra
pytest.importorskip("cryptography")

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

_ISS = "https://idp.example.com"
_AUD = "promptpolygraph"
_KID = "test-key-1"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = _KID
    jwk["alg"] = "RS256"
    return priv_pem, {"keys": [jwk]}


def _token(priv_pem, **overrides):
    now = int(time.time())
    claims = {"iss": _ISS, "aud": _AUD, "sub": "u-1", "email": "alice@example.com",
              "iat": now, "exp": now + 3600}
    claims.update(overrides)
    return jwt.encode(claims, priv_pem, algorithm="RS256", headers={"kid": _KID})


def _verifier(jwks, **kw):
    v = oidc.OIDCVerifier(issuer=_ISS, audience=_AUD, **kw)
    v.set_jwks(jwks)
    return v


def test_oidc_available():
    assert oidc.oidc_available() is True


def test_verify_valid_token(keypair):
    priv, jwks = keypair
    v = _verifier(jwks)
    claims = v.verify(_token(priv))
    assert claims.subject == "u-1"
    assert claims.identity() == "alice@example.com"


def test_verify_rejects_expired(keypair):
    priv, jwks = keypair
    v = _verifier(jwks)
    with pytest.raises(oidc.OIDCError):
        v.verify(_token(priv, exp=int(time.time()) - 3600))  # well past the 60s leeway


def test_verify_rejects_wrong_audience(keypair):
    priv, jwks = keypair
    v = _verifier(jwks)
    with pytest.raises(oidc.OIDCError):
        v.verify(_token(priv, aud="someone-else"))


def test_verify_rejects_wrong_issuer(keypair):
    priv, jwks = keypair
    v = oidc.OIDCVerifier(issuer="https://evil.example.com", audience=_AUD)
    v.set_jwks(jwks)
    with pytest.raises(oidc.OIDCError):
        v.verify(_token(priv))


def test_verify_rejects_tampered_token(keypair):
    priv, jwks = keypair
    tok = _token(priv)
    tampered = tok[:-4] + ("aaaa" if tok[-4:] != "aaaa" else "bbbb")
    v = _verifier(jwks)
    with pytest.raises(oidc.OIDCError):
        v.verify(tampered)


def test_mfa_enforcement(keypair):
    priv, jwks = keypair
    v = _verifier(jwks, require_mfa=True)
    with pytest.raises(oidc.OIDCError):
        v.verify(_token(priv))  # no amr
    claims = v.verify(_token(priv, amr=["pwd", "mfa"]))  # has mfa factor
    assert claims.email == "alice@example.com"


def test_get_verifier_disabled_without_issuer(monkeypatch):
    oidc.get_verifier.cache_clear()
    from promptpolygraph.service import settings as S
    monkeypatch.setattr(S.get_settings(), "oidc_issuer", "", raising=False)
    assert oidc.get_verifier() is None
    oidc.get_verifier.cache_clear()


# ── membership mapping in auth._principal_from_oidc ──────────────────────────

def test_principal_from_oidc_maps_member_role(monkeypatch, keypair):
    from promptpolygraph.service import auth

    priv, jwks = keypair
    v = _verifier(jwks)
    monkeypatch.setattr("promptpolygraph.service.oidc.get_verifier", lambda: v)

    class _Tenancy:
        def member_workspaces(self, subject):
            assert subject == "alice@example.com"
            return [{"workspace_id": "ws_a", "role": "editor"}]

    monkeypatch.setattr(auth, "get_tenancy", lambda: _Tenancy())
    p = auth._principal_from_oidc(_token(priv), None)
    assert p.workspace_id == "ws_a" and p.role == "editor" and p.via == "oidc"


def test_principal_from_oidc_non_member_denied(monkeypatch, keypair):
    from fastapi import HTTPException

    from promptpolygraph.service import auth

    priv, jwks = keypair
    v = _verifier(jwks)
    monkeypatch.setattr("promptpolygraph.service.oidc.get_verifier", lambda: v)
    monkeypatch.setattr(auth, "get_tenancy", lambda: type("T", (), {
        "member_workspaces": lambda self, s: []})())
    with pytest.raises(HTTPException) as ei:
        auth._principal_from_oidc(_token(priv), None)
    assert ei.value.status_code == 403


def test_principal_from_oidc_workspace_hint_selects(monkeypatch, keypair):
    from promptpolygraph.service import auth

    priv, jwks = keypair
    v = _verifier(jwks)
    monkeypatch.setattr("promptpolygraph.service.oidc.get_verifier", lambda: v)
    monkeypatch.setattr(auth, "get_tenancy", lambda: type("T", (), {
        "member_workspaces": lambda self, s: [
            {"workspace_id": "ws_a", "role": "viewer"},
            {"workspace_id": "ws_b", "role": "admin"}]})())
    p = auth._principal_from_oidc(_token(priv), "ws_b")
    assert p.workspace_id == "ws_b" and p.role == "admin"


def test_oidc_disabled_returns_none(monkeypatch, keypair):
    from promptpolygraph.service import auth

    priv, _ = keypair
    monkeypatch.setattr("promptpolygraph.service.oidc.get_verifier", lambda: None)
    assert auth._principal_from_oidc(_token(priv), None) is None
