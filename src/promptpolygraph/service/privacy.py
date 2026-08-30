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

Chunk boundaries (GitHub #50 follow-up)
---------------------------------------
``tokens_streamed`` is an arbitrary transport-level split of one body: a target
may emit ``["Contact jane.doe@", "example.com"]``. Redacting each chunk on its
own leaves both halves intact, and the address reappears the moment anything
joins them. ``scrub_response`` therefore redacts over the *concatenation*: it
computes the spans ``scrub_pii`` would replace in ``"".join(tokens_streamed)``
and writes the result back across the chunk list, so that

    "".join(scrub_response(resp).tokens_streamed) == scrub_pii(joined)

for any list of ``str`` chunks. The redistribution keeps the list shape the
callers and the ``Response`` model expect:

* the output is a ``list[str]`` of the same length, in the same order;
* each placeholder is emitted whole into the chunk where its match *started*,
  so no chunk ever holds a torn ``[REDACTED-`` fragment;
* chunks whose text was swallowed by a placeholder that began earlier shrink,
  possibly to ``""``. Empty chunks are kept rather than dropped, because the
  chunk count is itself observable (assertions inspect first-N-token output).

A ``tokens_streamed`` that is absent, ``None``, or not a list of ``str`` is
left untouched rather than coerced: unlike ``scrub_pii``'s ingest-path input,
this value's shape is fixed by the ``Response`` model, so an off-shape value is
someone else's object and rewriting it would be a surprising side effect. Note
this differs from ``Response.text``, which is scrubbed only when it is a
``str`` for the same reason.
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


def _redaction_spans(text: str) -> list[tuple[int, int, str]]:
    """Return the ``(start, end, placeholder)`` spans ``scrub_pii`` replaces.

    Reproduces ``scrub_pii``'s two-pass order -- emails first, then SSNs over
    the *already email-substituted* text -- while reporting every span in
    coordinates of the original ``text``, which is what the chunk walker needs.

    The second pass runs against the substituted string (not against the gaps
    between email matches) because ``\\b`` resolves differently there: an SSN
    abutting an address sees the placeholder's ``]``, a non-word character,
    where the original text had a word character. Positions are carried back
    through ``origin``. No SSN match can overlap a placeholder -- the SSN
    pattern is digits and separators only, and ``[REDACTED-EMAIL]`` contains no
    digit -- so the spans are disjoint; the guard below is belt-and-braces.
    """
    spans: list[tuple[int, int, str]] = []
    parts: list[str] = []
    origin: list[int] = []  # substituted index -> original index, -1 if injected
    pos = 0
    for match in _EMAIL_RE.finditer(text):
        spans.append((match.start(), match.end(), EMAIL_PLACEHOLDER))
        parts.append(text[pos : match.start()])
        origin.extend(range(pos, match.start()))
        parts.append(EMAIL_PLACEHOLDER)
        origin.extend([-1] * len(EMAIL_PLACEHOLDER))
        pos = match.end()
    parts.append(text[pos:])
    origin.extend(range(pos, len(text)))

    for match in _SSN_RE.finditer("".join(parts)):
        start = origin[match.start()]
        end = origin[match.end() - 1] + 1
        if start >= 0 and end > start:
            spans.append((start, end, SSN_PLACEHOLDER))

    spans.sort()
    return spans


def _scrub_chunks(chunks: list[str]) -> list[str]:
    """Redact ``chunks`` as one body, returning one output chunk per input one.

    ``"".join(_scrub_chunks(cs)) == scrub_pii("".join(cs))`` and
    ``len(_scrub_chunks(cs)) == len(cs)``. Each placeholder lands whole in the
    chunk holding the start of its match; chunks covered by a span that began
    in an earlier chunk lose the covered text and may come back ``""``.
    """
    joined = "".join(chunks)
    spans = _redaction_spans(joined)
    if not spans:
        return list(chunks)

    out: list[str] = []
    cursor = 0  # next index of `joined` not yet emitted or consumed
    index = 0  # next span to place
    start = 0  # index of the current chunk within `joined`
    for chunk in chunks:
        stop = start + len(chunk)
        buf: list[str] = []
        while index < len(spans) and spans[index][0] < stop:
            span_start, span_end, placeholder = spans[index]
            index += 1
            if span_end <= cursor:  # wholly inside an earlier placeholder
                continue
            buf.append(joined[cursor:span_start])
            buf.append(placeholder)
            cursor = max(cursor, span_end)
        if cursor < stop:
            buf.append(joined[cursor:stop])
            cursor = stop
        out.append("".join(buf))
        start = stop
    return out


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
    # Only a genuine list[str] is rewritten; see "Chunk boundaries" above for
    # why an off-shape value is left exactly as the caller had it.
    new_chunks = (
        _scrub_chunks(chunks)
        if isinstance(chunks, list) and all(isinstance(c, str) for c in chunks)
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
