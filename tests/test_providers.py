"""Provider discovery + /api/providers endpoint (drives the UI dropdowns)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from promptpolygraph import ui
from promptpolygraph.discovery import discover_providers


def test_discover_shape_no_probe():
    provs = discover_providers(probe_local=False)
    ids = {p["id"] for p in provs}
    assert {"anthropic", "openai", "ollama"} <= ids
    for p in provs:
        assert set(p) >= {"id", "label", "available", "reason", "models", "default_model", "allow_custom"}
        assert isinstance(p["available"], bool)
        assert isinstance(p["models"], list)
    ollama = next(p for p in provs if p["id"] == "ollama")
    assert ollama["available"] is False and "skip" in ollama["reason"].lower()


def test_keyed_provider_availability(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provs = {p["id"]: p for p in discover_providers(probe_local=False)}
    assert provs["anthropic"]["available"] is True
    assert provs["anthropic"]["models"] and provs["anthropic"]["default_model"]
    assert provs["openai"]["available"] is False


def _start(tmp_path):
    import socket

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    base = f"http://127.0.0.1:{port}"
    threading.Thread(target=lambda: ui.serve_dashboard(out_dir=str(tmp_path), port=port, open_browser=False),
                     daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/runs", timeout=1).read(); break
        except OSError:
            time.sleep(0.1)
    return base


def test_providers_endpoint(tmp_path):
    base = _start(tmp_path)
    with urllib.request.urlopen(base + "/api/providers", timeout=5) as r:
        assert r.status == 200
        data = json.loads(r.read())
    assert isinstance(data, list)
    assert {p["id"] for p in data} >= {"anthropic", "openai", "ollama"}


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_status(tmp_path):
    base = _start(tmp_path)
    with urllib.request.urlopen(base + "/api/health", timeout=5) as r:
        h = json.loads(r.read())
    assert h["status"] in ("live", "mock")
    assert isinstance(h["any_provider"], bool) and h["mock_only"] == (not h["any_provider"])
    assert h["providers"]


def test_adapter_test_demo_ok_and_custom_not_wired(tmp_path):
    base = _start(tmp_path)
    st, ok = _post(base, "/api/adapter/test", {"adapter": {"type": "demo"}})
    assert st == 200 and ok["ok"] is True and ok["name"]
    # a custom (callable) adapter with no fn must report it's not wired
    st, bad = _post(base, "/api/adapter/test", {"adapter": {"type": "callable"}})
    assert st == 200 and bad["ok"] is False and "wired" in bad["error"].lower()
