"""The single-page dashboard document.

`PAGE` is a fully self-contained HTML string: inline CSS + vanilla JS, no CDN
or external assets, no build step. The server serves it verbatim at GET /. All
data arrives over the small JSON API the server exposes; all server/user text
is escaped client-side via esc() before it touches the DOM.
"""

from __future__ import annotations

PAGE: str = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PromptPolygraph Dashboard</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --panel-2: #1d212b;
    --border: #2a2f3a;
    --text: #e6e9ef;
    --muted: #98a0ad;
    --accent: #6aa3ff;
    --pass: #46c08a;
    --fail: #e5736b;
    --warn: #e6b450;
    --row-hover: #20242f;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text); font-family: var(--sans);
    font-size: 14px; line-height: 1.5;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  header.top {
    display: flex; align-items: baseline; gap: 14px;
    padding: 14px 22px; border-bottom: 1px solid var(--border);
    background: var(--panel); position: sticky; top: 0; z-index: 10;
  }
  header.top h1 { font-size: 16px; margin: 0; letter-spacing: .3px; }
  header.top .sub { color: var(--muted); font-size: 12px; }
  header.top .spacer { flex: 1; }
  header.top .crumb { color: var(--muted); font-size: 13px; cursor: pointer; }
  header.top .crumb:hover { color: var(--text); }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 22px; }

  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .4px; }
  tbody.runs tr { cursor: pointer; }
  tbody.runs tr:hover { background: var(--row-hover); }
  td.mono, .mono { font-family: var(--mono); font-size: 12px; }

  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
          font-weight: 600; border: 1px solid var(--border); color: var(--muted); }
  .pill.pass { color: var(--pass); border-color: rgba(70,192,138,.4); background: rgba(70,192,138,.08); }
  .pill.fail { color: var(--fail); border-color: rgba(229,115,107,.4); background: rgba(229,115,107,.08); }
  .pill.neutral { color: var(--muted); }

  .prog { width: 120px; height: 8px; background: var(--panel-2); border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
  .prog > i { display: block; height: 100%; background: var(--accent); }

  .statband { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0 24px; }
  .stat { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
          padding: 12px 16px; min-width: 120px; flex: 1; }
  .stat .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
  .stat .v { font-size: 20px; font-weight: 700; margin-top: 4px; }
  .stat .v.pass { color: var(--pass); }
  .stat .v.fail { color: var(--fail); }

  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 4px 0; margin-bottom: 22px; overflow: hidden; }
  .panel h2 { font-size: 14px; margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .panel .body { padding: 4px 0; }

  .tabs { display: flex; gap: 4px; margin: 18px 0 6px; border-bottom: 1px solid var(--border); }
  .tab { padding: 8px 16px; cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent; font-weight: 600; }
  .tab.active { color: var(--text); border-bottom-color: var(--accent); }

  details.cat { border-bottom: 1px solid var(--border); }
  details.cat > summary { cursor: pointer; padding: 11px 16px; display: flex; align-items: center; gap: 10px; list-style: none; }
  details.cat > summary::-webkit-details-marker { display: none; }
  details.cat > summary .chev { color: var(--muted); transition: transform .15s; }
  details.cat[open] > summary .chev { transform: rotate(90deg); }
  details.cat > summary .name { font-weight: 600; }
  details.cat > summary .count { color: var(--muted); font-size: 12px; }

  .case { padding: 12px 18px 16px 32px; border-top: 1px dashed var(--border); }
  .case .meta { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin-bottom: 8px; }
  .case .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .4px; margin: 10px 0 3px; }
  .case .prompt { white-space: pre-wrap; word-break: break-word; }
  .resp { background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
          padding: 10px 12px; max-height: 260px; overflow: auto; white-space: pre-wrap; word-break: break-word;
          font-family: var(--mono); font-size: 12.5px; }
  .dims { display: flex; flex-wrap: wrap; gap: 6px; }
  .dim { font-size: 12px; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--panel-2); }
  .dim b { font-weight: 700; }
  .dim.low b { color: var(--fail); }
  .dim.ok b { color: var(--pass); }
  .asserts { list-style: none; padding: 0; margin: 4px 0 0; }
  .asserts li { font-size: 12.5px; padding: 2px 0; }
  .asserts li .mk { font-weight: 700; margin-right: 6px; }
  .asserts li .mk.pass { color: var(--pass); }
  .asserts li .mk.fail { color: var(--fail); }
  .reason { color: var(--warn); font-size: 13px; margin-top: 8px; white-space: pre-wrap; }

  .btnrow { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 18px; }
  .btn { display: inline-block; padding: 7px 13px; border: 1px solid var(--border); border-radius: 8px;
         background: var(--panel); color: var(--text); cursor: pointer; font-size: 13px; }
  .btn:hover { background: var(--panel-2); text-decoration: none; }

  .empty { color: var(--muted); padding: 26px 16px; text-align: center; }
  .err { color: var(--fail); padding: 16px; }
  .muted { color: var(--muted); }
  .frust { margin: 4px 0 0; padding-left: 18px; }
  .frust li { font-size: 13px; padding: 1px 0; }
  .narr { white-space: pre-wrap; padding: 0 16px 14px; line-height: 1.6; }
  ol.changes { margin: 2px 16px 14px; padding-left: 20px; }
  ol.changes li { padding: 3px 0; }
  .persona-card { padding: 12px 16px; border-top: 1px solid var(--border); }
  .persona-card h3 { margin: 0 0 4px; font-size: 13.5px; }
</style>
</head>
<body>
<header class="top">
  <h1>PromptPolygraph</h1>
  <span class="sub">evaluation dashboard</span>
  <span class="spacer"></span>
  <span class="crumb" id="crumb" onclick="showRuns()">All runs</span>
</header>
<div class="wrap" id="app"><div class="empty">Loading…</div></div>

<script>
"use strict";

// ---- helpers ------------------------------------------------------------
function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function dash(v) { return (v === null || v === undefined || v === "") ? "&mdash;" : esc(v); }
function num(v, d) {
  if (v === null || v === undefined) return "&mdash;";
  d = (d === undefined) ? 1 : d;
  return Number(v).toFixed(d);
}
function pct(v) { return (v === null || v === undefined) ? "&mdash;" : (Number(v) * 100).toFixed(0) + "%"; }
function shortId(id) { return id ? esc(String(id).slice(0, 8)) : "&mdash;"; }
function fmtTime(t) {
  if (!t) return "&mdash;";
  const d = new Date(t);
  if (isNaN(d)) return esc(t);
  return esc(d.toLocaleString());
}
function passPill(p) {
  if (p === true) return '<span class="pill pass">PASS</span>';
  if (p === false) return '<span class="pill fail">FAIL</span>';
  return '<span class="pill neutral">&mdash;</span>';
}
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
  return await r.json();
}

// ---- state --------------------------------------------------------------
const app = document.getElementById("app");
const crumb = document.getElementById("crumb");
let pollTimer = null;
let view = "runs";          // "runs" | "detail"
let currentRunId = null;
let currentTab = "results"; // "results" | "audit"

function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

// ---- runs list ----------------------------------------------------------
async function showRuns() {
  view = "runs"; currentRunId = null; crumb.textContent = "All runs";
  stopPoll();
  await renderRuns();
  pollTimer = setInterval(() => { if (view === "runs") renderRuns(); }, 4000);
}

async function renderRuns() {
  let runs;
  try { runs = await getJSON("/api/runs"); }
  catch (e) { app.innerHTML = '<div class="err">Could not load runs: ' + esc(e.message) + '</div>'; return; }
  if (!runs.length) {
    app.innerHTML = '<div class="empty">No runs found yet. Produce one with <span class="mono">polygraph all …</span> and it will appear here.</div>';
    return;
  }
  let rows = "";
  for (const r of runs) {
    const done = r.completed_cases || 0, total = r.total_cases || 0;
    const frac = total ? Math.round(100 * done / total) : 0;
    rows += '<tr onclick="showRun(\'' + esc(r.run_id) + '\')">'
      + '<td class="mono">' + shortId(r.run_id) + '</td>'
      + '<td>' + dash(r.name) + '</td>'
      + '<td>' + dash(r.mode) + '</td>'
      + '<td>' + dash(r.adapter) + '</td>'
      + '<td><div style="display:flex;align-items:center;gap:8px">'
        + '<span class="prog"><i style="width:' + frac + '%"></i></span>'
        + '<span class="muted mono">' + done + '/' + total + '</span></div></td>'
      + '<td>' + passPill(r.overall_pass) + '</td>'
      + '<td class="muted">' + fmtTime(r.created_at) + '</td>'
      + '</tr>';
  }
  app.innerHTML =
    '<table><thead><tr><th>ID</th><th>Name</th><th>Mode</th><th>Adapter</th>'
    + '<th>Cases</th><th>Pass</th><th>Created</th></tr></thead>'
    + '<tbody class="runs">' + rows + '</tbody></table>';
}

// ---- run detail ---------------------------------------------------------
async function showRun(id) {
  view = "detail"; currentRunId = id; currentTab = "results";
  stopPoll();
  crumb.textContent = "All runs  ›  " + id.slice(0, 8);
  app.innerHTML = '<div class="empty">Loading run…</div>';
  let run, summary, cases;
  try {
    const meta = await getJSON("/api/runs/" + encodeURIComponent(id));
    run = meta.run || meta; summary = meta.summary || {};
    cases = await getJSON("/api/runs/" + encodeURIComponent(id) + "/cases");
  } catch (e) {
    app.innerHTML = '<div class="err">Could not load run: ' + esc(e.message) + '</div>'; return;
  }
  renderDetail(run, summary, cases);
}

function renderDetail(run, summary, cases) {
  const cost = summary.cost || {};
  const lat = summary.latency || {};
  const op = summary.overall_pass;
  let band = "";
  const stat = (k, vHtml, cls) =>
    '<div class="stat"><div class="k">' + esc(k) + '</div><div class="v ' + (cls || "") + '">' + vHtml + '</div></div>';
  band += stat("Overall", op === true ? "PASS" : (op === false ? "FAIL" : "&mdash;"),
               op === true ? "pass" : (op === false ? "fail" : ""));
  band += stat("Categories", (summary.categories_passing ?? "&mdash;") + " / " + (summary.categories_total ?? "&mdash;"));
  band += stat("Threshold", num(summary.threshold, 1));
  band += stat("Assertions", pct(summary.assertion_pass_rate));
  band += stat("Agreement", summary.agreement_mean == null ? "&mdash;" : num(summary.agreement_mean, 2));
  band += stat("Latency p50/p95", num(lat.p50_ms, 0) + " / " + num(lat.p95_ms, 0) + " ms");
  let costStr = (cost.usd == null ? "&mdash;" : "$" + Number(cost.usd).toFixed(4));
  band += stat("Cost", costStr + ' <span class="muted" style="font-size:12px">' + (cost.tokens_in || 0) + " in / " + (cost.tokens_out || 0) + " out</span>");

  const head =
    '<div style="margin-bottom:6px"><span style="font-size:18px;font-weight:700">' + dash(run.name) + '</span> '
    + '<span class="muted mono">' + shortId(run.run_id) + '</span></div>'
    + '<div class="muted" style="font-size:13px">' + dash(run.adapter) + ' · ' + dash(run.model) + ' · ' + dash(run.mode)
    + ' · created ' + fmtTime(run.created_at) + '</div>';

  const reportBtns =
    '<div class="btnrow">'
    + '<a class="btn" target="_blank" href="/api/runs/' + esc(run.run_id) + '/report?format=html">Report (HTML)</a>'
    + '<a class="btn" target="_blank" href="/api/runs/' + esc(run.run_id) + '/report?format=md">Report (Markdown)</a>'
    + '<a class="btn" href="/api/runs/' + esc(run.run_id) + '/report?format=pdf">Download PDF</a>'
    + '<a class="btn" href="/api/runs/' + esc(run.run_id) + '/report?format=docx">Download DOCX</a>'
    + '</div>';

  const tabs =
    '<div class="tabs">'
    + '<div class="tab' + (currentTab === "results" ? " active" : "") + '" onclick="switchTab(\'results\')">Results</div>'
    + '<div class="tab' + (currentTab === "audit" ? " active" : "") + '" onclick="switchTab(\'audit\')">Audit</div>'
    + '</div>';

  app.innerHTML = head + '<div class="statband">' + band + '</div>' + reportBtns + tabs
    + '<div id="tabbody"></div>';

  window.__detail = { run, summary, cases };
  if (currentTab === "results") renderResults(summary, cases);
  else renderAuditTab(run.run_id);
}

function switchTab(t) {
  currentTab = t;
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(el => {
    if (el.getAttribute("onclick").indexOf("'" + t + "'") >= 0) el.classList.add("active");
  });
  const d = window.__detail;
  if (t === "results") renderResults(d.summary, d.cases);
  else renderAuditTab(d.run.run_id);
}

// ---- results tab --------------------------------------------------------
function verdictRank(row) {
  // worst first: explicit fail < assertions failed < null < pass
  const s = row.score;
  if (!s) return 2;
  if (s.verdict_pass === false) return 0;
  if (s.assertions_passed === false) return 1;
  if (s.verdict_pass === true) return 3;
  return 2;
}

function renderResults(summary, cases) {
  const body = document.getElementById("tabbody");
  const dims = (summary.dimensions || []);
  const catScores = summary.category_scores || {};
  const thr = summary.threshold;

  // category-score table
  let cst = "";
  const catNames = Object.keys(catScores).sort();
  if (catNames.length) {
    let head = '<tr><th>Category</th>';
    for (const d of dims) head += '<th>' + esc(d) + '</th>';
    head += '<th>Pass</th></tr>';
    let rows = "";
    for (const cat of catNames) {
      const e = catScores[cat];
      let r = '<td>' + esc(cat) + ' <span class="muted">(' + (e.count || 0) + ')</span></td>';
      for (const d of dims) {
        const v = e[d];
        if (v === null || v === undefined) r += '<td class="muted">&mdash;</td>';
        else {
          const low = (thr != null && v < thr);
          r += '<td class="mono" style="color:' + (low ? "var(--fail)" : "var(--pass)") + '">' + num(v, 1) + '</td>';
        }
      }
      r += '<td>' + passPill(e.pass) + '</td>';
      rows += '<tr>' + r + '</tr>';
    }
    cst = '<div class="panel"><h2>Category scores</h2><div class="body">'
      + '<table><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div></div>';
  }

  // group cases by category
  const groups = {};
  for (const row of cases) {
    const cat = (row.case && row.case.category) || "default";
    (groups[cat] = groups[cat] || []).push(row);
  }
  let sections = "";
  const gnames = Object.keys(groups).sort();
  if (!gnames.length) sections = '<div class="empty">No cases recorded for this run.</div>';
  for (const cat of gnames) {
    const rows = groups[cat].slice().sort((a, b) => verdictRank(a) - verdictRank(b));
    let inner = "";
    for (const row of rows) inner += renderCase(row, dims, thr);
    sections += '<details class="cat"><summary>'
      + '<span class="chev">▶</span><span class="name">' + esc(cat) + '</span>'
      + '<span class="count">' + rows.length + ' case' + (rows.length === 1 ? "" : "s") + '</span>'
      + '</summary>' + inner + '</details>';
  }
  body.innerHTML = cst + '<div class="panel"><h2>Cases by category</h2>' + sections + '</div>';
}

function renderCase(row, dims, thr) {
  const c = row.case || {}, resp = row.response, s = row.score;
  let metaBits = passPill(s ? s.verdict_pass : null);
  if (c.subcategory) metaBits += ' <span class="muted mono">' + esc(c.subcategory) + '</span>';
  if (resp && resp.error) metaBits += ' <span class="pill fail">error</span>';

  let html = '<div class="case"><div class="meta">' + metaBits + '</div>';
  html += '<div class="label">Prompt</div><div class="prompt">' + dash(c.prompt) + '</div>';
  if (c.expected_behavior) html += '<div class="label">Expected behavior</div><div>' + esc(c.expected_behavior) + '</div>';
  if (c.red_flags && c.red_flags.length)
    html += '<div class="label">Red flags</div><div class="muted">' + c.red_flags.map(esc).join(", ") + '</div>';

  html += '<div class="label">Response</div>';
  if (resp && resp.error) html += '<div class="resp" style="color:var(--fail)">' + esc(resp.error) + '</div>';
  else html += '<div class="resp">' + (resp ? dash(resp.text) : '<span class="muted">&mdash; no response</span>') + '</div>';

  if (s && s.dimensions && Object.keys(s.dimensions).length) {
    html += '<div class="label">Scores</div><div class="dims">';
    for (const d of (dims.length ? dims : Object.keys(s.dimensions))) {
      const v = s.dimensions[d];
      if (v === null || v === undefined) {
        html += '<span class="dim muted">' + esc(d) + ' &mdash;</span>';
      } else {
        const cls = (thr != null && v < thr) ? "low" : "ok";
        html += '<span class="dim ' + cls + '">' + esc(d) + ' <b>' + v + '</b></span>';
      }
    }
    html += '</div>';
  }

  if (s && s.assertions && s.assertions.length) {
    html += '<div class="label">Assertions</div><ul class="asserts">';
    for (const a of s.assertions) {
      const mk = a.passed ? '<span class="mk pass">✓</span>' : '<span class="mk fail">✗</span>';
      const desc = a.description || a.kind || "assertion";
      let line = mk + esc(desc);
      if (a.detail) line += ' <span class="muted">— ' + esc(a.detail) + '</span>';
      html += '<li>' + line + '</li>';
    }
    html += '</ul>';
  }

  if (s && s.failure_reason) html += '<div class="reason">⚠ ' + esc(s.failure_reason) + '</div>';
  if (s && s.notes) html += '<div class="muted" style="font-size:12.5px;margin-top:6px">' + esc(s.notes) + '</div>';
  html += '</div>';
  return html;
}

// ---- audit tab ----------------------------------------------------------
async function renderAuditTab(runId) {
  const body = document.getElementById("tabbody");
  body.innerHTML = '<div class="empty">Loading audit…</div>';
  let audit;
  try { audit = await getJSON("/api/runs/" + encodeURIComponent(runId) + "/audit"); }
  catch (e) {
    body.innerHTML = '<div class="empty">No audit available for this run.</div>'; return;
  }
  if (!audit || (!audit.persona && !audit.forensic)) {
    body.innerHTML = '<div class="empty">No audit available for this run.</div>'; return;
  }
  let html = "";
  const f = audit.forensic || {};
  const syn = f.synthesis || {};

  // forensic synthesis
  let syHtml = "";
  if (syn.cross_category_patterns && syn.cross_category_patterns.length) {
    syHtml += '<div class="label" style="padding:10px 16px 0">Cross-category patterns</div><ul class="frust" style="margin:0 16px">';
    syHtml += syn.cross_category_patterns.map(p => '<li>' + esc(p) + '</li>').join("");
    syHtml += '</ul>';
  }
  if (syn.prioritized_changes && syn.prioritized_changes.length) {
    syHtml += '<div class="label" style="padding:10px 16px 0">Prioritized changes</div><ol class="changes">';
    syHtml += syn.prioritized_changes.map(p => '<li>' + esc(typeof p === "string" ? p : (p.change || JSON.stringify(p))) + '</li>').join("");
    syHtml += '</ol>';
  }
  if (syn.closest_to_pass)
    syHtml += '<div class="label" style="padding:6px 16px 0">Closest to pass</div><div style="padding:0 16px 8px">' + esc(syn.closest_to_pass) + '</div>';
  if (syn.narrative)
    syHtml += '<div class="label" style="padding:6px 16px 0">Narrative</div><div class="narr">' + esc(syn.narrative) + '</div>';
  if (syHtml) html += '<div class="panel"><h2>Forensic synthesis</h2><div class="body">' + syHtml + '</div></div>';

  // per-category forensic audits
  const cas = f.category_audits || [];
  if (cas.length) {
    let secs = "";
    for (const ca of cas) {
      let inner = "";
      if (ca.highest_leverage_one_liner)
        inner += '<div class="case"><div class="label">Highest-leverage change</div><div>' + esc(ca.highest_leverage_one_liner) + '</div>';
      else inner += '<div class="case">';
      if (ca.gap_dims && ca.gap_dims.length)
        inner += '<div class="label">Gap dimensions</div><div class="muted">' + ca.gap_dims.map(esc).join(", ") + '</div>';
      if (ca.failure_modes && ca.failure_modes.length)
        inner += '<div class="label">Failure modes</div><ul class="frust">' + ca.failure_modes.map(x => '<li>' + esc(typeof x === "string" ? x : JSON.stringify(x)) + '</li>').join("") + '</ul>';
      if (ca.leverage_changes && ca.leverage_changes.length)
        inner += '<div class="label">Leverage changes</div><ul class="frust">' + ca.leverage_changes.map(x => '<li>' + esc(typeof x === "string" ? x : JSON.stringify(x)) + '</li>').join("") + '</ul>';
      inner += '</div>';
      secs += '<details class="cat"><summary><span class="chev">▶</span><span class="name">' + esc(ca.category || "category") + '</span></summary>' + inner + '</details>';
    }
    html += '<div class="panel"><h2>Forensic — by category</h2>' + secs + '</div>';
  }

  // persona reactions
  const p = audit.persona || {};
  const reactions = p.reactions || [];
  if (reactions.length) {
    let cards = "";
    for (const pr of reactions) {
      let card = '<div class="persona-card"><h3>' + esc(pr.persona || "Persona") + '</h3>';
      if (pr.persona_summary) card += '<div class="muted" style="font-size:13px">' + esc(pr.persona_summary) + '</div>';
      if (pr.biggest_frustrations && pr.biggest_frustrations.length) {
        card += '<div class="label">Biggest frustrations</div><ul class="frust">'
          + pr.biggest_frustrations.map(x => '<li>' + esc(typeof x === "string" ? x : JSON.stringify(x)) + '</li>').join("") + '</ul>';
      }
      card += '</div>';
      cards += card;
    }
    html += '<div class="panel"><h2>Persona reactions</h2><div class="body">' + cards + '</div></div>';
  }

  if (!html) html = '<div class="empty">No audit available for this run.</div>';
  body.innerHTML = html;
}

// ---- boot ---------------------------------------------------------------
showRuns();
</script>
</body>
</html>
"""
