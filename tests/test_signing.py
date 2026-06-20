"""HMAC + Ed25519 signing primitives and the unified sign/verify."""

from __future__ import annotations

import pytest

from promptpolygraph import signing


def test_hmac_sign_verify():
    sig = signing.hmac_sign(b"data", "secret")
    assert signing.hmac_verify(b"data", sig, "secret")
    assert not signing.hmac_verify(b"data", sig, "wrong")
    assert not signing.hmac_verify(b"tampered", sig, "secret")


def test_unified_hmac_record():
    rec = signing.sign(b"x", hmac_key="k")
    assert rec["alg"] == signing.ALG_HMAC
    assert signing.verify(b"x", rec, hmac_key="k") is True
    assert signing.verify(b"x", rec, hmac_key="other") is False
    assert signing.verify(b"x", rec) is None  # no key to check


def test_sign_nothing_returns_none():
    assert signing.sign(b"x") is None


@pytest.mark.skipif(not signing.ed25519_available(), reason="cryptography not installed")
def test_ed25519_roundtrip_and_tamper():
    priv, pub = signing.generate_keypair()
    assert "PRIVATE KEY" in priv and "PUBLIC KEY" in pub
    sig = signing.ed25519_sign(b"payload", priv)
    assert signing.ed25519_verify(b"payload", sig, pub) is True
    assert signing.ed25519_verify(b"payload2", sig, pub) is False
    # a different key does not verify
    _, other_pub = signing.generate_keypair()
    assert signing.ed25519_verify(b"payload", sig, other_pub) is False


@pytest.mark.skipif(not signing.ed25519_available(), reason="cryptography not installed")
def test_unified_ed25519_prefers_keypair():
    priv, pub = signing.generate_keypair()
    rec = signing.sign(b"x", hmac_key="k", ed25519_private_pem=priv)
    assert rec["alg"] == signing.ALG_ED25519  # keypair wins over hmac
    assert signing.verify(b"x", rec, ed25519_public_pem=pub) is True
    assert signing.verify(b"x", rec) is None  # need the public key
