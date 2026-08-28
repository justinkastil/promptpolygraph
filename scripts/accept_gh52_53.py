#!/usr/bin/env python3
"""Founder acceptance for GitHub issues #52 and #53.

User-flow only. Does not prescribe internals beyond the public HTTP
surface and Settings names the issues require. Do not weaken this file.
"""

from __future__ import annotations

import os
import sys
import tempfile


def _prepare_env() -> str:
    tmp = tempfile.mkdtemp(prefix="polygraph-accept-5253-")
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples",
        "support_bot",
    )
    os.environ.update(
        {
            "POLYGRAPH_DATABASE_URL": f"sqlite:///{tmp}/svc.sqlite",
            "POLYGRAPH_OUT_DIR": f"{tmp}/out",
            "POLYGRAPH_CONFIG_DIR": config_dir,
            "POLYGRAPH_API_KEYS": "test-key",
            "POLYGRAPH_DEFAULT_MOCK": "true",
            "POLYGRAPH_INPROCESS_WORKER": "false",
            "POLYGRAPH_MAX_CONCURRENT_RUNS": "1",
            "POLYGRAPH_JOBS_PER_DAY": "100",
            "POLYGRAPH_MONTHLY_COST_BUDGET": "10",
        }
    )
    return tmp


def main() -> int:
    tmp = _prepare_env()
    from promptpolygraph.service.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    from fastapi.testclient import TestClient
    from promptpolygraph.service.app import app

    headers = {"X-API-Key": "test-key"}

    # ── #52: settings /metrics / structured logs ──────────────────────────
    for name in ("db_pool_size",):  # sanity: service still boots
        if not hasattr(settings, name):
            raise SystemExit(f"FAIL settings missing {name}")

    with TestClient(app) as client:
        metrics = client.get("/metrics")
        if metrics.status_code != 200:
            raise SystemExit(
                f"FAIL #52 GET /metrics {metrics.status_code} {metrics.text}"
            )
        body = (metrics.text or "").lower()
        if not any(
            tok in body
            for tok in ("job", "run", "queue", "latency", "error", "cost")
        ):
            raise SystemExit(
                f"FAIL #52 /metrics body has no observability series: {metrics.text[:200]!r}"
            )

        # ── #53: usage surface ────────────────────────────────────────────
        usage = client.get("/api/usage", headers=headers)
        if usage.status_code != 200:
            raise SystemExit(
                f"FAIL #53 GET /api/usage {usage.status_code} {usage.text}"
            )
        payload = usage.json()
        if not isinstance(payload, dict) or not payload:
            raise SystemExit(f"FAIL #53 /api/usage must be a nonempty dict, got {payload!r}")

        # Exceeding a quota must 429. Zero concurrent-run cap is the
        # founder-visible tripwire; other spellings of the same ceiling
        # are accepted if this env is honored.
        os.environ["POLYGRAPH_MAX_CONCURRENT_RUNS"] = "0"
        get_settings.cache_clear()
        from promptpolygraph.service import app as app_mod

        app_mod.settings = get_settings()
        denied = client.post(
            "/api/runs",
            headers=headers,
            json={"config_name": "support_bot", "mock": True},
        )
        if denied.status_code != 429:
            raise SystemExit(
                f"FAIL #53 quota ceiling must return 429, got {denied.status_code} {denied.text}"
            )

    print("accept: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
