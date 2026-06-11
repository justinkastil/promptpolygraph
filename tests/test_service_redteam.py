"""Tests for the WebSocket-streamed Red-Team Arena on the FastAPI service.

Like test_service.py, the POLYGRAPH_* env vars must be set BEFORE importing
the app and the settings cache cleared. Everything runs offline in --mock mode;
no network, no LLM tokens.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# ─── env-before-import (see module docstring) ──────────────────────────────
_D = tempfile.mkdtemp()
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples",
    "support_bot",
)
# NB: the service binds `settings = get_settings()` at module-import time, and
# test modules share one process. We use the SAME api-key convention as
# test_service.py and always pass the key on the socket, so this suite behaves
# correctly regardless of which service test module imported the app first
# (auth enabled with "test-key" either way).
# Use setdefault for everything so we never override a value a sibling service
# test module (sharing this process) set first. We don't need the in-process
# worker (the WS path drives the orchestrator itself), but we also must not
# turn it OFF if test_service.py already turned it on.
os.environ.setdefault("POLYGRAPH_DATABASE_URL", f"sqlite:///{_D}/svc_rt.sqlite")
os.environ.setdefault("POLYGRAPH_OUT_DIR", f"{_D}/out")
os.environ.setdefault("POLYGRAPH_CONFIG_DIR", _CONFIG_DIR)
os.environ.setdefault("POLYGRAPH_API_KEYS", "test-key")
os.environ.setdefault("POLYGRAPH_DEFAULT_MOCK", "true")
os.environ.setdefault("POLYGRAPH_INPROCESS_WORKER", "false")

from promptpolygraph.service.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from promptpolygraph.service.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_redteam_arena_page(client):
    r = client.get("/redteam")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")
    assert "/ws/redteam" in r.text


def test_ws_redteam_streams_to_done(client):
    seen: list[str] = []
    with client.websocket_connect("/ws/redteam?profile=quick&mock=1&key=test-key") as ws:
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] in ("done", "error"):
                break
    assert "agent_spawned" in seen, seen
    assert "verdict" in seen, seen
    assert seen[-1] == "done", seen
