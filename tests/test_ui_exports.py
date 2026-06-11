"""v0.5.1 UI export tests: corpus download (json/jsonl/csv) and persona-panel
YAML export, exercised over a real threaded HTTP server in mock mode (offline)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
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


def _get_raw(base: str, path: str):
    """Return (status, content_type, content_disposition, body_bytes)."""
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return (r.status, r.headers.get("Content-Type"),
                    r.headers.get("Content-Disposition"), r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), None, e.read()


def _post(base: str, path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def _start_server(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(
        target=lambda: ui.serve_dashboard(out_dir=str(tmp_path), port=port, open_browser=False),
        daemon=True,
    )
    t.start()
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/runs", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)
    return base


def _launch_and_wait(base: str) -> str:
    _, resp = _post(base, "/api/run",
                    {"config_name": "everyday_assistant", "overrides": {"mock": True, "per_category": 2}})
    run_id = resp["run_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        _, last = _get(base, f"/api/run/{run_id}/status")
        if last.get("done"):
            break
        time.sleep(0.5)
    return run_id


def test_corpus_export_json_jsonl_csv(tmp_path):
    base = _start_server(tmp_path)
    run_id = _launch_and_wait(base)

    # JSON
    status, ctype, dispo, body = _get_raw(base, f"/api/runs/{run_id}/corpus?format=json")
    assert status == 200
    assert "application/json" in (ctype or "")
    assert "attachment" in (dispo or "") and "corpus.json" in (dispo or "")
    rows = json.loads(body)
    assert isinstance(rows, list) and rows
    assert "prompt" in rows[0] and "category" in rows[0]

    # JSONL
    status, ctype, _, body = _get_raw(base, f"/api/runs/{run_id}/corpus?format=jsonl")
    assert status == 200 and "ndjson" in (ctype or "")
    lines = [ln for ln in body.decode().splitlines() if ln.strip()]
    assert lines and all("prompt" in json.loads(ln) for ln in lines)

    # CSV
    status, ctype, _, body = _get_raw(base, f"/api/runs/{run_id}/corpus?format=csv")
    assert status == 200 and "text/csv" in (ctype or "")
    text = body.decode()
    assert text.splitlines()[0].startswith("prompt,category")

    # prompts_only trims the schema
    _, _, _, body = _get_raw(base, f"/api/runs/{run_id}/corpus?format=json&prompts_only=1")
    rows = json.loads(body)
    assert set(rows[0].keys()) == {"prompt", "category"}


def test_corpus_export_unknown_format_and_run(tmp_path):
    base = _start_server(tmp_path)
    run_id = _launch_and_wait(base)
    status, _, _, _ = _get_raw(base, f"/api/runs/{run_id}/corpus?format=xml")
    assert status == 404
    status, _, _, _ = _get_raw(base, "/api/runs/does-not-exist/corpus?format=json")
    assert status == 404


def test_persona_export_yaml_and_path_guard(tmp_path):
    base = _start_server(tmp_path)
    _, resp = _post(base, "/api/personas/new", {"description": "a busy ops lead", "mock": True})
    path = resp["path"]

    # the saved panel downloads as YAML
    quoted = urllib.parse.quote(path, safe="")
    status, ctype, dispo, body = _get_raw(base, f"/api/personas/files/download?path={quoted}")
    assert status == 200
    assert "attachment" in (dispo or "") and ".yaml" in (dispo or "")
    assert b"personas:" in body

    # a path outside the allowed set is refused (no arbitrary file read)
    bad = urllib.parse.quote("/etc/passwd", safe="")
    status, _, _, _ = _get_raw(base, f"/api/personas/files/download?path={bad}")
    assert status == 404


def test_page_exposes_export_controls():
    from promptpolygraph.ui.page import PAGE

    assert "/corpus?format=json" in PAGE
    assert "/api/personas/files/download" in PAGE
