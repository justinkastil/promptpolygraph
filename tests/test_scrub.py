"""Secret-scrub tests — the egress hygiene guard for code-grounded ladder excerpts."""

from __future__ import annotations

from promptpolygraph.redteam.scrub import scrub_secrets


def test_redacts_assigned_secrets():
    src = 'API_KEY = "sk-abcdef0123456789ABCDEF"\npassword: hunter2longpass\n'
    out, n = scrub_secrets(src)
    assert "sk-abcdef0123456789ABCDEF" not in out
    assert "hunter2longpass" not in out
    assert "REDACTED" in out and n >= 2


def test_redacts_private_key_block():
    src = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    out, n = scrub_secrets(src)
    assert "MIIEowIBAAKCAQEA" not in out and n == 1


def test_redacts_tokens_and_conn_strings():
    src = ("token=ghp_0123456789abcdefghijklmnopqrstuvwxyz\n"
           "url = postgres://user:s3cretpw@db.host:5432/app\n"
           "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payloadpart.sigpart\n")
    out, n = scrub_secrets(src)
    assert "ghp_0123456789abcdefghijklmnopqrstuvwxyz" not in out
    assert "s3cretpw" not in out
    assert "user:" in out  # the username/host is preserved, only the password redacted
    assert n >= 3


def test_keeps_normal_code_intact():
    src = "def add(a, b):\n    return a + b  # no secrets here\n"
    out, n = scrub_secrets(src)
    assert out == src and n == 0


def test_empty():
    assert scrub_secrets("") == ("", 0)
