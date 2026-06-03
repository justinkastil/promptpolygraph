"""Server-rendered shell for the interactive dashboard.

`render_dashboard(store, settings) -> str` returns a single self-contained HTML
document (inline CSS + vanilla JS, no external assets, works offline). The shell
embeds a small amount of server context (title, auth flag, DB dialect) and then
fetches everything else client-side from the same-origin `/api` surface.
"""

from __future__ import annotations

import html
import json

from .db import SqlStore
from .settings import Settings


def render_dashboard(store: SqlStore, settings: Settings) -> str:
    title = html.escape(settings.title)
    dialect = html.escape(store.engine.dialect.name)
    # Server context handed to the client. Embedded as a JS object literal
    # inside the inline <script>. json.dumps gives valid JS; we only need to
    # neutralize sequences that could terminate the <script> element.
    ctx = {
        "title": settings.title,
        "authEnabled": bool(settings.auth_enabled),
        "dialect": store.engine.dialect.name,
    }
    ctx_js = (
        json.dumps(ctx)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    return _HTML.replace("__TITLE__", title).replace("__DIALECT__", dialect).replace(
        "__CTX__", ctx_js
    )


# A single self-contained document. No CDN, no build step. Placeholders
# (__TITLE__, __DIALECT__, __CTX__) are substituted in render_dashboard.
_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg:#0f1117; --panel:#171a23; --panel2:#1d212c; --border:#2a2f3c;
    --fg:#e6e9ef; --muted:#9aa3b2; --accent:#6d8bff; --accent2:#4ea3ff;
    --ok:#2ea043; --warn:#d29922; --bad:#f85149; --idle:#6e7681; --run:#3fb6d3;
    --chip:#222838;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:var(--bg); color:var(--fg); font-size:14px; line-height:1.45;
  }
  a { color:var(--accent2); text-decoration:none; }
  a:hover { text-decoration:underline; }
  header {
    display:flex; align-items:center; gap:1rem; padding:.75rem 1.25rem;
    background:var(--panel); border-bottom:1px solid var(--border); position:sticky; top:0; z-index:10;
    flex-wrap:wrap;
  }
  header h1 { font-size:1.05rem; margin:0; font-weight:650; letter-spacing:.2px; }
  header .meta { color:var(--muted); font-size:12px; }
  header .spacer { flex:1; }
  .key-field { display:flex; align-items:center; gap:.4rem; }
  .key-field input {
    background:var(--panel2); border:1px solid var(--border); color:var(--fg);
    padding:.35rem .55rem; border-radius:6px; font-size:12px; width:170px;
  }
  button {
    background:var(--accent); color:#fff; border:none; padding:.4rem .7rem;
    border-radius:6px; font-size:12.5px; cursor:pointer; font-weight:550;
  }
  button:hover { filter:brightness(1.08); }
  button.ghost { background:var(--panel2); color:var(--fg); border:1px solid var(--border); }
  button.danger { background:var(--bad); }
  button:disabled { opacity:.5; cursor:not-allowed; }
  main { padding:1.25rem; max-width:1500px; margin:0 auto; }
  .grid { display:grid; grid-template-columns:340px 1fr; gap:1.25rem; align-items:start; }
  @media (max-width:980px){ .grid { grid-template-columns:1fr; } }
  .card {
    background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:1rem; margin-bottom:1.25rem;
  }
  .card h2 { font-size:.92rem; margin:0 0 .8rem; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }
  label { display:block; font-size:11.5px; color:var(--muted); margin:.55rem 0 .2rem; text-transform:uppercase; letter-spacing:.4px; }
  input[type=text], input[type=number], select, textarea {
    width:100%; background:var(--panel2); border:1px solid var(--border); color:var(--fg);
    padding:.4rem .55rem; border-radius:6px; font-size:13px; font-family:inherit;
  }
  .row2 { display:grid; grid-template-columns:1fr 1fr; gap:.55rem; }
  .checkline { display:flex; align-items:center; gap:.4rem; margin-top:.6rem; font-size:13px; color:var(--fg); }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th, td { text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--border); vertical-align:middle; }
  th { color:var(--muted); font-weight:600; font-size:11.5px; text-transform:uppercase; letter-spacing:.4px; }
  tbody tr:hover { background:var(--panel2); }
  tr.clickable { cursor:pointer; }
  tr.selected { background:rgba(109,139,255,.12); }
  code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; }
  .pill {
    display:inline-flex; align-items:center; gap:.35rem; padding:.15rem .55rem;
    border-radius:999px; font-size:11px; font-weight:600; color:#fff; white-space:nowrap;
  }
  .dot { width:7px; height:7px; border-radius:50%; background:rgba(255,255,255,.85); }
  .pill.queued{background:var(--idle);} .pill.running{background:var(--run);}
  .pill.done{background:var(--ok);} .pill.failed{background:var(--bad);} .pill.canceled{background:#444b5a;}
  .pill.unknown{background:#555;}
  .bar { background:var(--panel2); border-radius:6px; height:9px; width:120px; overflow:hidden; border:1px solid var(--border); }
  .bar > span { display:block; height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); }
  .passmark { font-weight:700; }
  .passmark.yes { color:var(--ok); } .passmark.no { color:var(--bad); } .passmark.na { color:var(--muted); }
  .stage { color:var(--muted); font-size:11px; }
  .actions { display:flex; gap:.35rem; }
  .actions button { padding:.25rem .5rem; font-size:11px; }
  .banner {
    display:none; background:rgba(248,81,73,.15); border:1px solid var(--bad);
    color:#ffb3ae; padding:.6rem .9rem; border-radius:8px; margin-bottom:1rem; font-size:13px;
  }
  .banner.show { display:block; }
  .toast {
    position:fixed; bottom:1rem; right:1rem; background:var(--panel2); border:1px solid var(--border);
    padding:.6rem .9rem; border-radius:8px; font-size:13px; box-shadow:0 6px 24px rgba(0,0,0,.4);
    opacity:0; transform:translateY(8px); transition:.25s; pointer-events:none; max-width:380px;
  }
  .toast.show { opacity:1; transform:translateY(0); }
  .toast.err { border-color:var(--bad); color:#ffb3ae; }
  .empty { color:var(--muted); padding:1rem 0; font-style:italic; }
  .kv { display:grid; grid-template-columns:auto 1fr; gap:.2rem .8rem; font-size:13px; }
  .kv dt { color:var(--muted); }
  .kv dd { margin:0; }
  .statgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:.6rem; margin-bottom:1rem; }
  .stat { background:var(--panel2); border:1px solid var(--border); border-radius:8px; padding:.6rem .7rem; }
  .stat .n { font-size:1.15rem; font-weight:700; }
  .stat .l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }
  details { border:1px solid var(--border); border-radius:8px; margin-bottom:.7rem; background:var(--panel2); }
  details > summary { cursor:pointer; padding:.55rem .8rem; font-weight:600; font-size:13px; list-style:none; }
  details > summary::-webkit-details-marker { display:none; }
  details > summary::before { content:"\25B8"; margin-right:.5rem; color:var(--muted); }
  details[open] > summary::before { content:"\25BE"; }
  details .body { padding:0 .8rem .8rem; }
  .persona { border-bottom:1px solid var(--border); padding:.55rem 0; }
  .persona .who { font-weight:600; }
  .persona .focus { color:var(--muted); font-size:12.5px; }
  .tabbar { display:flex; gap:.4rem; margin-bottom:1rem; flex-wrap:wrap; }
  .tab { background:var(--panel2); border:1px solid var(--border); color:var(--muted); padding:.35rem .8rem; border-radius:6px; cursor:pointer; font-size:12.5px; }
  .tab.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  pre.json { background:#0b0d13; border:1px solid var(--border); border-radius:8px; padding:.7rem; overflow:auto; max-height:340px; font-size:11.5px; }
  .hint { color:var(--muted); font-size:11.5px; margin-top:.3rem; }
  .small { font-size:11.5px; color:var(--muted); }
</style>
</head>
<body>
<header>
  <h1 id="appTitle">__TITLE__</h1>
  <span class="meta">db: <code>__DIALECT__</code> · <span id="authState"></span> ·
    <a href="/healthz" target="_blank">status</a> · <a href="/docs" target="_blank">API</a></span>
  <span class="spacer"></span>
  <div class="key-field" id="keyField">
    <label style="margin:0;color:var(--muted)">API key</label>
    <input type="password" id="apiKey" placeholder="X-API-Key" autocomplete="off">
    <button class="ghost" id="saveKey">Save</button>
  </div>
</header>

<main>
  <div class="banner" id="authBanner">Unauthorized (401). Paste a valid API key in the header and click Save.</div>

  <div class="tabbar">
    <div class="tab active" data-tab="overview">Overview</div>
    <div class="tab" data-tab="personas">Personas</div>
    <div class="tab" data-tab="compare">Compare A/B</div>
  </div>

  <!-- OVERVIEW TAB -->
  <section data-panel="overview">
    <div class="grid">
      <div>
        <div class="card">
          <h2>Trigger run</h2>
          <form id="runForm">
            <label>Config name</label>
            <input type="text" id="f_config_name" placeholder="default">
            <div class="row2">
              <div>
                <label>Mode</label>
                <select id="f_mode">
                  <option value="">(config default)</option>
                  <option value="fixed">fixed</option>
                  <option value="varied">varied</option>
                  <option value="adversarial">adversarial</option>
                  <option value="hybrid">hybrid</option>
                </select>
              </div>
              <div>
                <label>Difficulty</label>
                <input type="text" id="f_difficulty" placeholder="e.g. hard">
              </div>
            </div>
            <div class="row2">
              <div>
                <label>Count</label>
                <input type="number" id="f_count" min="1" placeholder="">
              </div>
              <div>
                <label>Per category</label>
                <input type="number" id="f_per_category" min="1" placeholder="">
              </div>
            </div>
            <label>Categories (comma-separated)</label>
            <input type="text" id="f_categories" placeholder="reasoning, safety">
            <div class="row2">
              <div>
                <label>Judges (comma-separated)</label>
                <input type="text" id="f_judges" placeholder="judge-a, judge-b">
              </div>
              <div>
                <label>Concurrency</label>
                <input type="number" id="f_concurrency" min="1" placeholder="">
              </div>
            </div>
            <label>Formats (comma-separated)</label>
            <input type="text" id="f_formats" placeholder="html, md">
            <label class="checkline"><input type="checkbox" id="f_mock"> Mock run (no live model calls)</label>
            <div style="margin-top:.9rem; display:flex; gap:.5rem;">
              <button type="submit" id="launchBtn">Launch run</button>
              <button type="button" class="ghost" id="refreshBtn">Refresh now</button>
            </div>
            <div class="hint">Leave dials blank to use the config defaults.</div>
          </form>
        </div>

        <div class="card">
          <h2>Jobs</h2>
          <div id="jobsBox"><div class="empty">No jobs.</div></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Runs <span class="small" id="runCount"></span></h2>
          <div style="overflow:auto">
            <table>
              <thead><tr>
                <th>Run</th><th>Mode</th><th>Status</th><th>Progress</th>
                <th>Pass</th><th>Created</th><th></th>
              </tr></thead>
              <tbody id="runsBody"><tr><td colspan="7" class="empty">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>

        <div class="card" id="detailCard">
          <h2>Run detail</h2>
          <div id="detailBox"><div class="empty">Select a run above to inspect its summary, report, and audit.</div></div>
        </div>
      </div>
    </div>
  </section>

  <!-- PERSONAS TAB -->
  <section data-panel="personas" style="display:none">
    <div class="card">
      <h2>Personas</h2>
      <div style="display:flex; gap:.5rem; margin-bottom:.8rem;">
        <button class="ghost" id="loadPersonas">Reload</button>
      </div>
      <div id="personaBox"><div class="empty">Not loaded.</div></div>
    </div>
  </section>

  <!-- COMPARE TAB -->
  <section data-panel="compare" style="display:none">
    <div class="card">
      <h2>Compare two runs (A/B)</h2>
      <div class="row2">
        <div><label>Run A id</label><input type="text" id="cmp_a" placeholder="run id"></div>
        <div><label>Run B id</label><input type="text" id="cmp_b" placeholder="run id"></div>
      </div>
      <div style="margin-top:.8rem"><button id="cmpBtn">Compare</button></div>
      <div id="cmpBox" style="margin-top:1rem"></div>
    </div>
  </section>
</main>

<div class="toast" id="toast"></div>

<script>
"use strict";
const CTX = __CTX__;
const KEY_LS = "promptpolygraph.apikey";

// ---------- helpers ----------
function esc(s){
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}
function shortId(id){ return id ? esc(String(id).slice(0,8)) : "—"; }
function fmtTime(t){
  if (!t) return "—";
  const d = new Date(t);
  if (isNaN(d)) return esc(t);
  return d.toLocaleString();
}
function num(v, digits){
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return esc(v);
  return digits === undefined ? String(n) : n.toFixed(digits);
}
function toast(msg, isErr){
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(()=>{ t.className = "toast"; }, 3500);
}
function getKey(){ return localStorage.getItem(KEY_LS) || ""; }

function showAuthBanner(show){
  document.getElementById("authBanner").classList.toggle("show", !!show);
}

async function api(path, opts){
  opts = opts || {};
  const headers = Object.assign({}, opts.headers || {});
  const k = getKey();
  if (k) headers["X-API-Key"] = k;
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, Object.assign({}, opts, { headers }));
  } catch (e) {
    throw new Error("network error: " + e.message);
  }
  if (res.status === 401 || res.status === 403){
    showAuthBanner(true);
    throw new Error("unauthorized");
  }
  showAuthBanner(false);
  if (!res.ok){
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch(_){}
    const err = new Error(detail); err.status = res.status; throw err;
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

// ---------- header / auth ----------
function initHeader(){
  document.getElementById("appTitle").textContent = CTX.title;
  document.title = CTX.title;
  const authState = document.getElementById("authState");
  const keyField = document.getElementById("keyField");
  if (CTX.authEnabled){
    authState.textContent = "auth: on";
    document.getElementById("apiKey").value = getKey();
  } else {
    authState.textContent = "auth: off";
    keyField.style.display = "none";
  }
  document.getElementById("saveKey").onclick = () => {
    const v = document.getElementById("apiKey").value.trim();
    if (v) localStorage.setItem(KEY_LS, v); else localStorage.removeItem(KEY_LS);
    showAuthBanner(false);
    toast("API key saved");
    refreshAll();
  };
}

// ---------- tabs ----------
function initTabs(){
  document.querySelectorAll(".tab").forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const which = tab.dataset.tab;
      document.querySelectorAll("section[data-panel]").forEach(s => {
        s.style.display = (s.dataset.panel === which) ? "" : "none";
      });
      if (which === "personas") loadPersonas();
    };
  });
}

// ---------- runs table ----------
let SELECTED = null;
function statusPill(status){
  const s = esc(status || "unknown");
  return `<span class="pill ${s}"><span class="dot"></span>${s}</span>`;
}
function passMark(p){
  if (p === true)  return '<span class="passmark yes">&#10003;</span>';
  if (p === false) return '<span class="passmark no">&#10007;</span>';
  return '<span class="passmark na">—</span>';
}
function progressCell(r){
  const total = r.total_cases || 0, done = r.completed_cases || 0;
  const pct = total ? Math.round(100*done/total) : (r.status === "done" ? 100 : 0);
  const stage = (r.progress && r.progress.stage) ? r.progress.stage : "";
  const stageHtml = (r.status === "running" && stage) ? `<div class="stage">${esc(stage)}</div>` : "";
  return `<div class="bar"><span style="width:${pct}%"></span></div>
          <div class="stage">${done}/${total || "?"}</div>${stageHtml}`;
}
function actionsCell(r){
  const id = esc(r.run_id);
  let html = `<button class="ghost" data-act="view" data-id="${id}">View</button>`;
  html += `<button class="ghost" data-act="report" data-id="${id}">Report</button>`;
  if (r.status === "queued" || r.status === "running")
    html += `<button class="danger" data-act="cancel" data-id="${id}">Cancel</button>`;
  return `<div class="actions">${html}</div>`;
}
async function refreshRuns(){
  let runs;
  try { runs = await api("/api/runs"); }
  catch(e){ if (e.message !== "unauthorized") toast("runs: " + e.message, true);
            document.getElementById("runsBody").innerHTML =
              `<tr><td colspan="7" class="empty">Could not load runs.</td></tr>`; return; }
  document.getElementById("runCount").textContent = runs.length ? `(${runs.length})` : "";
  if (!runs.length){
    document.getElementById("runsBody").innerHTML =
      `<tr><td colspan="7" class="empty">No runs yet — launch one on the left.</td></tr>`;
    return;
  }
  const rows = runs.map(r => {
    const sel = (r.run_id === SELECTED) ? " selected" : "";
    return `<tr class="clickable${sel}" data-id="${esc(r.run_id)}">
      <td><code>${shortId(r.run_id)}</code></td>
      <td>${esc(r.mode || "—")}</td>
      <td>${statusPill(r.status)}</td>
      <td>${progressCell(r)}</td>
      <td>${passMark(r.overall_pass)}</td>
      <td class="small">${fmtTime(r.created_at)}</td>
      <td>${actionsCell(r)}</td>
    </tr>`;
  }).join("");
  document.getElementById("runsBody").innerHTML = rows;

  document.querySelectorAll("#runsBody tr.clickable").forEach(tr => {
    tr.addEventListener("click", e => {
      if (e.target.closest("button")) return;
      selectRun(tr.dataset.id);
    });
  });
  document.querySelectorAll("#runsBody button[data-act]").forEach(b => {
    b.addEventListener("click", () => doAction(b.dataset.act, b.dataset.id));
  });
}
function doAction(act, id){
  if (act === "view") return selectRun(id);
  if (act === "report") return window.open("/api/runs/" + encodeURIComponent(id) + "/report?format=html", "_blank");
  if (act === "cancel") return cancelRun(id);
}
async function cancelRun(id){
  if (!confirm("Cancel run " + id.slice(0,8) + "?")) return;
  try { await api("/api/runs/" + encodeURIComponent(id) + "/cancel", { method:"POST" });
        toast("Cancel requested"); refreshRuns(); }
  catch(e){ toast("cancel: " + e.message, true); }
}

// ---------- run detail ----------
async function selectRun(id){
  SELECTED = id;
  document.querySelectorAll("#runsBody tr.clickable").forEach(tr =>
    tr.classList.toggle("selected", tr.dataset.id === id));
  const box = document.getElementById("detailBox");
  box.innerHTML = `<div class="empty">Loading detail for <code>${shortId(id)}</code>…</div>`;
  let summary = null, err = null;
  try { summary = await api("/api/runs/" + encodeURIComponent(id) + "/summary"); }
  catch(e){ err = e; }
  renderDetail(id, summary, err);
}
function renderDetail(id, s, err){
  const box = document.getElementById("detailBox");
  const reportUrl = "/api/runs/" + encodeURIComponent(id) + "/report?format=html";
  let head = `<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;margin-bottom:.8rem">
      <div>Run <code>${esc(id)}</code></div>
      <div class="actions">
        <a href="${reportUrl}" target="_blank"><button class="ghost">Open full report</button></a>
      </div></div>`;

  if (err){
    box.innerHTML = head + `<div class="empty">No summary available yet (${esc(err.message)}).</div>`
      + auditSection(id);
    wireAudit(id);
    return;
  }
  if (!s){ box.innerHTML = head + `<div class="empty">No summary.</div>`; return; }

  const dims = Array.isArray(s.dimensions) ? s.dimensions : [];
  const cats = s.category_scores || {};
  // stat band
  const cost = s.cost || {}, lat = s.latency || {};
  const stats = `<div class="statgrid">
    <div class="stat"><div class="n">${passMark(s.overall_pass)}</div><div class="l">Overall</div></div>
    <div class="stat"><div class="n">${num(s.categories_passing)}/${num(s.categories_total)}</div><div class="l">Cats pass</div></div>
    <div class="stat"><div class="n">${s.threshold!=null?num(s.threshold,2):"—"}</div><div class="l">Threshold</div></div>
    <div class="stat"><div class="n">${s.assertion_pass_rate!=null?(num(100*s.assertion_pass_rate,0)+"%"):"—"}</div><div class="l">Assertions</div></div>
    <div class="stat"><div class="n">${s.agreement_mean!=null?num(s.agreement_mean,2):"—"}</div><div class="l">Agreement</div></div>
    <div class="stat"><div class="n">${num(lat.p50_ms,0)}/${num(lat.p95_ms,0)}</div><div class="l">Lat p50/p95 ms</div></div>
    <div class="stat"><div class="n">$${num(cost.usd,4)}</div><div class="l">Cost</div></div>
    <div class="stat"><div class="n">${num(cost.tokens_in)}/${num(cost.tokens_out)}</div><div class="l">Tokens in/out</div></div>
  </div>`;

  // category table
  let table = `<div class="empty">No category scores.</div>`;
  const catNames = Object.keys(cats);
  if (catNames.length){
    const dimHead = dims.map(d => `<th>${esc(d)}</th>`).join("");
    const rows = catNames.map(name => {
      const c = cats[name] || {};
      const dimCells = dims.map(d => {
        const v = c[d];
        return `<td>${v==null?'<span class="passmark na">—</span>':num(v,2)}</td>`;
      }).join("");
      return `<tr><td>${esc(name)}</td><td class="small">${num(c.count)}</td>${dimCells}<td>${passMark(c.pass)}</td></tr>`;
    }).join("");
    table = `<div style="overflow:auto"><table>
      <thead><tr><th>Category</th><th>n</th>${dimHead}<th>Pass</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }

  box.innerHTML = head + stats + table + auditSection(id);
  wireAudit(id);
}

function auditSection(id){
  return `
  <details style="margin-top:1rem"><summary>Audit (personas + forensic synthesis)</summary>
    <div class="body" id="auditBody-${esc(id)}"><div class="empty">Click to load…</div></div>
  </details>`;
}
function wireAudit(id){
  const det = document.querySelector(`#auditBody-${CSS.escape(id)}`)?.closest("details");
  if (!det) return;
  det.addEventListener("toggle", async () => {
    if (!det.open || det._loaded) return;
    det._loaded = true;
    const body = document.getElementById("auditBody-" + id);
    try {
      const a = await api("/api/runs/" + encodeURIComponent(id) + "/audit");
      body.innerHTML = renderAudit(a);
    } catch(e){
      det._loaded = false;
      body.innerHTML = `<div class="empty">No audit for this run (${esc(e.message)}).</div>`;
    }
  });
}
function renderAudit(a){
  a = a || {};
  let out = "";
  const persona = a.persona || {};
  const reactions = persona.reactions;
  if (reactions){
    out += `<h2 style="margin-top:.4rem">Persona reactions</h2>`;
    if (Array.isArray(reactions)){
      out += reactions.map(r => {
        const who = r.who || r.persona || r.id || "persona";
        const txt = r.reaction || r.text || r.comment || JSON.stringify(r);
        return `<div class="persona"><div class="who">${esc(who)}</div><div class="focus">${esc(txt)}</div></div>`;
      }).join("");
    } else {
      out += `<pre class="json">${esc(JSON.stringify(reactions, null, 2))}</pre>`;
    }
  }
  if (persona.comparison){
    out += `<h2>Persona comparison</h2><pre class="json">${esc(JSON.stringify(persona.comparison, null, 2))}</pre>`;
  }
  const forensic = a.forensic || {};
  if (forensic.synthesis){
    out += `<h2>Forensic synthesis</h2>`;
    out += (typeof forensic.synthesis === "string")
      ? `<div class="focus">${esc(forensic.synthesis)}</div>`
      : `<pre class="json">${esc(JSON.stringify(forensic.synthesis, null, 2))}</pre>`;
  }
  if (forensic.category_audits){
    out += `<h2>Category audits</h2><pre class="json">${esc(JSON.stringify(forensic.category_audits, null, 2))}</pre>`;
  }
  return out || `<div class="empty">Audit present but empty.</div>`;
}

// ---------- jobs ----------
async function refreshJobs(){
  let jobs;
  try { jobs = await api("/api/jobs"); }
  catch(e){ if (e.message !== "unauthorized") {} return; }
  const box = document.getElementById("jobsBox");
  if (!jobs || !jobs.length){ box.innerHTML = `<div class="empty">No jobs.</div>`; return; }
  box.innerHTML = `<table><thead><tr><th>Run</th><th>Status</th><th>Try</th><th>When</th></tr></thead><tbody>` +
    jobs.slice(0,20).map(j => `<tr>
      <td><code>${shortId(j.run_id)}</code></td>
      <td>${statusPill(j.status)}</td>
      <td class="small">${num(j.attempts)}</td>
      <td class="small">${fmtTime(j.finished_at || j.started_at || j.created_at)}</td>
    </tr>${j.error ? `<tr><td colspan="4" class="small" style="color:var(--bad)">${esc(j.error)}</td></tr>` : ""}`).join("") +
    `</tbody></table>`;
}

// ---------- trigger form ----------
function csv(id){
  const v = document.getElementById(id).value.trim();
  if (!v) return undefined;
  return v.split(",").map(s => s.trim()).filter(Boolean);
}
function intVal(id){
  const v = document.getElementById(id).value.trim();
  if (!v) return undefined;
  const n = parseInt(v, 10); return isNaN(n) ? undefined : n;
}
function strVal(id){
  const v = document.getElementById(id).value.trim();
  return v || undefined;
}
function initForm(){
  document.getElementById("runForm").addEventListener("submit", async e => {
    e.preventDefault();
    const overrides = {};
    const mode = strVal("f_mode");        if (mode) overrides.mode = mode;
    const count = intVal("f_count");      if (count !== undefined) overrides.count = count;
    const pc = intVal("f_per_category");  if (pc !== undefined) overrides.per_category = pc;
    const cats = csv("f_categories");     if (cats) overrides.categories = cats;
    const diff = strVal("f_difficulty");  if (diff) overrides.difficulty = diff;
    const judges = csv("f_judges");       if (judges) overrides.judges = judges;
    const conc = intVal("f_concurrency"); if (conc !== undefined) overrides.concurrency = conc;

    const body = {};
    const cn = strVal("f_config_name");   if (cn) body.config_name = cn;
    if (Object.keys(overrides).length) body.overrides = overrides;
    if (document.getElementById("f_mock").checked) body.mock = true;
    const formats = csv("f_formats");     if (formats) body.formats = formats;

    const btn = document.getElementById("launchBtn");
    btn.disabled = true; btn.textContent = "Launching…";
    try {
      const r = await api("/api/runs", { method:"POST", body: JSON.stringify(body) });
      toast("Queued run " + (r.run_id ? r.run_id.slice(0,8) : ""));
      await refreshAll();
      if (r.run_id) selectRun(r.run_id);
    } catch(err){
      toast("launch: " + err.message, true);
    } finally {
      btn.disabled = false; btn.textContent = "Launch run";
    }
  });
  document.getElementById("refreshBtn").onclick = refreshAll;
}

// ---------- personas ----------
async function loadPersonas(){
  const box = document.getElementById("personaBox");
  box.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const ps = await api("/api/personas");
    if (!ps.length){ box.innerHTML = `<div class="empty">No personas.</div>`; return; }
    box.innerHTML = ps.map(p => `<div class="persona">
      <div class="who">${esc(p.who || p.id)} <span class="small">(${esc(p.id)})</span></div>
      <div class="focus">${esc(p.focus || "")}</div></div>`).join("");
  } catch(e){
    box.innerHTML = `<div class="empty">Could not load personas (${esc(e.message)}).</div>`;
  }
}
function initPersonas(){ document.getElementById("loadPersonas").onclick = loadPersonas; }

// ---------- compare ----------
function initCompare(){
  document.getElementById("cmpBtn").onclick = async () => {
    const a = document.getElementById("cmp_a").value.trim();
    const b = document.getElementById("cmp_b").value.trim();
    const box = document.getElementById("cmpBox");
    if (!a || !b){ box.innerHTML = `<div class="empty">Enter two run ids.</div>`; return; }
    box.innerHTML = `<div class="empty">Comparing…</div>`;
    try {
      const r = await api(`/api/compare?run_a=${encodeURIComponent(a)}&run_b=${encodeURIComponent(b)}`);
      let cat = "";
      if (r.by_category && Object.keys(r.by_category).length){
        cat = `<div style="overflow:auto;margin-top:.8rem"><table>
          <thead><tr><th>Category</th><th>detail</th></tr></thead><tbody>` +
          Object.entries(r.by_category).map(([k,v]) =>
            `<tr><td>${esc(k)}</td><td class="small mono">${esc(JSON.stringify(v))}</td></tr>`).join("") +
          `</tbody></table></div>`;
      }
      box.innerHTML = `<div class="statgrid">
        <div class="stat"><div class="n">${num(r.wins_a)}</div><div class="l">Wins A</div></div>
        <div class="stat"><div class="n">${num(r.wins_b)}</div><div class="l">Wins B</div></div>
        <div class="stat"><div class="n">${num(r.ties)}</div><div class="l">Ties</div></div>
      </div>` + cat;
    } catch(e){ box.innerHTML = `<div class="empty">Compare failed (${esc(e.message)}).</div>`; }
  };
}

// ---------- polling ----------
async function refreshAll(){ await Promise.all([refreshRuns(), refreshJobs()]); }
let POLL = null;
function startPolling(){
  if (POLL) clearInterval(POLL);
  POLL = setInterval(() => {
    if (document.hidden) return;
    refreshRuns(); refreshJobs();
  }, 3000);
}

// ---------- boot ----------
initHeader();
initTabs();
initForm();
initPersonas();
initCompare();
refreshAll();
startPolling();
</script>
</body>
</html>
"""
