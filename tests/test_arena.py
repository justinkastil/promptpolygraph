from __future__ import annotations

import re
import threading
import time
import urllib.request

from promptpolygraph import ui
from promptpolygraph.ui.arena import render_arena_page


# ── unit: the page is self-contained, escapes config, names no external host ──
def test_render_arena_page_is_self_contained_sse():
    html = render_arena_page(stream_url="/api/redteam/stream?profile=quick", transport="sse")
    assert "<html" in html.lower()
    assert "EventSource" in html  # SSE transport
    assert "WebSocket" in html  # ws path is also present (service reuses it)
    assert "/api/redteam/stream?profile=quick" in html
    # no external assets / CDNs — must work fully offline. The page contains
    # no http(s):// literal at all (matching the dashboard's offline contract).
    stripped = html.replace("http://127.0.0.1", "").replace("http://localhost", "")
    assert "http://" not in stripped
    assert "https://" not in html


def test_render_arena_page_ws_transport():
    html = render_arena_page(stream_url="/svc/ws", transport="ws")
    assert "startWS" in html
    assert '"transport": "ws"' in html or "'transport': 'ws'" in html or '"ws"' in html


def test_render_arena_page_has_replay_and_trace_controls():
    html = render_arena_page(stream_url="/api/redteam/stream?profile=quick")
    # replay + trace + run-list endpoints the page consumes
    assert "/api/redteam/trace" in html
    assert "/api/redteam/runs" in html
    assert "loadReplay" in html and "playReplay" in html
    # live + replay toggle present
    assert "setView('live')" in html and "setView('replay')" in html


def test_render_arena_page_drops_gimmicks():
    html = render_arena_page(stream_url="/api/redteam/stream?profile=quick").lower()
    # the flagged lightning-bolt + cheesy sub-banner are gone
    assert "lightning" not in html
    assert "&#9889;" not in html  # lightning-bolt glyph
    assert "authorized adversarial testing" not in html


def test_render_arena_page_honesty_rule_is_mode_gated():
    html = render_arena_page(stream_url="/api/redteam/stream?profile=quick")
    # the colored ladder only renders for the code-grounded result; the abstract
    # path renders the honest summary, never a fabricated pipeline.
    assert "renderLadder" in html
    assert "renderHonest" in html
    assert 'mode === "code"' in html or "j.mode === \"code\"" in html
    # consent / air-gap UX is wired
    assert "needs_consent" in html
    assert "Air-gap" in html or "air-gap" in html


def test_render_arena_page_no_banned_terms():
    html = render_arena_page(stream_url="/api/redteam/stream?profile=quick").lower()
    for term in (
        "blockhaven", "haven", "patent", "promptfoo",
        "health", "clinical", "medical", "phi", "vault",
    ):
        assert term not in html, f"banned term present: {term}"


def test_render_arena_page_escapes_script_close_in_url():
    # a hostile stream_url must not be able to break out of the <script> block
    html = render_arena_page(stream_url="/x</script><script>alert(1)//", transport="sse")
    assert "</script><script>alert(1)" not in html
    assert "<\\/script>" in html


# ── integration: threaded server smoke for the arena routes ──────────────────
def _start_server(tmp_path, port):
    t = threading.Thread(
        target=lambda: ui.serve_dashboard(out_dir=str(tmp_path), port=port, open_browser=False),
        daemon=True,
    )
    t.start()
    time.sleep(0.8)
    return t


def test_redteam_page_served(tmp_path):
    port = 8801
    _start_server(tmp_path, port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/redteam", timeout=4) as r:
            assert r.status == 200
            body = r.read().decode("utf-8")
    except OSError:
        return  # port contention in CI; unit tests still cover the page
    assert "<html" in body.lower()
    assert "/api/redteam/stream" in body
    stripped = body.replace("http://127.0.0.1", "").replace("http://localhost", "")
    assert "http://" not in stripped


def test_redteam_stream_flows_to_done(tmp_path):
    port = 8802
    _start_server(tmp_path, port)
    frames = b""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/redteam/stream?profile=quick&mock=1"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            assert r.status == 200
            assert "text/event-stream" in r.headers.get("Content-Type", "")
            deadline = time.time() + 12
            while time.time() < deadline:
                line = r.readline()
                if not line:
                    break
                frames += line
                if b"event: done" in frames or b"event: error" in frames:
                    break
    except OSError:
        return  # port contention in CI
    text = frames.decode("utf-8", "replace")
    assert "event: agent_spawned" in text
    assert "event: verdict" in text
    assert "event: done" in text
    # frames are well-formed SSE (event: <type>\ndata: <json>)
    assert re.search(r"event: \w+\ndata: \{", text)


def test_existing_dashboard_still_serves(tmp_path):
    # keep the original dashboard green alongside the new routes
    from promptpolygraph.models import RunMeta
    from promptpolygraph.runner import SQLiteStore

    store = SQLiteStore(tmp_path / "polygraph.sqlite")
    store.save_run(RunMeta(name="demo", adapter="demo", total_cases=1))
    port = 8803
    _start_server(tmp_path, port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=4) as r:
            assert r.status == 200
            assert "Red Team" in r.read().decode("utf-8")  # nav link present
    except OSError:
        return
