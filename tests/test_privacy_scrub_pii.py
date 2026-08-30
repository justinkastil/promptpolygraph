"""Tests for ``promptpolygraph.service.privacy.scrub_pii`` (GitHub #50).

The first test function below is a verbatim transcription of the frozen
founder gate ``scripts/accept_gh50.py``: its import line, the one literal it
passes to ``scrub_pii``, and the outcome it asserts for that literal. That
transcription -- not the implementation -- is the authoritative spec; every
later test is additive and must not contradict it.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from promptpolygraph.service.privacy import scrub_pii


def test_frozen_accept_gh50_contract() -> None:
    """Verbatim transcription of scripts/accept_gh50.py's scrub_pii checks."""
    from promptpolygraph.service.privacy import scrub_pii

    raw = "Contact Jane Doe at jane.doe@example.com, SSN 123-45-6789."
    out = scrub_pii(raw)
    assert isinstance(out, str), f"scrub_pii must return str, got {type(out)}"
    assert "jane.doe@example.com" not in out, "email survived scrub_pii"
    assert "123-45-6789" not in out, "SSN survived scrub_pii"


# --- Literals used by the additive tests below -----------------------------
#
# Every one of these is fed through the idempotency sweep at the bottom of the
# file, together with every other string literal in this module.

FROZEN_RAW = "Contact Jane Doe at jane.doe@example.com, SSN 123-45-6789."

MULTI_EMAIL = "ping alice@example.com and bob.smith+tag@mail.example.co.uk now"
MULTI_SSN = "SSNs on file: 123-45-6789, 987-65-4321 and 555 44 3333."
MULTI_MIXED = "carol@example.org 111-22-3333 dave@example.net 444-55-6666"

LEADING_EMAIL = "erin@example.com wrote the summary"
TRAILING_EMAIL = "the summary was written by erin@example.com"
LEADING_SSN = "123-45-6789 is the number on file"
TRAILING_SSN = "the number on file is 123-45-6789"
PUNCTUATED = "(frank@example.com), <321-54-9876>; [grace@example.com]."
EMAIL_ONLY = "heidi@example.com"
SSN_ONLY = "123-45-6789"

# Near misses. Each is a shape scripts/accept_gh50.py does NOT require to be
# redacted, so asserting it survives cannot contradict the frozen gate.
NEGATIVES = (
    "1234-56-7890",                 # digit run too long on the left
    "12-345-6789",                  # wrong grouping
    "123-45-67890",                 # digit run too long on the right
    "123-45-678",                   # digit run too short on the right
    "123456789",                    # no separator; reads as an order id
    "not.an.email at example.com",  # no @
    "@example.com",                 # no local part
    "someone@",                     # no domain
    "build 2024-01-02 shipped",     # date, not an SSN
)

EMPTY = ""


def test_multiple_emails_in_one_body() -> None:
    out = scrub_pii(MULTI_EMAIL)
    assert "alice@example.com" not in out
    assert "bob.smith+tag@mail.example.co.uk" not in out
    assert "@" not in out
    assert out.count("[REDACTED-EMAIL]") == 2
    assert out.startswith("ping ") and out.endswith(" now")


def test_multiple_ssns_in_one_body() -> None:
    out = scrub_pii(MULTI_SSN)
    for ssn in ("123-45-6789", "987-65-4321", "555 44 3333"):
        assert ssn not in out
    assert out.count("[REDACTED-SSN]") == 3


def test_emails_and_ssns_mixed_in_one_body() -> None:
    out = scrub_pii(MULTI_MIXED)
    for pii in ("carol@example.org", "111-22-3333", "dave@example.net", "444-55-6666"):
        assert pii not in out
    assert out.count("[REDACTED-EMAIL]") == 2
    assert out.count("[REDACTED-SSN]") == 2


def test_pii_at_string_boundaries() -> None:
    assert scrub_pii(LEADING_EMAIL).startswith("[REDACTED-EMAIL]")
    assert scrub_pii(TRAILING_EMAIL).endswith("[REDACTED-EMAIL]")
    assert scrub_pii(LEADING_SSN).startswith("[REDACTED-SSN]")
    assert scrub_pii(TRAILING_SSN).endswith("[REDACTED-SSN]")
    assert scrub_pii(EMAIL_ONLY) == "[REDACTED-EMAIL]"
    assert scrub_pii(SSN_ONLY) == "[REDACTED-SSN]"


def test_pii_adjacent_to_punctuation() -> None:
    out = scrub_pii(PUNCTUATED)
    for pii in ("frank@example.com", "321-54-9876", "grace@example.com"):
        assert pii not in out
    # Surrounding punctuation is preserved; only the PII span is replaced.
    assert out == "([REDACTED-EMAIL]), <[REDACTED-SSN]>; [[REDACTED-EMAIL]]."


@pytest.mark.parametrize("text", NEGATIVES)
def test_near_miss_shapes_are_left_intact(text: str) -> None:
    assert scrub_pii(text) == text


def test_empty_string() -> None:
    assert scrub_pii(EMPTY) == ""


def test_placeholders_contain_no_at_sign_and_no_digits() -> None:
    for placeholder in ("[REDACTED-EMAIL]", "[REDACTED-SSN]"):
        assert "@" not in placeholder
        assert not any(character.isdigit() for character in placeholder)


def test_non_str_input_is_coerced_not_raised() -> None:
    """Contract stated in the module docstring of privacy.py: total, never raises.

    `scrub_pii` sits on the persistence ingest path (`Store.save_response`), so
    raising on an unexpected body type would turn a privacy control into a
    failed write. It coerces instead, and the coerced text is still scrubbed.
    """
    for bad in (None, 123, 4.5, b"jane.doe@example.com", ["a"], {"a": 1}, object()):
        out = scrub_pii(bad)  # type: ignore[arg-type]
        assert isinstance(out, str), f"scrub_pii must return str for {bad!r}"

    # `None` means "no body" and must not become the literal string "None".
    assert scrub_pii(None) == ""  # type: ignore[arg-type]
    # bytes are decoded, not repr()'d, and the decoded PII is still redacted.
    assert scrub_pii(b"jane.doe@example.com") == "[REDACTED-EMAIL]"  # type: ignore[arg-type]
    assert scrub_pii(bytearray(b"SSN 123-45-6789")) == "SSN [REDACTED-SSN]"  # type: ignore[arg-type]
    # Anything else falls back to str(), and is scrubbed rather than passed through.
    assert "123-45-6789" not in scrub_pii(["123-45-6789"])  # type: ignore[arg-type]


def _string_literals_in_this_module() -> list[str]:
    """Every ``str`` literal appearing anywhere in this test module's source."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_idempotent_over_every_literal_in_this_module() -> None:
    literals = _string_literals_in_this_module()
    # Guard against the sweep silently collecting nothing.
    assert FROZEN_RAW in literals
    assert EMPTY in literals
    for literal in literals:
        once = scrub_pii(literal)
        assert scrub_pii(scrub_pii(literal)) == once
        assert isinstance(once, str)
