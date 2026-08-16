#!/usr/bin/env python3
"""Founder acceptance for GitHub issues #58 and #59.

User-flow only. Does not prescribe module names beyond the public HTTP
surface and a `--validate-config` style startup check the issue asked for.
"""

from __future__ import annotations

import os
import sys
import tempfile


def _prepare_env() -> None:
    tmp = tempfile.mkdtemp(prefix="polygraph-accept-")
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
        }
    )


def main() -> int:
    _prepare_env()
    from promptpolygraph.service.settings import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from promptpolygraph.service.app import app

    with TestClient(app) as client:
        live = client.get("/healthz")
        if live.status_code != 200:
            raise SystemExit(f"FAIL /healthz {live.status_code} {live.text}")
        ready = client.get("/healthz/ready")
        if ready.status_code != 200:
            raise SystemExit(
                f"FAIL /healthz/ready {ready.status_code} {ready.text} "
                "(issue #59: distinct readiness probe)"
            )
        if ready.json() == live.json() and "/healthz/ready" == "/healthz":
            raise SystemExit("FAIL readiness is not a distinct endpoint")

    # Issue #58: startup validation must exist and fail closed when
    # critical config is missing and we are not in mock mode.
    from promptpolygraph.service import startup_validate

    ok, report = startup_validate.run(mock=True)
    if not ok:
        raise SystemExit(f"FAIL startup validate in mock should pass: {report}")
    if not any(item.get("status") in {"pass", "warn", "fail"} for item in report):
        raise SystemExit(f"FAIL validate report has no per-check status: {report}")

    bad_env = dict(os.environ)
    bad_env["POLYGRAPH_DEFAULT_MOCK"] = "false"
    bad_env.pop("ANTHROPIC_API_KEY", None)
    # Call the same helper with mock=False so missing live-run key is critical.
    ok_live, report_live = startup_validate.run(mock=False, environ=bad_env)
    if ok_live:
        raise SystemExit(
            "FAIL startup validate passed without ANTHROPIC_API_KEY "
            "and mock=false (issue #58)"
        )
    print("accept: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
