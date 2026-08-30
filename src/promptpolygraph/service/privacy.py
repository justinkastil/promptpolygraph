"""PII redaction for stored response bodies and exports (GitHub #50).

Standard library only: this module is imported by the frozen founder gate
``scripts/accept_gh50.py`` and by ``promptpolygraph.runner.store`` (core, which
runs without the optional ``[service]`` extra installed), so it must never drag
in optional service dependencies. ``promptpolygraph.service.__init__`` resolves
its own names lazily precisely so importing *this* submodule stays stdlib-only.

What is redacted
----------------
* Email addresses -> ``[REDACTED-EMAIL]``
* US SSN-shaped strings, ``NNN-NN-NNNN`` with a ``-`` or space separator
  -> ``[REDACTED-SSN]``

Neither placeholder contains an ``@`` or a run of digits, so ``scrub_pii`` is
idempotent: scrubbing already-scrubbed text is a no-op. Emails are matched
before SSNs so that an SSN-shaped local part (``123-45-6789@example.com``) is
consumed by the email rule as a whole address rather than being hollowed out
into a still-recognisable domain.

Deliberate non-goals (documented limits, not oversights)
--------------------------------------------------------
* A separator is required for the SSN rule. A bare nine-digit run is far more
  often an order/invoice/case id than an SSN, and redacting it would corrupt
  ordinary stored bodies.
* Near-miss shapes are left intact: over-long digit runs (``1234-56-7890``),
  wrong groupings (``12-345-6789``), and ``@``-less or domain-less fragments.

Frozen-script collisions: none. ``scripts/accept_gh50.py`` requires exactly
``jane.doe@example.com`` and ``123-45-6789`` to be redacted; no negative
asserted by ``tests/test_privacy_scrub_pii.py`` overlaps either shape.

Non-``str`` input contract
--------------------------
``scrub_pii`` is TOTAL: it returns a ``str`` for every input and never raises.
It sits on the persistence ingest path, where raising would turn a privacy
control into an availability incident -- a body of an unexpected type would
abort the write rather than being stored redacted. Coercion is therefore
explicit rather than a bare ``str()``:

* ``None`` -> ``""``. ``None`` means "no body"; stringifying it to the literal
  ``"None"`` would fabricate a body the target never returned.
* ``bytes`` / ``bytearray`` / ``memoryview`` -> decoded as UTF-8 with
  ``errors="replace"``, then scrubbed. ``str(b"a@b.com")`` would instead yield
  ``"b'a@b.com'"``, which is not the body.
* anything else -> ``str(value)``, then scrubbed, so a mis-typed body is still
  redacted rather than passed through unexamined.

Callers that must distinguish "absent body" from "empty body" have to do so
*before* calling ``scrub_pii``; this function only guarantees that a redacted
``str`` comes out.

Scope
-----
``scrub_response`` redacts the response *body* only -- ``Response.text`` and
the ``Response.tokens_streamed`` chunks that reconstruct it. It deliberately
leaves ``Response.error`` and ``Response.raw`` alone, and nothing here touches
the ``cache`` table: the cache is a keyed replay of what the target returned,
and every cache hit is re-scrubbed on its way through ``save_response`` anyway.
"""
from __future__ import annotations

import re
from typing import Any, TypeVar

__all__ = [
    "EMAIL_PLACEHOLDER",
    "SSN_PLACEHOLDER",
    "scrub_pii",
    "scrub_response",
]

EMAIL_PLACEHOLDER = "[REDACTED-EMAIL]"
SSN_PLACEHOLDER = "[REDACTED-SSN]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SSN_RE = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")


def _coerce(value: Any) -> str:
    """Best-effort coercion to ``str``. See the module docstring for the rules."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def scrub_pii(text: str) -> str:
    """Return ``text`` with email addresses and US SSN shapes redacted.

    Total: returns a ``str`` for any input and never raises. Non-``str`` input
    is coerced first (see the module docstring for the exact rules).
    """
    return _SSN_RE.sub(SSN_PLACEHOLDER, _EMAIL_RE.sub(EMAIL_PLACEHOLDER, _coerce(text)))


_R = TypeVar("_R")


def scrub_response(resp: _R) -> _R:
    """Return ``resp`` with its body redacted, or ``resp`` itself if it is clean.

    Used at the ``responses``-table write path of both stores and by the
    ``redact=True`` export path. Returns the *same* object when nothing needs
    changing, so the overwhelmingly common no-PII case allocates nothing and
    serialises byte-for-byte as it did before #50.

    Duck-typed on ``text`` / ``tokens_streamed`` rather than importing
    ``models.Response``, to keep this module free of import cycles.
    """
    text = getattr(resp, "text", None)
    chunks = getattr(resp, "tokens_streamed", None)

    new_text = scrub_pii(text) if isinstance(text, str) else None
    new_chunks = (
        [scrub_pii(c) if isinstance(c, str) else c for c in chunks]
        if isinstance(chunks, list)
        else None
    )

    text_changed = new_text is not None and new_text != text
    chunks_changed = new_chunks is not None and new_chunks != chunks
    if not text_changed and not chunks_changed:
        return resp

    update: dict[str, Any] = {}
    if text_changed:
        update["text"] = new_text
    if chunks_changed:
        update["tokens_streamed"] = new_chunks

    # pydantic BaseModel: copy rather than mutate in place, so a caller still
    # holding the original is not surprised by a write-path side effect.
    copier = getattr(resp, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    for key, value in update.items():
        setattr(resp, key, value)
    return resp
