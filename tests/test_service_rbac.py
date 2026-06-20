"""Multi-tenant RBAC + workspace isolation + per-workspace API keys + audit log.

Like test_service.py, POLYGRAPH_* env must be set before importing the app
(settings + store + tenancy are bound at import via lru_cache). Auth is enabled
with a legacy key that resolves to admin of the `default` workspace.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_D = tempfile.mkdtemp()
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "support_bot")
# Use setdefault + the shared "test-key" convention so we never clobber the env a
# sibling service test module (sharing this process + the imported app) set first.
# The legacy "test-key" resolves to admin of the `default` workspace.
os.environ.setdefault("POLYGRAPH_DATABASE_URL", f"sqlite:///{_D}/rbac.sqlite")
os.environ.setdefault("POLYGRAPH_OUT_DIR", f"{_D}/out")
os.environ.setdefault("POLYGRAPH_CONFIG_DIR", _CONFIG_DIR)
os.environ.setdefault("POLYGRAPH_API_KEYS", "test-key")
os.environ.setdefault("POLYGRAPH_DEFAULT_MOCK", "true")
os.environ.setdefault("POLYGRAPH_INPROCESS_WORKER", "false")

from promptpolygraph.service.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from promptpolygraph.service.app import app  # noqa: E402

ADMIN = {"X-API-Key": "test-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_whoami_legacy_is_admin_of_default(client):
    r = client.get("/api/whoami", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["workspace_id"] == "default" and body["role"] == "admin" and body["via"] == "legacy"


def test_bad_key_rejected(client):
    assert client.get("/api/whoami", headers={"X-API-Key": "nope"}).status_code == 401


def test_admin_mints_scoped_keys_and_rbac_enforced(client):
    # admin mints an editor key and a viewer key in the default workspace
    ed = client.post("/api/keys", headers=ADMIN, json={"role": "editor", "label": "ci"})
    assert ed.status_code == 200 and ed.json()["api_key"].startswith("ppg_")
    editor_key = {"X-API-Key": ed.json()["api_key"]}
    vw = client.post("/api/keys", headers=ADMIN, json={"role": "viewer"})
    viewer_key = {"X-API-Key": vw.json()["api_key"]}

    # editor can create a run; viewer cannot (403); both can list
    cr = client.post("/api/runs", headers=editor_key, json={"config_name": "support_bot"})
    assert cr.status_code == 200, cr.text
    assert client.post("/api/runs", headers=viewer_key,
                       json={"config_name": "support_bot"}).status_code == 403
    assert client.get("/api/runs", headers=viewer_key).status_code == 200

    # viewer cannot reach admin endpoints
    assert client.get("/api/keys", headers=viewer_key).status_code == 403
    assert client.get("/api/audit-log", headers=viewer_key).status_code == 403
    assert client.post("/api/keys", headers=editor_key, json={"role": "viewer"}).status_code == 403


def test_workspace_isolation(client):
    # a run created in the default workspace...
    cr = client.post("/api/runs", headers=ADMIN, json={"config_name": "support_bot"})
    run_id = cr.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}", headers=ADMIN).status_code == 200

    # ...is invisible to a second workspace (404, not 403 — existence not leaked)
    ws = client.post("/api/workspaces", headers=ADMIN, json={"name": "acme"})
    assert ws.status_code == 200
    b_admin = {"X-API-Key": ws.json()["admin_api_key"]}
    assert client.get(f"/api/runs/{run_id}", headers=b_admin).status_code == 404
    listed = [s["run_id"] for s in client.get("/api/runs", headers=b_admin).json()]
    assert run_id not in listed
    # the default admin still sees it
    assert run_id in [s["run_id"] for s in client.get("/api/runs", headers=ADMIN).json()]


def test_audit_log_records_and_chain_verifies(client):
    # generate some auditable activity
    client.post("/api/keys", headers=ADMIN, json={"role": "viewer", "label": "audit-probe"})
    r = client.get("/api/audit-log", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    actions = {e["action"] for e in body["entries"]}
    assert "api_key_created" in actions and "run_created" in actions
    assert body["chain"]["ok"] is True


def test_key_revocation(client):
    k = client.post("/api/keys", headers=ADMIN, json={"role": "editor", "label": "temp"}).json()
    kh = {"X-API-Key": k["api_key"]}
    assert client.get("/api/runs", headers=kh).status_code == 200  # works
    prefix = [x for x in client.get("/api/keys", headers=ADMIN).json()
              if x["label"] == "temp"][0]["key_prefix"]
    assert client.request("DELETE", f"/api/keys/{prefix}", headers=ADMIN).status_code == 200
    assert client.get("/api/runs", headers=kh).status_code == 401  # revoked -> rejected
