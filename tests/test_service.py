"""End-to-end tests for the FastAPI service.

CRITICAL: `promptpolygraph.service.app` builds its `store` and `settings` at
import time via an lru_cached `get_settings()`. So the POLYGRAPH_* env vars must
be set BEFORE importing the app, and the settings cache cleared. Everything runs
offline in --mock mode with an in-process worker; no API key, no network.
"""

from __future__ import annotations

import os
import tempfile
import time

import pytest

# ─── env-before-import (see module docstring) ──────────────────────────────
_D = tempfile.mkdtemp()
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples",
    "support_bot",
)
os.environ.update(
    {
        "POLYGRAPH_DATABASE_URL": f"sqlite:///{_D}/svc.sqlite",
        "POLYGRAPH_OUT_DIR": f"{_D}/out",
        "POLYGRAPH_CONFIG_DIR": _CONFIG_DIR,
        "POLYGRAPH_API_KEYS": "test-key",
        "POLYGRAPH_DEFAULT_MOCK": "true",
        "POLYGRAPH_WORKER_POLL_S": "0.2",
        "POLYGRAPH_INPROCESS_WORKER": "true",
    }
)

from promptpolygraph.service.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from promptpolygraph.service.app import app  # noqa: E402

H = {"X-API-Key": "test-key"}


@pytest.fixture(scope="module")
def client():
    # `with` runs startup/shutdown so the in-process worker + scheduler spin up.
    with TestClient(app) as c:
        yield c


def _wait_for_done(client, run_id, cap_s=60.0):
    deadline = time.time() + cap_s
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}", headers=H)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("done", "failed", "canceled"):
            return last
        time.sleep(0.5)
    return last


# ─── liveness + auth ──────────────────────────────────────────────────────────


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_runs_requires_api_key(client):
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers=H).status_code == 200


# ─── full run lifecycle ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def finished_run(client):
    """Create a run, wait for the worker to finish it, return (run_id, job_id)."""
    r = client.post(
        "/api/runs",
        headers=H,
        json={
            "config_name": "config",
            "mock": True,
            "overrides": {"per_category": 2},
            "formats": ["md", "html"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["run_id"] and body["job_id"]

    final = _wait_for_done(client, body["run_id"])
    assert final is not None
    assert final["status"] == "done", f"run did not finish: {final}"
    return body["run_id"], body["job_id"]


def test_create_run_response_shape(finished_run):
    run_id, job_id = finished_run
    assert run_id
    assert job_id


def test_summary_keys(client, finished_run):
    run_id, _ = finished_run
    r = client.get(f"/api/runs/{run_id}/summary", headers=H)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert "overall_pass" in summary
    # summary carries per-category / aggregate detail
    assert isinstance(summary, dict) and len(summary) > 1


def test_html_report(client, finished_run):
    run_id, _ = finished_run
    r = client.get(f"/api/runs/{run_id}/report", params={"format": "html"}, headers=H)
    assert r.status_code == 200, r.text
    html = r.text
    assert "Persona" in html
    assert "Forensic" in html


def test_cases_non_empty(client, finished_run):
    run_id, _ = finished_run
    r = client.get(f"/api/runs/{run_id}/cases", headers=H)
    assert r.status_code == 200, r.text
    cases = r.json()
    assert isinstance(cases, list) and len(cases) > 0
    assert "case" in cases[0]


def test_jobs_shows_done(client, finished_run):
    _, job_id = finished_run
    r = client.get("/api/jobs", headers=H)
    assert r.status_code == 200, r.text
    jobs = r.json()
    target = next((j for j in jobs if j["job_id"] == job_id), None)
    assert target is not None
    assert target["status"] == "done"


def test_personas_list(client):
    r = client.get("/api/personas", headers=H)
    assert r.status_code == 200, r.text
    personas = r.json()
    assert isinstance(personas, list)
    assert len(personas) >= 12


def test_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_cancel_finished_run(client, finished_run):
    run_id, _ = finished_run
    r = client.post(f"/api/runs/{run_id}/cancel", headers=H)
    assert r.status_code == 200, r.text
    # a finished run's job is no longer queued, so cancel is a no-op
    assert r.json()["canceled"] is False
