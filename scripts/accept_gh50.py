#!/usr/bin/env python3
"""Founder acceptance for GitHub issue #50.

User-flow only. PII on stored responses and export. Do not weaken this file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    privacy = root / "docs" / "PRIVACY.md"
    if not privacy.is_file() or privacy.stat().st_size < 200:
        raise SystemExit("FAIL #50 docs/PRIVACY.md missing or trivial")
    text = privacy.read_text(encoding="utf-8").lower()
    if "residency" not in text or "redact" not in text:
        raise SystemExit("FAIL #50 PRIVACY.md must document residency and redaction")

    try:
        from promptpolygraph.service.privacy import scrub_pii
    except Exception as exc:
        raise SystemExit(
            f"FAIL #50 promptpolygraph.service.privacy.scrub_pii missing: {exc}"
        ) from exc

    raw = "Contact Jane Doe at jane.doe@example.com, SSN 123-45-6789."
    out = scrub_pii(raw)
    if not isinstance(out, str):
        raise SystemExit(f"FAIL #50 scrub_pii must return str, got {type(out)}")
    if "jane.doe@example.com" in out:
        raise SystemExit("FAIL #50 email survived scrub_pii")
    if "123-45-6789" in out:
        raise SystemExit("FAIL #50 SSN survived scrub_pii")

    from promptpolygraph.service.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    if not hasattr(settings, "data_residency"):
        raise SystemExit("FAIL #50 Settings.data_residency missing")

    print("accept: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
