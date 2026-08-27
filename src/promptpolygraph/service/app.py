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
from .auth import get_principal, require_api_key, require_role
from .db import SqlStore, make_store
from .tenancy import ROLES, Principal, get_tenancy
from .jobspec import payload_from_request
from .schemas import (
    CreatePersonaRequest,
    CreateRunRequest,
    CreateRunResponse,
    RunStatus,
)
from .settings import get_settings
from . import readiness, startup_validate, shutdown

settings = get_settings()
store: SqlStore = make_store(settings.database_url)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the optional in-process worker + scheduler, and clean them up."""
    ok, report = startup_validate.run(settings=settings)
    if not ok:
        failures = "; ".join(item["detail"] for item in report if item["status"] == "fail")
        raise RuntimeError(f"service startup validation failed: {failures}")
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
        shutdown.begin_drain()
        if bg is not None:
            bg.set()
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        drained = shutdown.wait(settings.shutdown_drain_seconds)
        if bg is not None:
            bg.join(timeout=0)
        import logging
        logging.getLogger("promptpolygraph.service").info(
            "shutdown summary: %s drained=%s", shutdown.summary(), drained)


app = FastAPI(title=settings.title, version="0.1.0", lifespan=_lifespan)


# ─── liveness + dashboard ───────────────────────────────────────────────────


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "database": store.engine.dialect.name}


@app.get("/healthz/ready")
def healthz_ready() -> JSONResponse:
    ok, checks = readiness.check(store, settings)
    if shutdown.is_draining():
        ok = False
        checks.append({"check": "drain", "status": "fail", "detail": "service is draining"})
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )


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
    sources: str | None = Query(None),
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

    src_list = [s.strip() for s in (sources or "").split(",") if s.strip()]

    async def _drive() -> None:
        try:
            await run_redteam(adapter, prof, emit=_emit, mock=mock, extra_sources=src_list)
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


def _require_run_access(run_id: str, principal: Principal) -> None:
    """404 if the run is not in the caller's workspace (don't leak existence)."""
    if not get_tenancy().owns_run(run_id, principal.workspace_id):
        raise HTTPException(404, "run not found")


@app.post("/api/runs", response_model=CreateRunResponse)
def create_run(req: CreateRunRequest,
               principal: Principal = Depends(require_role("editor"))) -> CreateRunResponse:
    payload = payload_from_request(req, settings)
    if payload.get("webhook_url") is None and settings.webhook_url:
        payload["webhook_url"] = settings.webhook_url
    ids = store.enqueue_job(payload, priority=req.priority)
    tenancy = get_tenancy()
    tenancy.claim_run(ids["run_id"], principal.workspace_id)
    tenancy.audit(principal.workspace_id, "run_created", actor=principal.subject,
                  run_id=ids["run_id"], job_id=ids["job_id"])
    return CreateRunResponse(run_id=ids["run_id"], job_id=ids["job_id"], status="queued")


@app.get("/api/runs")
def list_runs(limit: int = Query(100, ge=1, le=500),
              principal: Principal = Depends(require_role("viewer"))) -> list[RunStatus]:
    tenancy = get_tenancy()
    out: list[RunStatus] = []
    runs = {r.run_id: r for r in store.list_runs(limit=limit)}
    jobs = store.list_jobs(limit=limit)
    job_by_run = {j["run_id"]: j for j in jobs}

    def visible(run_id: str) -> bool:
        return tenancy.owns_run(run_id, principal.workspace_id)

    # include queued/running runs that have no run row yet
    for jid, job in job_by_run.items():
        if jid not in runs and visible(jid):
            out.append(_status_from_job(job))
    for run_id, meta in runs.items():
        if visible(run_id):
            out.append(_status(meta, job_by_run.get(run_id)))
    out.sort(key=lambda s: s.created_at or "", reverse=True)
    return out[:limit]


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str, principal: Principal = Depends(require_role("viewer"))) -> RunStatus:
    meta = store.get_run(run_id)
    job = store.get_job_for_run(run_id)
    if not meta and not job:
        raise HTTPException(404, "run not found")
    _require_run_access(run_id, principal)
    return _status(meta, job) if meta else _status_from_job(job)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, principal: Principal = Depends(require_role("editor"))) -> dict:
    job = store.get_job_for_run(run_id)
    if not job:
        raise HTTPException(404, "run not found")
    _require_run_access(run_id, principal)
    ok = store.cancel_job(job["job_id"])
    get_tenancy().audit(principal.workspace_id, "run_canceled", actor=principal.subject,
                        run_id=run_id)
    return {"run_id": run_id, "canceled": ok}


@app.get("/api/runs/{run_id}/summary")
def get_summary(run_id: str, principal: Principal = Depends(require_role("viewer"))) -> dict:
    _require_run_access(run_id, principal)
    return _summary(run_id)


@app.get("/api/runs/{run_id}/cases")
def get_cases(run_id: str, principal: Principal = Depends(require_role("viewer"))) -> list[dict]:
    _require_run_access(run_id, principal)
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


@app.get("/api/runs/{run_id}/audit")
def get_audit(run_id: str, principal: Principal = Depends(require_role("viewer"))) -> dict:
    _require_run_access(run_id, principal)
    path = _run_dir(run_id) / "audit.json"
    if not path.exists():
        raise HTTPException(404, "no audit for this run")
    return json.loads(path.read_text())


@app.get("/api/runs/{run_id}/report")
def get_report(run_id: str, format: str = Query("html"),
               principal: Principal = Depends(require_role("viewer"))):
    _require_run_access(run_id, principal)
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


@app.get("/api/jobs")
def list_jobs(status: str | None = None, limit: int = Query(100, ge=1, le=500),
              principal: Principal = Depends(require_role("viewer"))) -> list[dict]:
    tenancy = get_tenancy()
    return [_job_public(j) for j in store.list_jobs(status=status, limit=limit)
            if tenancy.owns_run(j["run_id"], principal.workspace_id)]


@app.get("/api/jobs/dead-letter")
def dead_letter_jobs(limit: int = Query(100, ge=1, le=500),
                     principal: Principal = Depends(require_role("viewer"))) -> list[dict]:
    tenancy = get_tenancy()
    return [_job_public(j) for j in store.list_jobs(status="dead_letter", limit=limit)
            if tenancy.owns_run(j["run_id"], principal.workspace_id)]


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, principal: Principal = Depends(require_role("editor"))) -> dict:
    job = store.get_job(job_id)
    if not job or not get_tenancy().owns_run(job["run_id"], principal.workspace_id):
        raise HTTPException(404, "job not found")
    retried = store.retry_job(job_id)
    if retried is None:
        raise HTTPException(409, "job is not eligible for retry")
    return _job_public(retried)


# ─── compare ────────────────────────────────────────────────────────────────


@app.get("/api/compare")
def compare(run_a: str, run_b: str,
            principal: Principal = Depends(require_role("viewer"))) -> dict:
    _require_run_access(run_a, principal)
    _require_run_access(run_b, principal)
    cases = store.get_cases(run_a)
    pw = pairwise_fn(cases, store.get_scores(run_a), store.get_scores(run_b))
    pw["run_a"], pw["run_b"] = run_a, run_b
    return pw


# ─── personas ───────────────────────────────────────────────────────────────


@app.get("/api/personas", dependencies=[Depends(require_api_key)])
def list_personas() -> list[dict]:
    return [p.model_dump() for p in P.load_library()]


@app.post("/api/personas")
async def create_persona(req: CreatePersonaRequest,
                         principal: Principal = Depends(require_role("editor"))) -> dict:
    mock = settings.default_mock if req.mock is None else req.mock
    client = None
    if not mock:
        from ..llm import make_client

        client = make_client()
    persona = await P.create_persona(client, req.description, mock=mock)
    return persona.model_dump()


# ─── admin: workspaces, members, API keys, audit log ─────────────────────────


@app.get("/api/whoami")
def whoami(principal: Principal = Depends(get_principal)) -> dict:
    return {"workspace_id": principal.workspace_id, "role": principal.role,
            "subject": principal.subject, "via": principal.via}


@app.get("/api/workspaces")
def list_workspaces(principal: Principal = Depends(require_role("admin"))) -> list[dict]:
    return get_tenancy().list_workspaces()


@app.post("/api/workspaces")
def create_workspace(body: dict, principal: Principal = Depends(require_role("admin"))) -> dict:
    name = (body or {}).get("name")
    if not name:
        raise HTTPException(400, "name is required")
    t = get_tenancy()
    ws = t.create_workspace(name)
    # bootstrap: mint an initial admin key for the new workspace (returned once).
    key = t.create_api_key(ws["workspace_id"], "admin", label="bootstrap-admin")
    t.audit(principal.workspace_id, "workspace_created", actor=principal.subject,
            new_workspace_id=ws["workspace_id"], name=ws["name"])
    return {**ws, "admin_api_key": key["api_key"]}


@app.get("/api/members")
def list_members(principal: Principal = Depends(require_role("admin"))) -> list[dict]:
    return get_tenancy().list_members(principal.workspace_id)


@app.post("/api/members")
def add_member(body: dict, principal: Principal = Depends(require_role("admin"))) -> dict:
    subject, role = (body or {}).get("subject"), (body or {}).get("role")
    if not subject or role not in ROLES:
        raise HTTPException(400, f"subject + role required (role in {ROLES})")
    out = get_tenancy().add_member(principal.workspace_id, subject, role)
    get_tenancy().audit(principal.workspace_id, "member_added", actor=principal.subject,
                        subject=subject, role=role)
    return out


@app.get("/api/keys")
def list_keys(principal: Principal = Depends(require_role("admin"))) -> list[dict]:
    return get_tenancy().list_api_keys(principal.workspace_id)


@app.post("/api/keys")
def create_key(body: dict, principal: Principal = Depends(require_role("admin"))) -> dict:
    role = (body or {}).get("role", "viewer")
    if role not in ROLES:
        raise HTTPException(400, f"role must be one of {ROLES}")
    out = get_tenancy().create_api_key(principal.workspace_id, role, (body or {}).get("label", ""))
    get_tenancy().audit(principal.workspace_id, "api_key_created", actor=principal.subject,
                        role=role, label=out["label"])
    return out  # plaintext returned once


@app.delete("/api/keys/{key_prefix}")
def revoke_key(key_prefix: str, principal: Principal = Depends(require_role("admin"))) -> dict:
    ok = get_tenancy().revoke_api_key(principal.workspace_id, key_prefix)
    if not ok:
        raise HTTPException(404, "no such key in this workspace")
    get_tenancy().audit(principal.workspace_id, "api_key_revoked", actor=principal.subject,
                        key_prefix=key_prefix)
    return {"revoked": True, "key_prefix": key_prefix}


@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(200, ge=1, le=1000),
                  principal: Principal = Depends(require_role("admin"))) -> dict:
    t = get_tenancy()
    return {"entries": t.list_audit(principal.workspace_id, limit=limit),
            "chain": t.verify_audit_chain(principal.workspace_id)}


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
