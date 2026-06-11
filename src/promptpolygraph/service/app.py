"""FastAPI application: trigger runs, poll status, fetch reports, compare, manage personas.

Endpoints under /api are API-key protected. The root serves a dashboard. The
app can run an in-process worker + scheduler (single-container / local) or defer
to dedicated worker containers in production.

Summary, markdown, and html are re-rendered on demand from the store when the
on-disk artifact is absent, so those work without a shared volume; docx/pdf are
served from the run's output directory (mount a shared volume in multi-container
deployments).
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from .. import analyze as A
from .. import persona as P
from ..compare import pairwise as pairwise_fn
from ..config import Config
from .auth import require_api_key
from .db import SqlStore, make_store
from .jobspec import payload_from_request
from .schemas import (
    CreatePersonaRequest,
    CreateRunRequest,
    CreateRunResponse,
    RunStatus,
)
from .settings import get_settings

settings = get_settings()
store: SqlStore = make_store(settings.database_url)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the optional in-process worker + scheduler, and clean them up."""
    bg = None
    scheduler = None
    if settings.inprocess_worker:
        from .worker import start_background_worker

        bg = start_background_worker(settings)
    from .scheduler import start_scheduler

    scheduler = start_scheduler(store, settings)
    try:
        yield
    finally:
        if bg is not None:
            bg.set()
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title=settings.title, version="0.1.0", lifespan=_lifespan)


# ─── liveness + dashboard ───────────────────────────────────────────────────


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "database": store.engine.dialect.name}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    from .dashboard import render_dashboard

    return render_dashboard(store, settings)


# ─── red-team arena (live event stream over WebSocket) ──────────────────────


def _fallback_arena_page(stream_url: str) -> str:
    """Minimal inline Arena page used until the dedicated UI lands."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Red-Team Arena</title>
<style>
  body {{ font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         margin: 0; background: #0b0e14; color: #d7dce5; }}
  header {{ padding: 12px 16px; background: #11161f; border-bottom: 1px solid #1c2430; }}
  h1 {{ font-size: 16px; margin: 0; }}
  #log {{ padding: 12px 16px; }}
  .ev {{ margin: 2px 0; white-space: pre-wrap; word-break: break-word; }}
  .t-agent_spawned {{ color: #7ee787; }}
  .t-attack {{ color: #f0883e; }}
  .t-response {{ color: #79c0ff; }}
  .t-verdict {{ color: #ff7b72; }}
  .t-vuln {{ color: #ffa657; }}
  .t-summary, .t-done {{ color: #d2a8ff; }}
  .t-error {{ color: #ff7b72; font-weight: bold; }}
  .ty {{ opacity: 0.6; }}
</style></head>
<body>
<header><h1>Red-Team Arena <span class="ty">(live)</span></h1></header>
<div id="log"></div>
<script>
  var proto = location.protocol === "https:" ? "wss:" : "ws:";
  var url = proto + "//" + location.host + {stream_url!r};
  var log = document.getElementById("log");
  function line(ev) {{
    var div = document.createElement("div");
    div.className = "ev t-" + ev.type;
    var label = ev.type;
    if (ev.attacker_id) label += " " + ev.attacker_id;
    if (ev.strategy) label += " " + ev.strategy;
    var body = ev.delta || ev.text || JSON.stringify(ev.verdict || ev.data || {{}});
    div.textContent = "[" + label + "] " + (body || "");
    log.appendChild(div);
    window.scrollTo(0, document.body.scrollHeight);
  }}
  var ws = new WebSocket(url);
  ws.onmessage = function(m) {{ try {{ line(JSON.parse(m.data)); }} catch (e) {{}} }};
  ws.onerror = function() {{ var d = document.createElement("div");
    d.className = "ev t-error"; d.textContent = "[connection error]"; log.appendChild(d); }};
</script>
</body></html>"""


@app.get("/redteam", response_class=HTMLResponse)
def redteam_arena() -> str:
    stream_url = "/ws/redteam"
    try:
        from ..ui.arena import render_arena_page  # type: ignore

        return render_arena_page(stream_url=stream_url, transport="ws")
    except Exception:
        return _fallback_arena_page(stream_url)


def _ws_authorized(websocket: WebSocket, key: str | None) -> bool:
    """Validate the API key against the same key set as `require_api_key`.

    When auth is disabled (no keys configured) all connections are allowed.
    The key may arrive as a `key=` query param or as the first subprotocol.
    """
    if not settings.auth_enabled:
        return True
    if not key:
        protos = websocket.headers.get("sec-websocket-protocol")
        if protos:
            key = protos.split(",")[0].strip()
    return bool(key) and key in settings.api_key_set


def _build_redteam_adapter(config_name: str | None, config_path: str | None):
    from ..adapters import DemoAdapter, build_adapter

    path = config_path
    if path is None and config_name:
        path = str(Path(settings.config_dir).expanduser() / f"{config_name}.yaml")
    if path:
        return build_adapter(Config.load(path).adapter)
    return DemoAdapter(style="everyday")


@app.websocket("/ws/redteam")
async def ws_redteam(
    websocket: WebSocket,
    profile: str = Query("all_frontier"),
    config_name: str | None = Query(None),
    config_path: str | None = Query(None),
    mock: bool = Query(True),
    key: str | None = Query(None),
) -> None:
    """Run a red-team and stream the live event feed to the browser Arena.

    `emit` is called synchronously from the orchestrator's context, so it hops
    onto this socket's event loop via `call_soon_threadsafe` and pushes each
    event onto a queue the socket coroutine drains.
    """
    from ..redteam import RedTeamEvent, get_profile, run_redteam

    await websocket.accept(
        subprotocol=websocket.headers.get("sec-websocket-protocol", "").split(",")[0].strip() or None
    )
    if not _ws_authorized(websocket, key):
        await websocket.send_json({"type": "error", "data": {"detail": "invalid or missing API key"}})
        await websocket.close(code=1008)
        return

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _emit(ev) -> None:
        # emit() is sync and may be invoked from a worker context — hop the loop.
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    try:
        prof = get_profile(profile)
        adapter = _build_redteam_adapter(config_name, config_path)
    except Exception as exc:
        await websocket.send_json({"type": "error", "data": {"detail": str(exc)}})
        await websocket.close(code=1011)
        return

    async def _drive() -> None:
        try:
            await run_redteam(adapter, prof, emit=_emit, mock=mock)
        except Exception as exc:  # surface engine failures as a terminal error event
            loop.call_soon_threadsafe(
                queue.put_nowait, RedTeamEvent(type="error", data={"detail": str(exc)})
            )

    runner = asyncio.create_task(_drive())
    try:
        while True:
            ev = await queue.get()
            await websocket.send_json(ev.model_dump())
            if ev.type in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        runner.cancel()
        try:
            await runner
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await websocket.close()
        except Exception:
            pass


# ─── runs ─────────────────────────────────────────────────────────────────


@app.post("/api/runs", response_model=CreateRunResponse, dependencies=[Depends(require_api_key)])
def create_run(req: CreateRunRequest) -> CreateRunResponse:
    payload = payload_from_request(req, settings)
    if payload.get("webhook_url") is None and settings.webhook_url:
        payload["webhook_url"] = settings.webhook_url
    ids = store.enqueue_job(payload, priority=req.priority)
    return CreateRunResponse(run_id=ids["run_id"], job_id=ids["job_id"], status="queued")


@app.get("/api/runs", dependencies=[Depends(require_api_key)])
def list_runs(limit: int = Query(100, ge=1, le=500)) -> list[RunStatus]:
    out: list[RunStatus] = []
    runs = {r.run_id: r for r in store.list_runs(limit=limit)}
    jobs = store.list_jobs(limit=limit)
    job_by_run = {j["run_id"]: j for j in jobs}
    # include queued/running runs that have no run row yet
    for jid, job in job_by_run.items():
        if jid not in runs:
            out.append(_status_from_job(job))
    for run_id, meta in runs.items():
        out.append(_status(meta, job_by_run.get(run_id)))
    out.sort(key=lambda s: s.created_at or "", reverse=True)
    return out[:limit]


@app.get("/api/runs/{run_id}", response_model=RunStatus, dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> RunStatus:
    meta = store.get_run(run_id)
    job = store.get_job_for_run(run_id)
    if not meta and not job:
        raise HTTPException(404, "run not found")
    return _status(meta, job) if meta else _status_from_job(job)


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_run(run_id: str) -> dict:
    job = store.get_job_for_run(run_id)
    if not job:
        raise HTTPException(404, "run not found")
    ok = store.cancel_job(job["job_id"])
    return {"run_id": run_id, "canceled": ok}


@app.get("/api/runs/{run_id}/summary", dependencies=[Depends(require_api_key)])
def get_summary(run_id: str) -> dict:
    return _summary(run_id)


@app.get("/api/runs/{run_id}/cases", dependencies=[Depends(require_api_key)])
def get_cases(run_id: str) -> list[dict]:
    cases = store.get_cases(run_id)
    rmap = {r.case_id: r for r in store.get_responses(run_id)}
    smap = {s.case_id: s for s in store.get_scores(run_id)}
    return [
        {
            "case": c.model_dump(),
            "response": rmap[c.id].model_dump() if c.id in rmap else None,
            "score": smap[c.id].model_dump() if c.id in smap else None,
        }
        for c in cases
    ]


@app.get("/api/runs/{run_id}/audit", dependencies=[Depends(require_api_key)])
def get_audit(run_id: str) -> dict:
    path = _run_dir(run_id) / "audit.json"
    if not path.exists():
        raise HTTPException(404, "no audit for this run")
    return json.loads(path.read_text())


@app.get("/api/runs/{run_id}/report", dependencies=[Depends(require_api_key)])
def get_report(run_id: str, format: str = Query("html")):
    fmt = format.lower()
    rd = _run_dir(run_id)
    disk = rd / f"report.{fmt}"
    if fmt in ("docx", "pdf"):
        if not disk.exists():
            raise HTTPException(404, f"{fmt} report not available (needs the run's output volume)")
        return FileResponse(str(disk), filename=f"report.{fmt}")
    if disk.exists():
        text = disk.read_text()
    else:
        text = _render(run_id, fmt)  # re-render from the store
    if fmt == "html":
        return HTMLResponse(text)
    return PlainTextResponse(text)


# ─── jobs ─────────────────────────────────────────────────────────────────


@app.get("/api/jobs", dependencies=[Depends(require_api_key)])
def list_jobs(status: str | None = None, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return [_job_public(j) for j in store.list_jobs(status=status, limit=limit)]


# ─── compare ────────────────────────────────────────────────────────────────


@app.get("/api/compare", dependencies=[Depends(require_api_key)])
def compare(run_a: str, run_b: str) -> dict:
    cases = store.get_cases(run_a)
    pw = pairwise_fn(cases, store.get_scores(run_a), store.get_scores(run_b))
    pw["run_a"], pw["run_b"] = run_a, run_b
    return pw


# ─── personas ───────────────────────────────────────────────────────────────


@app.get("/api/personas", dependencies=[Depends(require_api_key)])
def list_personas() -> list[dict]:
    return [p.model_dump() for p in P.load_library()]


@app.post("/api/personas", dependencies=[Depends(require_api_key)])
async def create_persona(req: CreatePersonaRequest) -> dict:
    mock = settings.default_mock if req.mock is None else req.mock
    client = None
    if not mock:
        from ..llm import make_client

        client = make_client()
    persona = await P.create_persona(client, req.description, mock=mock)
    return persona.model_dump()


# ─── helpers ──────────────────────────────────────────────────────────────


def _run_dir(run_id: str) -> Path:
    return Path(settings.out_dir).expanduser() / run_id


def _status(meta, job: dict | None) -> RunStatus:
    status = (job or {}).get("status") or ("done" if meta.completed_at else "running")
    return RunStatus(
        run_id=meta.run_id, job_id=(job or {}).get("job_id"), status=status,
        mode=meta.mode, adapter=meta.adapter,
        progress=_progress(job), error=(job or {}).get("error"),
        total_cases=meta.total_cases, completed_cases=meta.completed_cases,
        overall_pass=_overall_pass(meta.run_id),
        created_at=meta.created_at, completed_at=meta.completed_at,
    )


def _status_from_job(job: dict) -> RunStatus:
    return RunStatus(
        run_id=job["run_id"], job_id=job["job_id"], status=job["status"],
        progress=_progress(job), error=job.get("error"), created_at=job.get("created_at"),
    )


def _progress(job: dict | None) -> dict | None:
    if not job or not job.get("progress"):
        return None
    try:
        return json.loads(job["progress"])
    except (TypeError, ValueError):
        return None


def _overall_pass(run_id: str) -> bool | None:
    path = _run_dir(run_id) / "summary.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("overall_pass")
        except (ValueError, OSError):
            return None
    return None


def _job_public(j: dict) -> dict:
    return {
        "job_id": j["job_id"], "run_id": j["run_id"], "status": j["status"],
        "attempts": j.get("attempts"), "error": j.get("error"),
        "created_at": j.get("created_at"), "started_at": j.get("started_at"),
        "finished_at": j.get("finished_at"),
    }


def _rubric_for(run_id: str):
    meta = store.get_run(run_id)
    if meta and meta.config:
        try:
            cfg = Config(**meta.config)
            if cfg.analyze.rubric:
                return A.load_rubric(cfg.resolve(cfg.analyze.rubric))
        except Exception:
            pass
    return A.default_rubric()


def _summary(run_id: str) -> dict:
    path = _run_dir(run_id) / "summary.json"
    if path.exists():
        return json.loads(path.read_text())
    cases = store.get_cases(run_id)
    if not cases:
        raise HTTPException(404, "run not found or not analyzed")
    return A.summarize(cases, store.get_responses(run_id), store.get_scores(run_id), _rubric_for(run_id))


def _render(run_id: str, fmt: str) -> str:
    from ..report import render_html, render_markdown

    meta = store.get_run(run_id)
    if not meta:
        raise HTTPException(404, "run not found")
    cases = store.get_cases(run_id)
    responses = store.get_responses(run_id)
    scores = store.get_scores(run_id)
    rubric = _rubric_for(run_id)
    summary = _summary(run_id)
    audit_path = _run_dir(run_id) / "audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
    fn = render_html if fmt == "html" else render_markdown
    return fn(meta, cases, responses, scores, summary, rubric=rubric, audit=audit)
