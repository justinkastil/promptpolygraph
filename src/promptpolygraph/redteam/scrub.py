"""Secret scrubbing for source excerpts before they reach a model.

The code-grounded ladder sends ranked source excerpts from the target's checkout
to a model. Even with a local model this is a sensible hygiene layer; with the
frontier (consent) path it is essential. This redacts common secret shapes from
an excerpt string before it is put in a prompt. It is a guard, not a guarantee —
the primary IP protection is the local-model default + air-gap switch.
"""

from __future__ import annotations

import re

_REDACT = "«REDACTED:{label}»"

# (label, compiled pattern, group-to-redact). group 0 means redact the whole match.
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("private-key",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----",
                re.DOTALL), 0),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    ("gh-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 0),
    ("gh-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"), 0),
    ("bearer", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-]{12,})"), 1),
    ("conn-string-creds",
     re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:([^\s:@/]+)@"), 1),
    # KEY = "secret" / api_key: 'secret' style assignments
    ("assigned-secret",
     re.compile(r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?key|client[_-]?secret|"
                r"auth[_-]?token|password|passwd|pwd|private[_-]?key|token)\b\s*[:=]\s*"
                r"['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?"), 1),
]


def scrub_secrets(text: str) -> tuple[str, int]:
    """Redact common secret shapes from ``text``. Returns (scrubbed, redaction_count)."""
    if not text:
        return text, 0
    count = 0

    def _sub(label: str, grp: int):
        def repl(m: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if grp == 0:
                return _REDACT.format(label=label)
            # preserve everything but the captured secret group
            s, e = m.span(grp)
            return m.group(0)[: s - m.start()] + _REDACT.format(label=label) + m.group(0)[e - m.start():]
        return repl

    for label, pat, grp in _PATTERNS:
        text = pat.sub(_sub(label, grp), text)
    return text, count
