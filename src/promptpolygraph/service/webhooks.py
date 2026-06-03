"""Fire-and-forget completion callbacks for CI integration.

When a run finishes (done or failed) and a webhook URL is configured (per-run
or globally), POST a compact JSON summary. Failures to deliver are logged, not
raised — a flaky webhook never fails a run.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("promptpolygraph.service.webhooks")


def notify(url: str | None, payload: dict[str, Any], *, timeout: float = 10.0) -> None:
    if not url:
        return
    try:
        httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:  # never let a webhook break a run
        log.warning("webhook delivery failed url=%s err=%s", url, exc)
