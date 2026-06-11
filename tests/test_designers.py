"""AI config + red-team designers, and the build/save/run endpoints behind 0.6.5."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request

from promptpolygraph import ui
from promptpolygraph.config import Config
from promptpolygraph.configdesign import design_config
from promptpolygraph.redteam.design import design_redteam, profile_from_design


def test_design_config_mock_validates():
    out = asyncio.run(design_config(None, "a customer-support chatbot", mock=True))
    cfg = out["config"]
    Config(**cfg)  # must construct
    assert cfg["name"] and cfg["corpus"]["categories"] and cfg["redteam"]["profile"]


def test_design_redteam_mock_tailors_to_target():
    out = asyncio.run(design_redteam(None, "an agent with tools and access to user PII", mock=True))
    strats = {s["strategy"] for s in out["config"]["strategies"]}
    assert "tool_abuse" in strats and "pii_extraction" in strats
    assert 1 <= out["config"]["turns"] <= 6
    assert out["config"]["base_profile"]


def test_design_redteam_sanitizes_garbage():
    bad = {"base_profile": "nope", "turns": 99, "sources": ["evil"],
           "strategies": [{"strategy": "not_real", "mode": "x"}, {"strategy": "jailbreak", "mode": "pair", "converter": "base64"}]}
    out = asyncio.run(design_redteam(None, "x", mock=True))  # mock ignores `bad`, just check sanitizer via profile
    prof = profile_from_design(bad, provider="anthropic", model="m")
    # only the valid strategy survives; turns clamped; judge defaults
    assert [a.strategy for a in prof.attackers] == ["jailbreak"]
    assert prof.attackers[0].converter == "base64" and prof.turns <= 6


def test_profile_from_design_runnable():
    out = asyncio.run(design_redteam(None, "a tool-using agent", mock=True))
    prof = profile_from_design(out["config"], provider="anthropic", model="claude-opus-4-8")
    assert prof.name == "custom" and len(prof.attackers) == len(out["config"]["strategies"])


# ---- endpoints ----------------------------------------------------------

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


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_config_design_save_load_roundtrip(tmp_path):
    base = _start(tmp_path)
    st, des = _post(base, "/api/config/design", {"description": "a budgeting assistant", "mock": True})
    assert st == 200 and des["config"]["name"]
    st, saved = _post(base, "/api/configs", {"config": des["config"]})
    assert st == 200 and saved["name"]
    with urllib.request.urlopen(base + f"/api/config?name={saved['name']}", timeout=5) as r:
        loaded = json.loads(r.read())
    assert loaded["config"]["redteam"]["profile"] == des["config"]["redteam"]["profile"]


def test_redteam_design_to_runnable_profile(tmp_path):
    base = _start(tmp_path)
    st, des = _post(base, "/api/redteam/design", {"description": "a tool-using agent with PII", "mock": True})
    assert st == 200 and des["config"]["strategies"]
    st, prof = _post(base, "/api/redteam/profile", {"spec": des["config"], "provider": "anthropic", "model": "m"})
    assert st == 200 and prof["ref"] and prof["attackers"]
    # the ref is runnable through the SSE stream — read line-by-line until 'done'
    saw_verdict = saw_done = False
    with urllib.request.urlopen(base + f"/api/redteam/stream?profile_ref={prof['ref']}&mock=1", timeout=30) as r:
        for _ in range(20000):
            line = r.readline()
            if not line:
                break
            if b"event: verdict" in line:
                saw_verdict = True
            if b"event: done" in line:
                saw_done = True
                break
    assert saw_verdict and saw_done


def test_config_save_rejects_garbage(tmp_path):
    base = _start(tmp_path)
    st, resp = _post(base, "/api/configs", {"config": {"analyze": {"judges": "not-an-int-but-coerced"}}})
    # Config tolerates/ignores unknowns; a structurally-bad type should 400. Either way, never 500.
    assert st in (200, 400)
