"""Cryptographic signing for run artifacts.

Two schemes, chosen by which credential the operator supplies:

- HMAC-SHA256 (default, stdlib only): a shared secret authenticates the manifest
  within one trust domain.
- Ed25519 (optional, needs the ``[crypto]`` extra): a keypair allows public-key
  verification, so a third party can verify a report with the public key alone.

``ed25519_available()`` reports whether the optional ``cryptography`` dependency
is installed; the HMAC path has no extra dependency.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

ALG_HMAC = "hmac-sha256"
ALG_ED25519 = "ed25519"


def ed25519_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


# ── HMAC ──────────────────────────────────────────────────────────────────────

def hmac_sign(data: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()


def hmac_verify(data: bytes, signature: str, key: str) -> bool:
    return hmac.compare_digest(signature, hmac_sign(data, key))


# ── Ed25519 ─────────────────────────────────────────────────────────────────

def generate_keypair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for a fresh Ed25519 keypair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def ed25519_sign(data: bytes, private_pem: str | bytes) -> str:
    from cryptography.hazmat.primitives import serialization

    if isinstance(private_pem, str):
        private_pem = private_pem.encode("utf-8")
    key = serialization.load_pem_private_key(private_pem, password=None)
    return key.sign(data).hex()


def ed25519_verify(data: bytes, signature_hex: str, public_pem: str | bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization

    if isinstance(public_pem, str):
        public_pem = public_pem.encode("utf-8")
    try:
        key = serialization.load_pem_public_key(public_pem)
        key.verify(bytes.fromhex(signature_hex), data)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


# ── unified helpers (used by the bundle layer) ───────────────────────────────

def sign(data: bytes, *, hmac_key: str | None = None,
         ed25519_private_pem: str | bytes | None = None) -> dict | None:
    """Sign `data` with whichever credential is supplied. Returns a signature
    record {alg, sig} (or None when nothing to sign)."""
    if ed25519_private_pem:
        return {"alg": ALG_ED25519, "sig": ed25519_sign(data, ed25519_private_pem)}
    if hmac_key:
        return {"alg": ALG_HMAC, "sig": hmac_sign(data, hmac_key)}
    return None


def verify(data: bytes, record: dict, *, hmac_key: str | None = None,
           ed25519_public_pem: str | bytes | None = None) -> bool | None:
    """Verify a signature record. Returns True/False, or None when the verifier
    has no key for the record's algorithm."""
    alg = (record or {}).get("alg")
    sig = (record or {}).get("sig", "")
    if alg == ALG_ED25519:
        if not ed25519_public_pem:
            return None
        return ed25519_verify(data, sig, ed25519_public_pem)
    if alg == ALG_HMAC:
        if not hmac_key:
            return None
        return hmac_verify(data, sig, hmac_key)
    return None


def load_key_file(path: str | Path) -> str:
    return Path(path).read_text()
