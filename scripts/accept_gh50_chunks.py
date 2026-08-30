#!/usr/bin/env python3
"""Founder acceptance for the remaining #50 chunk-boundary finding.

User-flow only. PII split across streamed chunks must not survive storage.
Do not weaken this file.
"""

from __future__ import annotations

import sys
from pathlib import Path


class _Resp:
    def __init__(self, text, chunks):
        self.text = text
        self.tokens_streamed = list(chunks)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    privacy = root / "docs" / "PRIVACY.md"
    if not privacy.is_file() or privacy.stat().st_size < 200:
        raise SystemExit("FAIL #50-chunks docs/PRIVACY.md missing or trivial")
    doc = privacy.read_text(encoding="utf-8").lower()
    if "chunk" not in doc and "stream" not in doc:
        raise SystemExit(
            "FAIL #50-chunks PRIVACY.md must document streamed-chunk redaction"
        )

    try:
        from promptpolygraph.service.privacy import scrub_pii, scrub_response
    except Exception as exc:
        raise SystemExit(
            f"FAIL #50-chunks privacy helpers missing: {exc}"
        ) from exc

    email_chunks = ["Contact jane.doe@", "example.com please"]
    ssn_chunks = ["SSN 123-45-", "6789 is assigned"]
    joined_email = "".join(email_chunks)
    joined_ssn = "".join(ssn_chunks)
    if "jane.doe@example.com" not in joined_email:
        raise SystemExit("FAIL #50-chunks fixture no longer splits an email")
    if "123-45-6789" not in joined_ssn:
        raise SystemExit("FAIL #50-chunks fixture no longer splits an SSN")

    # Control: the concatenated record is PII that scrub_pii already catches.
    if "jane.doe@example.com" in scrub_pii(joined_email):
        raise SystemExit("FAIL #50-chunks scrub_pii lost whole-record email")
    if "123-45-6789" in scrub_pii(joined_ssn):
        raise SystemExit("FAIL #50-chunks scrub_pii lost whole-record SSN")

    out_email = scrub_response(_Resp("hello", email_chunks))
    reconstructed = "".join(
        c for c in (out_email.tokens_streamed or []) if isinstance(c, str)
    )
    if "jane.doe@example.com" in reconstructed:
        raise SystemExit(
            "FAIL #50-chunks email survived tokens_streamed across a chunk boundary"
        )
    if "jane.doe@" in reconstructed and "example.com" in reconstructed:
        raise SystemExit(
            "FAIL #50-chunks email fragments still reconstruct from streamed chunks"
        )

    out_ssn = scrub_response(_Resp("hello", ssn_chunks))
    reconstructed_ssn = "".join(
        c for c in (out_ssn.tokens_streamed or []) if isinstance(c, str)
    )
    if "123-45-6789" in reconstructed_ssn:
        raise SystemExit(
            "FAIL #50-chunks SSN survived tokens_streamed across a chunk boundary"
        )

    # Whole-body text still redacts (do not "fix" chunks by ignoring text).
    out_text = scrub_response(
        _Resp("Contact jane.doe@example.com", ["ok"])
    )
    if "jane.doe@example.com" in (out_text.text or ""):
        raise SystemExit("FAIL #50-chunks Response.text email survived")

    print("accept: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
