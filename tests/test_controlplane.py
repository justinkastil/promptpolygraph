"""Control-plane (v0.4) tests: launch a run, poll status, persona studio.

These exercise the additive endpoints in ``ui/server.py`` end-to-end over a
real threaded HTTP server (mirroring ``test_dashboard``), all in mock mode so
the suite runs fully offline with no API key.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from promptpolygraph import ui


def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.status, json.loads(r.read())


def _post(base: str, path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:  # still parse JSON error bodies
        return e.code, json.loads(e.read())


def _start_server(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(
        target=lambda: ui.serve_dashboard(out_dir=str(tmp_path), port=port, open_browser=False),
        daemon=True,
    )
    t.start()
    # wait for the server to accept connections
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/runs", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)
    return base


def test_configs_lists_examples(tmp_path):
    base = _start_server(tmp_path)
    status, configs = _get(base, "/api/configs")
    assert status == 200
    names = {c["name"] for c in configs}
    assert "everyday_assistant" in names
    # every entry resolves to a real config.yaml path
    for c in configs:
        assert c["path"].endswith(".yaml")


def test_launch_run_completes_and_appears(tmp_path):
    base = _start_server(tmp_path)
    status, resp = _post(
        base,
        "/api/run",
        {"config_name": "everyday_assistant", "overrides": {"mock": True, "per_category": 2}},
    )
    assert status == 200, resp
    run_id = resp["run_id"]
    assert resp["status"] == "running"

    # poll until done (cap ~60s)
    done = False
    last = None
    deadline = time.time() + 60
    while time.time() < deadline:
        _, last = _get(base, f"/api/run/{run_id}/status")
        if last.get("done"):
            done = True
            break
        time.sleep(0.5)
    assert done, f"run did not finish: {last}"
    assert not last.get("error"), last
    assert last.get("stage") == "done"

    # the run now shows up in /api/runs
    _, runs = _get(base, "/api/runs")
    assert any(r["run_id"] == run_id for r in runs)

    # and its cases are queryable
    _, cases = _get(base, f"/api/runs/{run_id}/cases")
    assert isinstance(cases, list) and cases


def test_launch_run_by_config_path(tmp_path):
    base = _start_server(tmp_path)
    _, configs = _get(base, "/api/configs")
    path = next(c["path"] for c in configs if c["name"] == "everyday_assistant")
    status, resp = _post(
        base, "/api/run", {"config_path": path, "overrides": {"mock": True, "per_category": 1}}
    )
    assert status == 200, resp
    assert resp.get("run_id")


def test_persona_new_creates_and_saves(tmp_path):
    base = _start_server(tmp_path)
    status, resp = _post(
        base, "/api/personas/new", {"description": "a busy nurse manager", "mock": True}
    )
    assert status == 200, resp
    persona = resp["persona"]
    assert persona["id"] and persona["who"]

    # the saved file is now listed under /api/personas/files
    _, files = _get(base, "/api/personas/files")
    paths = {f["path"] for f in files}
    assert resp["path"] in paths
    # it lives under the out_dir/personas directory
    assert (tmp_path / "personas").is_dir()


def test_persona_generate_panel(tmp_path):
    base = _start_server(tmp_path)
    status, resp = _post(
        base,
        "/api/personas/generate",
        {"count": 4, "domain": "a budgeting assistant", "mock": True},
    )
    assert status == 200, resp
    assert len(resp["panel"]) == 4
    assert resp["path"].endswith(".yaml")

    _, files = _get(base, "/api/personas/files")
    assert resp["path"] in {f["path"] for f in files}


def test_personas_library(tmp_path):
    base = _start_server(tmp_path)
    status, lib = _get(base, "/api/personas")
    assert status == 200
    assert isinstance(lib, list) and lib
    assert all("id" in p and "who" in p for p in lib)


def test_bad_run_request_does_not_crash(tmp_path):
    base = _start_server(tmp_path)
    # missing description -> 400, server stays up
    status, resp = _post(base, "/api/personas/new", {"mock": True})
    assert status == 400
    assert "error" in resp
    # server still serves other endpoints afterwards
    s2, _ = _get(base, "/api/runs")
    assert s2 == 200


def test_page_has_control_plane_and_no_external_urls():
    from promptpolygraph.ui.page import PAGE

    # new control-plane surfaces are present
    assert "New run" in PAGE
    assert "Persona studio" in PAGE
    assert "Case explorer" in PAGE
    assert "/api/run" in PAGE
    assert "/api/configs" in PAGE
    assert "/api/personas" in PAGE
    # Studio now hosts the prompt-corpus generator alongside personas
    assert "Studio" in PAGE
    assert "/api/corpus/generate" in PAGE
    assert "/api/corpus/export" in PAGE
    # still offline-only (mirrors test_dashboard)
    cleaned = PAGE.replace("http://127.0.0.1", "").replace("http://localhost", "")
    assert "http://" not in cleaned
    assert "https://" not in PAGE
