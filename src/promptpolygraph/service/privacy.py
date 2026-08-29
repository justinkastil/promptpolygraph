"""PII redaction for stored response bodies and exports (GitHub #50).

Standard library only: this module is imported by the frozen founder gate
``scripts/accept_gh50.py`` and must never drag in optional service extras.

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
``scrub_pii`` RAISES ``TypeError`` on non-``str`` input. It does not coerce.
Coercion would quietly turn ``None`` into the stored body ``"None"`` and would
stringify a ``bytes`` body into ``"b'...'"`` -- shapes the redaction rules then
fail to match -- so callers on the ingest path must decide explicitly what a
missing or binary body means before scrubbing it.
"""
from __future__ import annotations

import re

__all__ = ["EMAIL_PLACEHOLDER", "SSN_PLACEHOLDER", "scrub_pii"]

EMAIL_PLACEHOLDER = "[REDACTED-EMAIL]"
SSN_PLACEHOLDER = "[REDACTED-SSN]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SSN_RE = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")


def scrub_pii(text: str) -> str:
    """Return ``text`` with email addresses and US SSN shapes redacted.

    Raises ``TypeError`` if ``text`` is not a ``str`` (see module docstring).
    """
    if not isinstance(text, str):
        raise TypeError(f"scrub_pii expects str, got {type(text).__name__}")
    return _SSN_RE.sub(SSN_PLACEHOLDER, _EMAIL_RE.sub(EMAIL_PLACEHOLDER, text))
