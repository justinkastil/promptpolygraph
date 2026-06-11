"""The single-page dashboard document.

`PAGE` is a fully self-contained HTML string: inline CSS + vanilla JS, no CDN
or external assets, no build step. The server serves it verbatim at GET /. All
data arrives over the small JSON API the server exposes; all server/user text
is escaped client-side via esc() before it touches the DOM.
"""

from __future__ import annotations

from promptpolygraph.ui.chrome import (
    DESIGNER_DOCK_JS,
    THEME_CSS,
    designer_dock_html,
    header_html,
)

# The dashboard is assembled from the shared chrome (theme tokens + header bar)
# plus its own page-specific CSS and the SPA script. Splitting it this way keeps
# the dashboard and the Red-Team Arena pinned to one visual identity.
_HEAD = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>PromptPolygraph Dashboard</title>\n"
    "<style>" + THEME_CSS + r"""
  /* ── dashboard-specific layout / components (built on the shared tokens) ── */
  .wrap { max-width: 1180px; margin: 0 auto; padding: 22px; }

  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .4px; }
  tbody.runs tr { cursor: pointer; }
  tbody.runs tr:hover { background: var(--row-hover); }
  td.mono, .mono { font-family: var(--mono); font-size: 12px; }

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

  .frust { margin: 4px 0 0; padding-left: 18px; }
  .frust li { font-size: 13px; padding: 1px 0; }
  .narr { white-space: pre-wrap; padding: 0 16px 14px; line-height: 1.6; }
  ol.changes { margin: 2px 16px 14px; padding-left: 20px; }
  ol.changes li { padding: 3px 0; }
  .persona-card { padding: 13px 16px; border-top: 1px solid var(--border); }
  .persona-card:first-child { border-top: 0; }
  .persona-card h3 { margin: 0 0 5px; font-size: 13.5px; font-weight: 700; }

  .chart-card { padding: 14px 16px; }
  .chart-card .ctitle { font-size: 11px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; color: var(--muted); margin: 0 0 8px; }
  .chart-row { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; }
  .chart-row > div { flex: 1 1 320px; min-width: 280px; }
  .diff-block { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; margin: 6px 0 2px; overflow-x: auto; font-family: var(--mono); font-size: 12px; line-height: 1.5; }
  .diff-block .d-add { color: var(--pass); display: block; }
  .diff-block .d-del { color: var(--fail); display: block; }
  .diff-block .d-ctx { color: var(--text); display: block; }
  .diff-block .d-hdr { color: var(--muted); display: block; }
  .fix-card { border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 8px; padding: 10px 13px; margin: 8px 16px; background: var(--panel-2); }
  .fix-card .fix-head { font-weight: 700; }
  .locus { font-family: var(--mono); font-size: 12px; color: var(--accent); }
  .gap-chip { display: inline-block; background: rgba(229,115,107,.12); color: var(--fail); border: 1px solid rgba(229,115,107,.4); border-radius: 999px; padding: 1px 9px; font-size: 11px; font-weight: 600; margin: 0 4px 4px 0; }
  .lead-fix { background: var(--panel-2); border: 1px solid var(--border); border-top: 3px solid var(--accent); border-radius: 8px; padding: 10px 13px; margin: 8px 16px; }
  .lead-fix .lead-label { font-size: 10px; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; color: var(--accent); }
  .fm-list { list-style: none; padding: 0; margin: 4px 16px; }
  .fm-list li { padding: 4px 0; border-bottom: 1px dashed var(--border); }

  .cmpbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 8px 0 16px; }
  .cmpbar .hint { color: var(--muted); font-size: 12px; }
  .btn.disabled-btn { opacity: .5; cursor: default; pointer-events: none; }
  tbody.runs tr.sel { background: rgba(106,163,255,.12); }
  .sel-box { margin-right: 8px; }
  .delta-up { color: var(--pass); }
  .delta-down { color: var(--fail); }
  .matrix td.base { color: var(--muted); }
  .reglist { list-style: none; padding: 0; margin: 6px 0; }
  .reglist li { padding: 5px 0; border-bottom: 1px dashed var(--border); }
  .reglist .drop { color: var(--fail); font-weight: 700; font-family: var(--mono); }

  /* ── control plane (base header.top/.navtab/.field/.btn come from THEME_CSS) ── */
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--sp-4); padding: var(--sp-4) var(--sp-4) var(--sp-2); }
  .form-grid + .form-grid { padding-top: 0; }
  .checks { display: flex; flex-wrap: wrap; gap: 10px 16px; padding: 4px 0 2px; }
  .checks label { display: inline-flex; align-items: center; gap: 6px; color: var(--text); font-size: 13px; text-transform: none; letter-spacing: 0; cursor: pointer; }
  .checks label input { accent-color: var(--accent); }
  .btn.primary.disabled-btn { opacity: .5; }
  .launchbar { display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-3); padding: var(--sp-2) var(--sp-4) var(--sp-4); }
  .runprog { margin: 0 16px 16px; }
  .runprog .bigprog { height: 14px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .runprog .bigprog > i { display: block; height: 100%; background: var(--accent); transition: width .3s; }
  .stagerow { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0 6px; }
  .stagepip { font-size: 11px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
  .stagepip.active { color: var(--text); border-color: var(--accent); background: rgba(106,163,255,.12); }
  .stagepip.done { color: var(--pass); border-color: rgba(70,192,138,.4); }
  .stagepip.errpip { color: var(--fail); border-color: rgba(229,115,107,.4); }
  .filterbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 10px 16px; }
  .filterbar input[type=text], .filterbar select {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 7px; padding: 6px 9px; font-size: 13px; }
  table.explorer th { cursor: pointer; user-select: none; white-space: nowrap; }
  table.explorer th .arr { color: var(--accent); }
  table.explorer tbody tr { cursor: pointer; }
  table.explorer tbody tr:hover { background: var(--row-hover); }
  table.explorer td.p { max-width: 360px; }
  .diff-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .diff-pair .resp { max-height: 220px; }
  .diff-case { border: 1px solid var(--border); border-radius: 9px; padding: 10px 13px; margin: 10px 0; background: var(--panel); }
  .diff-case .dh { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .diff-case .dlt { font-family: var(--mono); font-weight: 700; }
  .mv-up { color: var(--pass); } .mv-down { color: var(--fail); } .mv-flat { color: var(--muted); }
  .persona-result { border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: var(--radius-sm); padding: 11px 14px; margin: 10px 16px; background: var(--panel-2); }
  .persona-result h3 { margin: 0 0 5px; font-size: 13.5px; font-weight: 700; }
  .filelist { list-style: none; padding: 0; margin: 4px 16px 12px; }
  .filelist li { padding: 9px 0; border-bottom: 1px dashed var(--border); display: flex; align-items: center; gap: 10px; }
  .filelist li:last-child { border-bottom: 0; }
  .tag-mono { font-family: var(--mono); font-size: 11.5px; color: var(--muted); word-break: break-all; }
  .subtabs { display: flex; gap: 4px; margin: 4px 0 18px; border-bottom: 1px solid var(--border); }
  .subtab { padding: 8px 16px; cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent; font-weight: 600; font-size: 13px; transition: color .14s, border-color .14s; }
  .subtab:hover { color: var(--text); }
  .subtab.active { color: var(--text); border-bottom-color: var(--accent); }
  .corpus-preview { max-height: 360px; overflow: auto; margin: 0 16px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg); }
  .corpus-preview .pgroup { border-bottom: 1px dashed var(--border); }
  .corpus-preview .pgroup:last-child { border-bottom: none; }
  .corpus-preview .pcat { font-size: var(--label-size); font-weight: 700; letter-spacing: var(--label-spacing); text-transform: uppercase; color: var(--muted); padding: 9px 13px 5px; }
  .corpus-preview .pitem { padding: 5px 13px 5px 22px; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.5; border-top: 1px dashed var(--border); }
  .corpus-summary { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 16px 4px; }
  .corpus-summary .cchip { font-size: 11.5px; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--panel-2); color: var(--text); }
  .corpus-summary .cchip b { color: var(--text); font-weight: 700; }
  .cg-stream { margin: 8px 16px 14px; }
  .cg-stream .cg-prog-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 7px; }
  .cg-stream .cg-prog-note { font-size: 12.5px; color: var(--text); font-weight: 600; }
  .cg-stream .cg-prog-count { font-size: 12px; color: var(--muted); font-family: var(--mono); margin-left: auto; }
  .cg-bar { height: 6px; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--border); overflow: hidden; }
  .cg-bar > i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .18s ease; }
  .cg-live { max-height: 300px; overflow: auto; margin-top: 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg); }
  .cg-live .cg-row { padding: 7px 13px; border-top: 1px dashed var(--border); white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.5; }
  .cg-live .cg-row:first-child { border-top: none; }
  .cg-live .cg-tag { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; color: var(--muted); margin-right: 8px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border); background: var(--panel-2); }
  .cg-live .empty { padding: 16px 13px; text-align: left; }
  .selpath { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 16px 12px; }
  .selpath .tag-mono { color: var(--accent); }

  /* ── New-run path toggle (pick existing vs build) ─────────────────────── */
  .nr-paths { display: flex; gap: 4px; margin: 0 16px 10px; border-bottom: 1px solid var(--border); }
  .nr-path { padding: 8px 16px; cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent; font-weight: 600; }
  .nr-path.active { color: var(--text); border-bottom-color: var(--accent); }

  /* ── config builder: custom-category chip editor ─────────────────────── */
  .catchips { display: flex; flex-wrap: wrap; gap: 6px; padding: 2px 0; }
  .catchip {
    display: inline-flex; align-items: center; gap: 4px; background: var(--panel-2);
    border: 1px solid var(--border); border-radius: 999px; padding: 3px 6px 3px 11px; font-size: 12.5px;
    transition: border-color .14s;
  }
  .catchip:focus-within { border-color: var(--accent); }
  .catchip input.catname {
    background: transparent; border: 0; color: var(--text); font: 12.5px var(--sans);
    min-width: 70px; width: auto; padding: 0; outline: none;
  }
  .catchip .catx {
    cursor: pointer; color: var(--muted); border: 0; background: transparent; font-size: 14px;
    line-height: 1; padding: 0 2px; transition: color .14s;
  }
  .catchip .catx:hover { color: var(--fail); }
  .catadd { display: inline-flex; gap: 8px; align-items: center; }
  .catadd input { background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 7px 10px; font-size: 13px; min-width: 160px;
    transition: border-color .14s, box-shadow .14s; }
  .catadd input:focus { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
  .builder-sec { border-top: 1px solid var(--border); padding: 16px 16px 10px; }
  .builder-sec > .bs-title { display: flex; align-items: baseline; gap: 8px; font-size: var(--label-size); font-weight: 700; letter-spacing: var(--label-spacing); text-transform: uppercase; color: var(--text); margin-bottom: 12px; }
  .builder-sec > .bs-title::before { content: ""; width: 3px; align-self: stretch; min-height: 12px; border-radius: 2px; background: var(--accent); opacity: .7; }
  .builder-sec > .bs-title .bs-note { font-weight: 600; letter-spacing: 0; text-transform: none; color: var(--muted); font-size: 11.5px; }

  /* helper microcopy under a field; ".opt" is an inline "optional" qualifier on a label */
  .field-hint { display: block; color: var(--muted); font-size: 11.5px; line-height: 1.45; margin-top: 2px; letter-spacing: 0; text-transform: none; font-weight: 400; }
  .field-hint b { color: var(--text); font-weight: 700; }
  .field label .opt { color: var(--muted-2, #6a7280); font-weight: 600; text-transform: none; letter-spacing: 0; font-size: 10.5px; }
  #nr-config-hint b { color: var(--accent); font-weight: 700; }

  /* the two New-Run paths read as a segmented choice rather than two loose tabs */
  .nr-paths { display: inline-flex; gap: 2px; margin: 12px 16px 10px; padding: 3px; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .nr-path { padding: 6px 16px; cursor: pointer; color: var(--muted); border-radius: 5px; border-bottom: 0; font-weight: 600; font-size: 13px; transition: background .14s, color .14s; }
  .nr-path:hover { color: var(--text); }
  .nr-path.active { color: var(--text); background: var(--panel-2); box-shadow: inset 0 0 0 1px var(--border); }

  /* launch bar: clear primary-vs-secondary hierarchy + a divider above it */
  .launchbar { border-top: 1px solid var(--border); margin-top: 4px; }
</style>
</head>
<body>
"""
)

# The dashboard body: shared header (in-page switchers, links=False) + the SPA.
# The shared AI Designer dock (context "Run config") is appended after the app
# container; it is a fixed-position element so its position in the DOM is moot.
_BODY = (
    r"""
<div class="wrap" id="app"><div class="empty">Loading…</div></div>
"""
    + designer_dock_html(context_label="Run config")
    + r"""
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
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  // parse JSON even on non-2xx so callers can surface {error}
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) {
    const msg = (data && (data.detail || data.error)) || ("HTTP " + r.status);
    throw new Error(msg);
  }
  return data;
}

// ---- provider / model dropdowns ----------------------------------------
// Sourced from GET /api/providers (cached once per page load). Each entry:
// {id,label,available,reason,needs_key,models,default_model,allow_custom,base_url?}.
const CUSTOM_OPT = "__custom__";
let _providersCache = null;
async function loadProviders() {
  if (_providersCache) return _providersCache;
  try { _providersCache = await getJSON("/api/providers"); }
  catch (e) { _providersCache = []; }
  if (!Array.isArray(_providersCache)) _providersCache = [];
  return _providersCache;
}
// Build provider + model <select>s. opts: {providerSel, modelSel, customInput,
// notice, preferLocal}. preferLocal picks ollama first when available.
async function initProviderSelects(opts) {
  const provEl = document.getElementById(opts.providerSel);
  const modelEl = document.getElementById(opts.modelSel);
  if (!provEl || !modelEl) return;
  const providers = await loadProviders();
  const noticeEl = opts.notice ? document.getElementById(opts.notice) : null;

  const anyAvailable = providers.some(p => p.available);
  if (!providers.length || !anyAvailable) {
    // Empty state: nothing configured. Surface the inline notice; leave the
    // selects populated (disabled) so the form still reads sensibly.
    if (noticeEl) {
      noticeEl.innerHTML = '<div class="empty" style="padding:8px 16px;text-align:left">'
        + 'No providers configured — run <span class="mono">polygraph init</span>, set an API key, or start Ollama.'
        + '</div>';
    }
  } else if (noticeEl) {
    noticeEl.innerHTML = "";
  }

  // pick a default provider id
  let defId = "";
  if (opts.preferLocal) {
    const local = providers.find(p => p.id === "ollama" && p.available);
    if (local) defId = local.id;
  }
  if (!defId) { const a = providers.find(p => p.available); if (a) defId = a.id; }
  if (!defId && providers.length) defId = providers[0].id;

  provEl.innerHTML = providers.map(p => {
    const dis = p.available ? "" : " disabled";
    const why = p.available ? "" : (p.reason ? " — " + p.reason : " (unavailable)");
    const sel = (p.id === defId) ? " selected" : "";
    return '<option value="' + esc(p.id) + '"' + dis + sel + '>' + esc(p.label || p.id) + esc(why) + '</option>';
  }).join("");

  provEl.onchange = () => fillModelSelect(opts);
  fillModelSelect(opts);
}
function _providerById(id) { return (_providersCache || []).find(p => p.id === id) || null; }
function fillModelSelect(opts) {
  const provEl = document.getElementById(opts.providerSel);
  const modelEl = document.getElementById(opts.modelSel);
  const customEl = opts.customInput ? document.getElementById(opts.customInput) : null;
  if (!provEl || !modelEl) return;
  const p = _providerById(provEl.value);
  const models = (p && p.models) || [];
  const def = p && p.default_model;
  let html = models.map(m =>
    '<option value="' + esc(m) + '"' + (m === def ? " selected" : "") + '>' + esc(m) + '</option>').join("");
  if (!models.length) html = '<option value="">(provider default)</option>';
  if (p && p.allow_custom) html += '<option value="' + CUSTOM_OPT + '">custom…</option>';
  modelEl.innerHTML = html;
  modelEl.onchange = () => {
    if (customEl) customEl.style.display = (modelEl.value === CUSTOM_OPT) ? "" : "none";
  };
  if (customEl) customEl.style.display = "none";
}
function resolveProvider(providerSelId) {
  const el = document.getElementById(providerSelId);
  return (el && el.value) ? el.value : "";
}
function resolveModel(modelSelId, customInputId) {
  const el = document.getElementById(modelSelId);
  if (!el) return "";
  if (el.value === CUSTOM_OPT) {
    const c = customInputId ? document.getElementById(customInputId) : null;
    return (c && c.value || "").trim();
  }
  return el.value || "";
}

// ---- inline-SVG chart helpers ------------------------------------------
// All helpers return SVG strings. They are namespace-free (no xmlns) so the
// page contains no external/CDN URL of any kind; the browser renders inline
// SVG fine without the namespace. Numeric inputs are coerced; nulls render
// as neutral "no data" cells. Every text value is run through esc().
const CMAX = 10;
function _clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
function _hex2rgb(h) {
  h = (h || "").replace("#", "");
  if (h.length === 3) h = h.split("").map(c => c + c).join("");
  if (h.length !== 6) return [106, 163, 255];
  return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
}
function _lerp(a, b, t) {
  t = _clamp(t, 0, 1);
  const c = i => Math.round(a[i] + (b[i] - a[i]) * t).toString(16).padStart(2, "0");
  return "#" + c(0) + c(1) + c(2);
}
const _RED = [229,115,107], _AMBER = [230,180,80], _GREEN = [70,192,138];
function scoreColor(v, thr, vmax) {
  vmax = vmax || CMAX;
  if (v === null || v === undefined || isNaN(v)) return "#1d212b";
  thr = (thr && thr > 0) ? thr : vmax / 2;
  if (v <= thr) return _lerp(_RED, _AMBER, thr ? v / thr : 0);
  return _lerp(_AMBER, _GREEN, (v - thr) / ((vmax - thr) || 1));
}
function _txtOn(hex) {
  const [r,g,b] = _hex2rgb(hex);
  return (0.299*r + 0.587*g + 0.114*b) < 140 ? "#ffffff" : "#0f1115";
}
function _trunc(s, n) { s = String(s); return s.length <= n ? s : s.slice(0, n-1) + "…"; }
function _svgOpen(w, h, label) {
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" '
    + 'style="max-width:' + w + 'px;height:auto;font-family:var(--sans)" '
    + 'role="img" aria-label="' + esc(label) + '">';
}
function _noData(msg) {
  return _svgOpen(280, 54, msg) + '<rect width="280" height="54" rx="8" fill="#1d212b"/>'
    + '<text x="140" y="31" text-anchor="middle" font-size="12" fill="#98a0ad">' + esc(msg) + '</text></svg>';
}

// heatmap(rows, cols, valueFn, {threshold,vmax,accent}) -> SVG
function heatmap(rows, cols, valueFn, opt) {
  opt = opt || {};
  const thr = opt.threshold, vmax = opt.vmax || CMAX, accent = opt.accent || "#6aa3ff";
  if (!rows.length || !cols.length) return _noData("No scores");
  const labelW = 130, cellW = Math.max(58, Math.min(96, Math.floor(620 / cols.length))), cellH = 28, padTop = 50, gap = 3;
  const gridW = cols.length * (cellW + gap);
  const w = labelW + gridW + 12, h = padTop + rows.length * (cellH + gap) + 6;
  let s = _svgOpen(w, h, "Score heatmap");
  cols.forEach((c, j) => {
    const cx = labelW + j * (cellW + gap) + cellW / 2;
    s += '<text x="' + cx.toFixed(1) + '" y="' + (padTop - 30) + '" text-anchor="middle" font-size="11" font-weight="600" fill="#e6e9ef">' + esc(_trunc(c, 10)) + '</text>';
  });
  s += '<line x1="' + labelW + '" y1="' + (padTop - 8) + '" x2="' + (labelW + gridW) + '" y2="' + (padTop - 8) + '" stroke="' + esc(accent) + '" stroke-width="2"/>';
  rows.forEach((r, i) => {
    const ry = padTop + i * (cellH + gap);
    s += '<text x="' + (labelW - 10) + '" y="' + (ry + cellH/2 + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="#e6e9ef">' + esc(_trunc(r, 17)) + '</text>';
    cols.forEach((c, j) => {
      let v = valueFn(r, c);
      v = (v === null || v === undefined || v === "") ? null : Number(v);
      const rx = labelW + j * (cellW + gap);
      const fill = scoreColor(v, thr, vmax);
      const tcol = v === null ? "#98a0ad" : _txtOn(fill);
      const label = v === null ? "—" : v.toFixed(1);
      s += '<rect x="' + rx.toFixed(1) + '" y="' + ry.toFixed(1) + '" width="' + cellW + '" height="' + cellH + '" rx="4" fill="' + fill + '" stroke="#2a2f3a"/>'
        + '<text x="' + (rx + cellW/2).toFixed(1) + '" y="' + (ry + cellH/2 + 4).toFixed(1) + '" text-anchor="middle" font-size="11" font-weight="600" fill="' + tcol + '">' + label + '</text>';
    });
  });
  return s + "</svg>";
}

// barChart([{label,value,color?}], {vmax,threshold,accent}) -> SVG (horizontal)
function barChart(items, opt) {
  opt = opt || {};
  const vmax = opt.vmax || CMAX, thr = opt.threshold, accent = opt.accent || "#6aa3ff";
  items = (items || []).filter(x => x);
  if (!items.length) return _noData("No data");
  const labelW = 116, barW = 280, rowH = 24, padL = 10, padTop = 12;
  const w = padL + labelW + barW + 52, h = padTop + items.length * (rowH + 7) + 22;
  const trackX = padL + labelW;
  let s = _svgOpen(w, h, "Bar chart");
  if (thr != null) {
    const tx = trackX + barW * _clamp(thr / vmax, 0, 1);
    s += '<line x1="' + tx.toFixed(1) + '" y1="' + (padTop - 4) + '" x2="' + tx.toFixed(1) + '" y2="' + (h - 16) + '" stroke="#98a0ad" stroke-width="1" stroke-dasharray="3 3"/>'
      + '<text x="' + tx.toFixed(1) + '" y="' + (h - 4) + '" text-anchor="middle" font-size="9.5" fill="#98a0ad">thr ' + Number(thr).toFixed(1) + '</text>';
  }
  items.forEach((it, i) => {
    const y = padTop + i * (rowH + 7);
    const v = (it.value === null || it.value === undefined) ? null : Number(it.value);
    s += '<text x="' + (padL + labelW - 8) + '" y="' + (y + rowH/2 + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="#e6e9ef">' + esc(_trunc(it.label, 14)) + '</text>'
      + '<rect x="' + trackX + '" y="' + y + '" width="' + barW + '" height="' + rowH + '" rx="5" fill="#1d212b" stroke="#2a2f3a"/>';
    if (v !== null && !isNaN(v)) {
      const fw = barW * _clamp(v / vmax, 0, 1);
      const fill = it.color || scoreColor(v, thr, vmax);
      s += '<rect x="' + trackX + '" y="' + y + '" width="' + fw.toFixed(1) + '" height="' + rowH + '" rx="5" fill="' + fill + '"/>'
        + '<text x="' + (trackX + barW + 8) + '" y="' + (y + rowH/2 + 4).toFixed(1) + '" font-size="11" font-weight="600" fill="#e6e9ef">' + v.toFixed(1) + '</text>';
    } else {
      s += '<text x="' + (trackX + 8) + '" y="' + (y + rowH/2 + 4).toFixed(1) + '" font-size="11" fill="#98a0ad">—</text>';
    }
  });
  s += '<line x1="' + trackX + '" y1="' + (h - 16) + '" x2="' + (trackX + barW) + '" y2="' + (h - 16) + '" stroke="' + esc(accent) + '" stroke-width="1" opacity="0.35"/>';
  return s + "</svg>";
}

// lineChart([{label,points:[..],color?}], {vmax,threshold,xlabels?}) -> SVG
function lineChart(series, opt) {
  opt = opt || {};
  const vmax = opt.vmax || CMAX, thr = opt.threshold;
  const colors = ["#6aa3ff", "#46c08a", "#e6b450", "#c08adf", "#e5736b", "#5fd0c4"];
  series = (series || []).filter(s => s && s.points && s.points.length);
  if (!series.length) return _noData("No trend data");
  const nX = Math.max.apply(null, series.map(s => s.points.length));
  const padL = 40, padR = 14, padT = 12, padB = 28;
  const plotW = 420, plotH = 180;
  const w = padL + plotW + padR, h = padT + plotH + padB + (series.length > 1 ? 18 : 0);
  const xpos = i => nX === 1 ? padL + plotW/2 : padL + plotW * i / (nX - 1);
  const ypos = v => padT + plotH * (1 - _clamp(v / vmax, 0, 1));
  let s = _svgOpen(w, h, "Trend");
  [0, vmax/2, vmax].forEach(gv => {
    const gy = ypos(gv);
    s += '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (padL + plotW) + '" y2="' + gy.toFixed(1) + '" stroke="#2a2f3a" stroke-width="1"/>'
      + '<text x="' + (padL - 6) + '" y="' + (gy + 3).toFixed(1) + '" text-anchor="end" font-size="9.5" fill="#98a0ad">' + gv.toFixed(0) + '</text>';
  });
  if (thr != null) {
    const ty = ypos(thr);
    s += '<line x1="' + padL + '" y1="' + ty.toFixed(1) + '" x2="' + (padL + plotW) + '" y2="' + ty.toFixed(1) + '" stroke="#e6b450" stroke-width="1" stroke-dasharray="4 3"/>';
  }
  const xlabels = opt.xlabels || [];
  for (let i = 0; i < nX; i++) {
    s += '<text x="' + xpos(i).toFixed(1) + '" y="' + (padT + plotH + 16) + '" text-anchor="middle" font-size="9" fill="#98a0ad">' + esc(xlabels[i] != null ? xlabels[i] : (i + 1)) + '</text>';
  }
  series.forEach((ser, si) => {
    const col = ser.color || colors[si % colors.length];
    const coords = [];
    ser.points.forEach((v, i) => { if (v !== null && v !== undefined && !isNaN(v)) coords.push([xpos(i), ypos(Number(v))]); });
    if (coords.length >= 2) s += '<polyline points="' + coords.map(c => c[0].toFixed(1) + "," + c[1].toFixed(1)).join(" ") + '" fill="none" stroke="' + col + '" stroke-width="2.2"/>';
    coords.forEach(c => { s += '<circle cx="' + c[0].toFixed(1) + '" cy="' + c[1].toFixed(1) + '" r="3" fill="' + col + '"/>'; });
  });
  if (series.length > 1) {
    let lx = padL, ly = padT + plotH + padB + 6;
    series.forEach((ser, si) => {
      const col = ser.color || colors[si % colors.length];
      const lab = _trunc(ser.label || ("series " + (si + 1)), 14);
      s += '<rect x="' + lx + '" y="' + (ly - 9) + '" width="11" height="11" rx="2" fill="' + col + '"/>'
        + '<text x="' + (lx + 15) + '" y="' + ly + '" font-size="10" fill="#e6e9ef">' + esc(lab) + '</text>';
      lx += 30 + lab.length * 6;
    });
  }
  return s + "</svg>";
}

// radar([{name,axes:{key:val}}], axisDefs:[{key,label}], {vmax,accent}) -> SVG
function radar(seriesIn, axisDefs, opt) {
  opt = opt || {};
  const vmax = opt.vmax || CMAX;
  const colors = [opt.accent || "#6aa3ff", "#46c08a", "#e6b450", "#c08adf", "#e5736b", "#5fd0c4"];
  const series = (seriesIn || []).filter(p => p && p.axes);
  if (!series.length || !axisDefs.length) return _noData("No persona reactions");
  const n = axisDefs.length, cx = 165, cy = 158, radius = 104, w = 440, h = 350;
  const pt = (idx, frac) => {
    const ang = -Math.PI/2 + idx * (2*Math.PI/n);
    const rr = radius * _clamp(frac, 0, 1);
    return [cx + rr*Math.cos(ang), cy + rr*Math.sin(ang)];
  };
  let s = _svgOpen(w, h, "Persona radar");
  [0.25, 0.5, 0.75, 1].forEach(ring => {
    const pts = axisDefs.map((_, i) => pt(i, ring)).map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    s += '<polygon points="' + pts + '" fill="none" stroke="#2a2f3a" stroke-width="1"/>';
  });
  axisDefs.forEach((ax, i) => {
    const e = pt(i, 1), l = pt(i, 1.22);
    let anchor = "middle";
    if (l[0] < cx - 5) anchor = "end"; else if (l[0] > cx + 5) anchor = "start";
    s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + e[0].toFixed(1) + '" y2="' + e[1].toFixed(1) + '" stroke="#2a2f3a" stroke-width="1"/>'
      + '<text x="' + l[0].toFixed(1) + '" y="' + (l[1] + 4).toFixed(1) + '" text-anchor="' + anchor + '" font-size="10.5" font-weight="600" fill="#e6e9ef">' + esc(ax.label) + '</text>';
  });
  series.slice(0, 6).forEach((p, si) => {
    const col = colors[si % colors.length];
    const pts = axisDefs.map((ax, i) => { const v = p.axes[ax.key]; return pt(i, (v == null || isNaN(v)) ? 0 : Number(v)/vmax); });
    s += '<polygon points="' + pts.map(c => c[0].toFixed(1) + "," + c[1].toFixed(1)).join(" ") + '" fill="' + col + '" fill-opacity="0.14" stroke="' + col + '" stroke-width="2"/>';
    pts.forEach(c => { s += '<circle cx="' + c[0].toFixed(1) + '" cy="' + c[1].toFixed(1) + '" r="2.4" fill="' + col + '"/>'; });
  });
  let ly = 16;
  series.slice(0, 6).forEach((p, si) => {
    const col = colors[si % colors.length];
    s += '<rect x="' + (w - 132) + '" y="' + (ly - 9) + '" width="11" height="11" rx="2" fill="' + col + '"/>'
      + '<text x="' + (w - 117) + '" y="' + ly + '" font-size="10.5" fill="#e6e9ef">' + esc(_trunc(p.name, 16)) + '</text>';
    ly += 18;
  });
  return s + "</svg>";
}

// diff -> colored monospace HTML block
function diffBlock(diff) {
  const lines = String(diff).split("\n").map(ln => {
    let cls = "d-ctx";
    if (ln.startsWith("@@") || ln.startsWith("+++") || ln.startsWith("---")) cls = "d-hdr";
    else if (ln.startsWith("+")) cls = "d-add";
    else if (ln.startsWith("-")) cls = "d-del";
    return '<span class="' + cls + '">' + esc(ln) + '</span>';
  });
  return '<div class="diff-block">' + lines.join("") + '</div>';
}

// ---- state --------------------------------------------------------------
const app = document.getElementById("app");
const crumb = document.getElementById("crumb");
let pollTimer = null;
let view = "runs";          // "runs" | "detail" | "compare" | "newrun" | "studio"
let currentRunId = null;
let currentTab = "results"; // "results" | "audit"
let selectMode = false;     // compare-selection mode in the runs list
const selected = new Set(); // selected run ids for compare
let runsCache = [];         // last /api/runs payload (chronological metadata)
let launchProgressTimer = null; // poll timer for an in-flight launched run
let selectedPersonaPath = "";   // persona file fed into the New Run panel
let selectedCorpusPath = "";    // generated corpus dir fed into the New Run panel
let studioTab = "prompts";      // Studio sub-tab: "prompts" | "personas"
let lastCorpusResult = null;    // last corpus-stream result frame, for re-render
let corpusStream = null;        // live EventSource for the generator, or null when idle

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  closeCorpusStream();  // any view transition also abandons a live generator stream
}

function setNav(active) {
  document.querySelectorAll("#navtabs .navtab").forEach(el => el.classList.remove("active"));
  const el = document.getElementById("nav-" + active);
  if (el) el.classList.add("active");
}

// ---- runs list ----------------------------------------------------------
async function showRuns() {
  view = "runs"; currentRunId = null; crumb.textContent = "All runs";
  setNav("runs");
  stopPoll();
  await renderRuns();
  pollTimer = setInterval(() => { if (view === "runs") renderRuns(); }, 4000);
}

async function renderRuns() {
  let runs;
  try { runs = await getJSON("/api/runs"); }
  catch (e) { app.innerHTML = '<div class="err">Could not load runs: ' + esc(e.message) + '</div>'; return; }
  runsCache = runs;
  if (!runs.length) {
    app.innerHTML = '<div class="empty">No runs found yet. Produce one with <span class="mono">polygraph all …</span> and it will appear here.</div>';
    return;
  }
  let rows = "";
  for (const r of runs) {
    const done = r.completed_cases || 0, total = r.total_cases || 0;
    const frac = total ? Math.round(100 * done / total) : 0;
    const isSel = selected.has(r.run_id);
    const onclick = selectMode
      ? 'onclick="toggleSel(\'' + esc(r.run_id) + '\')"'
      : 'onclick="showRun(\'' + esc(r.run_id) + '\')"';
    const selCell = selectMode
      ? '<td><input type="checkbox" class="sel-box"' + (isSel ? " checked" : "") + '></td>'
      : '';
    rows += '<tr class="' + (isSel ? "sel" : "") + '" ' + onclick + '>'
      + selCell
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
  const selHead = selectMode ? '<th></th>' : '';
  const toggleLabel = selectMode ? "Cancel" : "Compare runs";
  const compareBtn = selectMode
    ? '<button class="btn' + (selected.size < 2 ? " disabled-btn" : "") + '" onclick="openCompare()">Compare ' + selected.size + ' selected</button>'
    : '';
  const bar = '<div class="cmpbar"><button class="btn" onclick="toggleSelectMode()">' + toggleLabel + '</button>'
    + compareBtn
    + (selectMode ? '<span class="hint">Pick 2 or more runs; the first selected is the baseline.</span>' : '')
    + '</div>';
  app.innerHTML = bar
    + '<table><thead><tr>' + selHead + '<th>ID</th><th>Name</th><th>Mode</th><th>Adapter</th>'
    + '<th>Cases</th><th>Pass</th><th>Created</th></tr></thead>'
    + '<tbody class="runs">' + rows + '</tbody></table>';
}

function toggleSelectMode() {
  selectMode = !selectMode;
  if (!selectMode) selected.clear();
  renderRuns();
}
function toggleSel(id) {
  if (selected.has(id)) selected.delete(id); else selected.add(id);
  renderRuns();
}

// ---- compare view -------------------------------------------------------
async function openCompare() {
  if (selected.size < 2) return;
  view = "compare";
  setNav("runs");
  stopPoll();
  crumb.textContent = "All runs  ›  Compare " + selected.size + " runs";
  app.innerHTML = '<div class="empty">Loading comparison…</div>';

  // chronological order from the runs list; first is baseline
  const order = runsCache
    .filter(r => selected.has(r.run_id))
    .slice()
    .sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
  // fall back to selection order if metadata lacks timestamps
  const ids = order.length ? order.map(r => r.run_id) : Array.from(selected);

  const cols = [];
  for (const id of ids) {
    let meta;
    try { meta = await getJSON("/api/runs/" + encodeURIComponent(id)); }
    catch (e) { continue; }
    const run = meta.run || {};
    cols.push({ id: id, name: run.name || id.slice(0, 8), summary: meta.summary || {} });
  }
  if (cols.length < 2) {
    app.innerHTML = '<div class="err">Could not load enough runs to compare.</div>'; return;
  }
  renderCompare(cols);
}

function renderCompare(cols) {
  const base = cols[0];
  // union of dimensions + categories across all runs
  const dimSet = [];
  const catSet = [];
  for (const c of cols) {
    for (const d of (c.summary.dimensions || [])) if (!dimSet.includes(d)) dimSet.push(d);
    for (const k of Object.keys(c.summary.category_scores || {})) if (!catSet.includes(k)) catSet.push(k);
  }
  catSet.sort();
  const thr = base.summary.threshold;

  const catMean = (sum, cat) => {
    const e = (sum.category_scores || {})[cat];
    if (!e) return null;
    const vals = (sum.dimensions || []).map(d => e[d]).filter(v => v != null).map(Number);
    return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
  };

  // (a) comparison matrix: categories × runs, cell mean colored by delta vs baseline
  let mhead = '<tr><th>Category</th>';
  for (const c of cols) mhead += '<th>' + esc(_trunc(c.name, 18)) + (c === base ? ' <span class="muted">(base)</span>' : '') + '</th>';
  mhead += '</tr>';
  let mrows = "";
  for (const cat of catSet) {
    const baseM = catMean(base.summary, cat);
    let r = '<td>' + esc(cat) + '</td>';
    for (const c of cols) {
      const m = catMean(c.summary, cat);
      if (m === null) { r += '<td class="muted">&mdash;</td>'; continue; }
      if (c === base) { r += '<td class="mono base">' + m.toFixed(1) + '</td>'; continue; }
      const delta = (baseM != null) ? (m - baseM) : null;
      let cell = m.toFixed(1);
      if (delta != null) {
        const cls = delta >= 0 ? "delta-up" : "delta-down";
        const sign = delta >= 0 ? "+" : "";
        cell += ' <span class="' + cls + '">(' + sign + delta.toFixed(1) + ')</span>';
      }
      r += '<td class="mono">' + cell + '</td>';
    }
    mrows += '<tr>' + r + '</tr>';
  }
  const matrix = '<div class="panel"><h2>Comparison matrix</h2><div class="body">'
    + '<table class="matrix"><thead>' + mhead + '</thead><tbody>' + mrows + '</tbody></table></div></div>';

  // (b) per-dimension trend lines across the chronological runs
  let trends = "";
  if (dimSet.length) {
    const xlabels = cols.map(c => _trunc(c.name, 8));
    let cards = "";
    for (const d of dimSet) {
      const pts = cols.map(c => {
        const e = (c.summary.category_scores || {});
        const vals = Object.values(e).map(x => x && x[d]).filter(v => v != null).map(Number);
        return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
      });
      cards += '<div class="chart-card"><p class="ctitle">' + esc(d) + '</p>'
        + lineChart([{ label: d, points: pts }], { threshold: thr, xlabels: xlabels }) + '</div>';
    }
    trends = '<div class="panel"><h2>Per-dimension trend</h2><div class="body chart-row">' + cards + '</div></div>';
  }

  // (c) regressions list: dims that dropped > 0.5 vs baseline in any later run
  const regs = [];
  for (let ci = 1; ci < cols.length; ci++) {
    const c = cols[ci];
    for (const cat of catSet) {
      const be = (base.summary.category_scores || {})[cat];
      const ce = (c.summary.category_scores || {})[cat];
      if (!be || !ce) continue;
      for (const d of dimSet) {
        const bv = be[d], cv = ce[d];
        if (bv == null || cv == null) continue;
        const drop = Number(bv) - Number(cv);
        if (drop > 0.5) {
          regs.push({ run: c.name, cat: cat, dim: d, from: Number(bv), to: Number(cv), drop: drop });
        }
      }
    }
  }
  regs.sort((a, b) => b.drop - a.drop);
  let regHtml;
  if (regs.length) {
    regHtml = '<ul class="reglist">' + regs.map(rg =>
      '<li><span class="drop">−' + rg.drop.toFixed(1) + '</span> '
      + esc(rg.dim) + ' in <b>' + esc(rg.cat) + '</b> '
      + '<span class="muted">(' + rg.from.toFixed(1) + ' → ' + rg.to.toFixed(1) + ' in ' + esc(_trunc(rg.run, 18)) + ')</span></li>'
    ).join("") + '</ul>';
  } else {
    regHtml = '<div class="muted" style="padding:6px 0">No dimension dropped more than 0.5 vs the baseline.</div>';
  }
  const regsPanel = '<div class="panel"><h2>Regressions vs baseline</h2><div class="body" style="padding:6px 16px">' + regHtml + '</div></div>';

  const headLine = '<div style="margin-bottom:10px"><span style="font-size:18px;font-weight:700">Comparing ' + cols.length + ' runs</span> '
    + '<span class="muted">baseline: ' + esc(_trunc(base.name, 24)) + '</span></div>';

  // (d) A/B case diff — only when exactly two runs are compared.
  let diffPanel = "";
  if (cols.length === 2) {
    diffPanel = '<div class="panel" id="casediff-panel"><h2>Case diff</h2>'
      + '<div class="body"><div class="filterbar">'
      + '<button class="btn" onclick="loadCaseDiff(\'' + esc(cols[0].id) + '\',\'' + esc(cols[1].id) + '\')">Load case-by-case diff</button>'
      + '<span class="hint">Side-by-side responses for every shared prompt, biggest score change first.</span>'
      + '</div><div id="casediff-body"></div></div></div>';
  }

  app.innerHTML = headLine + matrix + trends + regsPanel + diffPanel;
}

// ---- A/B case diff ------------------------------------------------------
function _scoreMean(s) {
  if (!s || !s.dimensions) return null;
  const vals = Object.values(s.dimensions).filter(v => v != null).map(Number).filter(v => !isNaN(v));
  return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
}

async function loadCaseDiff(idA, idB) {
  const body = document.getElementById("casediff-body");
  if (!body) return;
  body.innerHTML = '<div class="empty">Loading cases for both runs…</div>';
  let casesA, casesB;
  try {
    casesA = await getJSON("/api/runs/" + encodeURIComponent(idA) + "/cases");
    casesB = await getJSON("/api/runs/" + encodeURIComponent(idB) + "/cases");
  } catch (e) {
    body.innerHTML = '<div class="err">Could not load cases: ' + esc(e.message) + '</div>'; return;
  }
  // index run B by case_id, then by prompt text as a fallback
  const byId = {}, byPrompt = {};
  for (const r of casesB) {
    const c = r.case || {};
    if (c.id) byId[c.id] = r;
    if (c.prompt) byPrompt[c.prompt] = r;
  }
  const pairs = [];
  for (const ra of casesA) {
    const ca = ra.case || {};
    let rb = (ca.id && byId[ca.id]) || (ca.prompt && byPrompt[ca.prompt]) || null;
    if (!rb) continue;
    const ma = _scoreMean(ra.score), mb = _scoreMean(rb.score);
    const delta = (ma != null && mb != null) ? (mb - ma) : null;
    pairs.push({ a: ra, b: rb, ma: ma, mb: mb, delta: delta,
                 prompt: ca.prompt || (rb.case && rb.case.prompt) || "",
                 category: ca.category || (rb.case && rb.case.category) || "default" });
  }
  if (!pairs.length) {
    body.innerHTML = '<div class="empty">No shared prompts between these two runs.</div>'; return;
  }
  // sort by |delta| desc; nulls last
  pairs.sort((x, y) => {
    const ax = x.delta == null ? -1 : Math.abs(x.delta);
    const ay = y.delta == null ? -1 : Math.abs(y.delta);
    return ay - ax;
  });

  let html = '<div class="muted" style="padding:4px 16px">' + pairs.length + ' shared prompt' + (pairs.length === 1 ? "" : "s") + ' · run A vs run B</div>';
  for (const p of pairs) {
    let marker;
    if (p.delta == null) marker = '<span class="mv-flat">—</span>';
    else if (p.delta > 0.05) marker = '<span class="mv-up">▲ improved</span>';
    else if (p.delta < -0.05) marker = '<span class="mv-down">▼ regressed</span>';
    else marker = '<span class="mv-flat">▬ flat</span>';
    const dStr = p.delta == null ? "&mdash;" : ((p.delta >= 0 ? "+" : "") + p.delta.toFixed(2));
    const dCls = p.delta == null ? "mv-flat" : (p.delta > 0.05 ? "mv-up" : (p.delta < -0.05 ? "mv-down" : "mv-flat"));
    const ta = (p.a.response ? (p.a.response.text || "") : "");
    const tb = (p.b.response ? (p.b.response.text || "") : "");
    html += '<div class="diff-case" style="margin-left:16px;margin-right:16px"><div class="dh">'
      + '<span class="dlt ' + dCls + '">Δ ' + dStr + '</span> ' + marker
      + ' <span class="muted mono">' + esc(p.category) + '</span>'
      + ' <span class="muted">A: ' + num(p.ma, 1) + ' → B: ' + num(p.mb, 1) + '</span></div>';
    html += '<div class="label">Prompt</div><div class="prompt">' + dash(p.prompt) + '</div>';
    html += '<div class="diff-pair" style="margin-top:8px">'
      + '<div><div class="label">Run A response</div><div class="resp">' + (ta ? esc(ta) : '<span class="muted">&mdash;</span>') + '</div></div>'
      + '<div><div class="label">Run B response</div><div class="resp">' + (tb ? esc(tb) : '<span class="muted">&mdash;</span>') + '</div></div>'
      + '</div></div>';
  }
  body.innerHTML = html;
}

// ---- run detail ---------------------------------------------------------
async function showRun(id) {
  view = "detail"; currentRunId = id; currentTab = "results";
  setNav("runs");
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
    + '<a class="btn" href="/api/runs/' + esc(run.run_id) + '/corpus?format=json">Export corpus (JSON)</a>'
    + '<a class="btn" href="/api/runs/' + esc(run.run_id) + '/corpus?format=csv">Corpus (CSV)</a>'
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

  // heatmap (categories × dimensions)
  let heat = "";
  const heatCats = Object.keys(catScores).sort();
  if (heatCats.length && dims.length) {
    const hm = heatmap(heatCats, dims, (cat, d) => {
      const e = catScores[cat]; return e ? e[d] : null;
    }, { threshold: thr });
    const bars = barChart(dims.map(d => {
      const vals = heatCats.map(c => catScores[c] && catScores[c][d]).filter(v => v != null).map(Number);
      const m = vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
      return { label: d, value: m };
    }), { threshold: thr });
    heat = '<div class="panel"><h2>Score heatmap</h2><div class="body chart-row">'
      + '<div class="chart-card"><p class="ctitle">Category × dimension</p>' + hm + '</div>'
      + '<div class="chart-card"><p class="ctitle">Mean by dimension</p>' + bars + '</div>'
      + '</div></div>';
  }

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

  // case explorer — searchable / sortable / filterable flat table
  const explorer = '<div class="panel"><h2>Case explorer</h2><div class="body" id="explorer-body"></div></div>';

  body.innerHTML = heat + cst + explorer + '<div class="panel"><h2>Cases by category</h2>' + sections + '</div>';
  renderExplorer(cases, dims, thr);
}

// ---- case explorer ------------------------------------------------------
function _verdictLabel(s) {
  if (!s) return "ungraded";
  if (s.verdict_pass === true) return "pass";
  if (s.verdict_pass === false) return "fail";
  if (s.assertions_passed === false) return "assert-fail";
  return "ungraded";
}

function renderExplorer(cases, dims, thr) {
  const host = document.getElementById("explorer-body");
  if (!host) return;
  window.__explorer = { cases: cases, dims: dims, thr: thr, sortKey: "category", sortDir: 1, q: "", verdict: "", category: "" };
  const cats = Array.from(new Set(cases.map(r => (r.case && r.case.category) || "default"))).sort();
  const catOpts = ['<option value="">All categories</option>']
    .concat(cats.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>')).join("");
  const verdOpts = '<option value="">All verdicts</option>'
    + '<option value="pass">Pass</option><option value="fail">Fail</option>'
    + '<option value="assert-fail">Assertions failed</option><option value="ungraded">Ungraded</option>';
  host.innerHTML =
    '<div class="filterbar">'
    + '<input type="text" id="exp-q" placeholder="Search prompt / response / category…" oninput="explorerUpdate()" style="flex:1;min-width:200px">'
    + '<select id="exp-verdict" onchange="explorerUpdate()">' + verdOpts + '</select>'
    + '<select id="exp-cat" onchange="explorerUpdate()">' + catOpts + '</select>'
    + '<span class="hint" id="exp-count"></span>'
    + '</div><div id="exp-table"></div>';
  drawExplorerTable();
}

function explorerUpdate() {
  const st = window.__explorer; if (!st) return;
  st.q = (document.getElementById("exp-q").value || "").toLowerCase();
  st.verdict = document.getElementById("exp-verdict").value || "";
  st.category = document.getElementById("exp-cat").value || "";
  drawExplorerTable();
}

function explorerSort(key) {
  const st = window.__explorer; if (!st) return;
  if (st.sortKey === key) st.sortDir = -st.sortDir; else { st.sortKey = key; st.sortDir = 1; }
  drawExplorerTable();
}

function drawExplorerTable() {
  const st = window.__explorer; if (!st) return;
  const tbl = document.getElementById("exp-table");
  const dims = st.dims, thr = st.thr;
  // filter
  let rows = st.cases.filter(r => {
    const c = r.case || {}, s = r.score;
    if (st.category && (c.category || "default") !== st.category) return false;
    if (st.verdict && _verdictLabel(s) !== st.verdict) return false;
    if (st.q) {
      const hay = ((c.prompt || "") + " " + (c.category || "") + " "
        + (r.response ? (r.response.text || "") : "")).toLowerCase();
      if (hay.indexOf(st.q) < 0) return false;
    }
    return true;
  });
  // sort
  const sk = st.sortKey, dir = st.sortDir;
  const keyVal = (r) => {
    const c = r.case || {}, s = r.score;
    if (sk === "prompt") return (c.prompt || "").toLowerCase();
    if (sk === "category") return (c.category || "default").toLowerCase();
    if (sk === "verdict") return _verdictLabel(s);
    if (sk === "assertions") return s ? (s.assertions_passed === false ? 0 : (s.assertions_passed === true ? 2 : 1)) : 1;
    if (sk === "score") { const m = _scoreMean(s); return m == null ? -1 : m; }
    if (dims.indexOf(sk) >= 0) { const v = s && s.dimensions ? s.dimensions[sk] : null; return v == null ? -1 : Number(v); }
    return "";
  };
  rows.sort((a, b) => {
    const va = keyVal(a), vb = keyVal(b);
    if (va < vb) return -1 * dir; if (va > vb) return 1 * dir; return 0;
  });
  const arrow = (k) => st.sortKey === k ? ' <span class="arr">' + (st.sortDir > 0 ? "▲" : "▼") + '</span>' : '';
  let head = '<tr>'
    + '<th onclick="explorerSort(\'prompt\')">Prompt' + arrow("prompt") + '</th>'
    + '<th onclick="explorerSort(\'category\')">Category' + arrow("category") + '</th>'
    + '<th onclick="explorerSort(\'score\')">Mean' + arrow("score") + '</th>';
  for (const d of dims) head += '<th onclick="explorerSort(\'' + esc(d) + '\')">' + esc(d) + arrow(d) + '</th>';
  head += '<th onclick="explorerSort(\'assertions\')">Assert' + arrow("assertions") + '</th>'
    + '<th onclick="explorerSort(\'verdict\')">Verdict' + arrow("verdict") + '</th></tr>';
  let trs = "";
  for (const r of rows) {
    const c = r.case || {}, s = r.score;
    const cid = c.id || "";
    let tr = '<tr onclick="explorerOpen(\'' + esc(cid) + '\')">'
      + '<td class="p">' + esc(_trunc(c.prompt || "", 80)) + '</td>'
      + '<td>' + esc(c.category || "default") + '</td>'
      + '<td class="mono">' + num(_scoreMean(s), 1) + '</td>';
    for (const d of dims) {
      const v = s && s.dimensions ? s.dimensions[d] : null;
      if (v == null) tr += '<td class="muted">&mdash;</td>';
      else { const low = thr != null && v < thr; tr += '<td class="mono" style="color:' + (low ? "var(--fail)" : "var(--pass)") + '">' + v + '</td>'; }
    }
    let asrt = '<span class="muted">&mdash;</span>';
    if (s && s.assertions_passed === true) asrt = '<span class="mk pass" style="font-weight:700">✓</span>';
    else if (s && s.assertions_passed === false) asrt = '<span class="mk fail" style="font-weight:700">✗</span>';
    tr += '<td>' + asrt + '</td>';
    tr += '<td>' + passPill(s ? s.verdict_pass : null) + '</td></tr>';
    trs += tr;
  }
  const cnt = document.getElementById("exp-count");
  if (cnt) cnt.textContent = rows.length + " case" + (rows.length === 1 ? "" : "s");
  if (!rows.length) { tbl.innerHTML = '<div class="empty">No cases match these filters.</div>'; return; }
  tbl.innerHTML = '<table class="explorer"><thead>' + head + '</thead><tbody>' + trs + '</tbody></table>';
}

function explorerOpen(cid) {
  // expand the matching category section and scroll its case into view
  const d = window.__detail; if (!d) return;
  const row = (d.cases || []).find(r => r.case && r.case.id === cid);
  if (!row) return;
  const cat = (row.case && row.case.category) || "default";
  document.querySelectorAll("details.cat").forEach(det => {
    const nm = det.querySelector(".name");
    if (nm && nm.textContent === cat) {
      det.open = true;
      det.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
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

  // per-category forensic audits — root cause → fix is the centerpiece
  const cas = f.category_audits || [];
  if (cas.length) {
    let secs = "";
    for (const ca of cas) {
      let inner = '<div class="case" style="padding-left:18px">';
      if (ca.highest_leverage_one_liner)
        inner += '<div class="lead-fix" style="margin:8px 0"><span class="lead-label">Highest-leverage change</span><div>' + esc(ca.highest_leverage_one_liner) + '</div></div>';
      if (ca.gap_dims && ca.gap_dims.length) {
        inner += '<div style="margin:6px 0">' + ca.gap_dims.map(g => '<span class="gap-chip">' + esc(g) + '</span>').join("") + '</div>';
      }
      if (ca.failure_modes && ca.failure_modes.length) {
        inner += '<div class="label">Failure modes</div><ul class="fm-list" style="margin-left:0">';
        for (const fm of ca.failure_modes) {
          if (typeof fm === "string") { inner += '<li>' + esc(fm) + '</li>'; continue; }
          let li = "";
          if (fm.dimension) li += '<b>' + esc(fm.dimension) + '</b>: ';
          li += esc(fm.pattern || "");
          if (fm.code_locus) li += ' <span class="locus">' + esc(fm.code_locus) + '</span>';
          if (fm.rubric_criterion_missed) li += ' <span class="muted">— misses: ' + esc(fm.rubric_criterion_missed) + '</span>';
          inner += '<li>' + li + '</li>';
        }
        inner += '</ul>';
      }
      if (ca.leverage_changes && ca.leverage_changes.length) {
        inner += '<div class="label">Suggested fixes</div>';
        for (const lc of ca.leverage_changes) {
          if (typeof lc === "string") { inner += '<div class="fix-card" style="margin-left:0">' + esc(lc) + '</div>'; continue; }
          let fc = '<div class="fix-card" style="margin-left:0"><div class="fix-head">' + esc(lc.change || "fix");
          if (lc.target_dimension) fc += ' <span class="muted">→ ' + esc(lc.target_dimension) + '</span>';
          fc += '</div>';
          const sf = lc.suggested_fix || {};
          const locus = lc.code_locus || sf.file;
          if (locus) fc += '<div class="locus">' + esc(locus) + (sf.locus ? ' · ' + esc(sf.locus) : "") + '</div>';
          const metaBits = [];
          if (lc.est_impact) metaBits.push("impact " + lc.est_impact);
          if (lc.effort) metaBits.push("effort " + lc.effort);
          if (lc.confidence) metaBits.push("confidence " + lc.confidence);
          if (metaBits.length) fc += '<div class="muted" style="font-size:12px">' + esc(metaBits.join(" · ")) + '</div>';
          if (sf.rationale) fc += '<div style="margin-top:5px">' + esc(sf.rationale) + '</div>';
          if (sf.diff) fc += diffBlock(sf.diff);
          fc += '</div>';
          inner += fc;
        }
      }
      inner += '</div>';
      secs += '<details class="cat"><summary><span class="chev">▶</span><span class="name">' + esc(ca.category || "category") + '</span>'
        + (ca.gap_dims && ca.gap_dims.length ? '<span class="count">gaps: ' + ca.gap_dims.map(esc).join(", ") + '</span>' : "")
        + '</summary>' + inner + '</details>';
    }
    html += '<div class="panel"><h2>Root cause → fix, by category</h2>' + secs + '</div>';
  }

  // persona reactions + radar
  const p = audit.persona || {};
  const reactions = p.reactions || [];
  if (reactions.length) {
    // compute per-persona axis averages from reactions[].reactions[]
    const axisDefs = [
      { key: "trust", label: "Trust" },
      { key: "usefulness", label: "Usefulness" },
      { key: "clarity", label: "Clarity" },
      { key: "would_return", label: "Would return" },
    ];
    const radarSeries = [];
    for (const pr of reactions) {
      const agg = { trust: [], usefulness: [], clarity: [], would_return: [] };
      for (const cr of (pr.reactions || [])) {
        for (const k of Object.keys(agg)) {
          let v = cr[k];
          if (v === true) v = 10; else if (v === false) v = 0;
          v = Number(v);
          if (!isNaN(v)) agg[k].push(v);
        }
      }
      const axes = {};
      let any = false;
      for (const k of Object.keys(agg)) {
        if (agg[k].length) { axes[k] = agg[k].reduce((a,b)=>a+b,0)/agg[k].length; any = true; }
        else axes[k] = null;
      }
      if (any) radarSeries.push({ name: pr.persona || pr.persona_id || "Persona", axes: axes });
    }

    let cards = "";
    if (radarSeries.length) {
      cards += '<div class="chart-card"><p class="ctitle">Persona experience (avg trust · usefulness · clarity · would-return)</p>'
        + radar(radarSeries, axisDefs, {}) + '</div>';
    }
    for (const pr of reactions) {
      let card = '<div class="persona-card"><h3>' + esc(pr.persona || pr.persona_id || "Persona") + '</h3>';
      if (pr.persona_summary) card += '<div class="muted" style="font-size:13px">' + esc(pr.persona_summary) + '</div>';
      if (pr.biggest_frustrations && pr.biggest_frustrations.length) {
        card += '<div class="label">Biggest frustrations</div><ul class="frust">'
          + pr.biggest_frustrations.map(x => '<li>' + esc(typeof x === "string" ? x : JSON.stringify(x)) + '</li>').join("") + '</ul>';
      }
      if (pr.what_would_win_me) card += '<div class="label">What would win me</div><div>' + esc(pr.what_would_win_me) + '</div>';
      card += '</div>';
      cards += card;
    }
    html += '<div class="panel"><h2>Persona panel</h2><div class="body">' + cards + '</div></div>';
  }

  // rubric vs persona divergence
  const cmp = p.comparison || {};
  if (cmp && Object.keys(cmp).length) {
    const rows = [
      ["Rubric fidelity verdict", cmp.rubric_fidelity_verdict],
      ["Chasing-tail risks", cmp.chasing_tail_risks],
      ["Human-value blindspots", cmp.human_value_blindspots],
      ["Reconciled priorities", cmp.reconciled_priorities],
      ["Final path", cmp.final_path],
    ].filter(r => r[1]);
    let dhtml = "";
    for (const r of rows) {
      const v = Array.isArray(r[1]) ? r[1].map(esc).join("; ") : (typeof r[1] === "string" ? esc(r[1]) : esc(JSON.stringify(r[1])));
      dhtml += '<div class="label" style="padding:6px 16px 0">' + esc(r[0]) + '</div><div style="padding:0 16px">' + v + '</div>';
    }
    if (dhtml) html += '<div class="panel"><h2>Rubric vs persona divergence</h2><div class="body">' + dhtml + '</div></div>';
  }

  if (!html) html = '<div class="empty">No audit available for this run.</div>';
  body.innerHTML = html;
}

// ---- New Run panel ------------------------------------------------------
const CATEGORY_HINTS = ["factual_qa","how_to","reasoning","recommendations","refusal","safety","edge_input"];
const FORMAT_OPTS = ["md","html","pdf","docx"];

async function showNewRun() {
  view = "newrun"; currentRunId = null; crumb.textContent = "New run";
  setNav("newrun");
  stopPoll();
  app.innerHTML = '<div class="empty">Loading…</div>';
  let configs = [], pfiles = [];
  try { configs = await getJSON("/api/configs"); } catch (e) { configs = []; }
  try { pfiles = await getJSON("/api/personas/files"); } catch (e) { pfiles = []; }
  renderNewRun(configs, pfiles);
}

function renderNewRun(configs, pfiles) {
  _builderProvidersReady = false;  // DOM is rebuilt; provider selects re-init on demand
  const cfgOpts = configs.length
    ? configs.map(c => '<option value="' + esc(c.path) + '">' + esc(c.name) + '</option>').join("")
    : '<option value="">(no configs found — a default config will be used)</option>';
  const personaOpts = ['<option value="">(use the config\'s own personas)</option>']
    .concat(pfiles.map(f => {
      const sel = (f.path === selectedPersonaPath) ? " selected" : "";
      return '<option value="' + esc(f.path) + '"' + sel + '>' + esc(f.name) + '</option>';
    })).join("");
  const catChecks = CATEGORY_HINTS.map(c =>
    '<label><input type="checkbox" class="cat-chk" value="' + esc(c) + '"> ' + esc(c) + '</label>').join("");
  const fmtChecks = FORMAT_OPTS.map(f =>
    '<label><input type="checkbox" class="fmt-chk" value="' + esc(f) + '"' + (f === "md" || f === "html" ? " checked" : "") + '> ' + esc(f) + '</label>').join("");

  const corpusSel = selectedCorpusPath
    ? '<div class="selpath"><span class="muted">Selected corpus:</span> '
      + '<span class="tag-mono">' + esc(selectedCorpusPath) + '</span> '
      + '<button class="btn" onclick="clearSelectedCorpus()">Clear</button>'
      + '<span class="hint">This generated corpus will run as a fixed set; Mode/Count/Categories above are ignored.</span></div>'
    : '';

  const cfgEditBtn = configs.length
    ? '<button class="btn" onclick="loadConfigForEdit(document.getElementById(\'nr-config\').value)">Edit in builder</button>'
    : '';

  const pickForm =
    '<div class="builder-sec" style="border-top:0;padding-top:14px">'
    + '<div class="bs-title">Config</div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field" style="grid-column:1 / -1"><label>Config</label>'
      + '<select id="nr-config" onchange="updateNrConfigHint()">' + cfgOpts + '</select>'
      + '<span class="field-hint" id="nr-config-hint">Blank fields below inherit this config\'s own settings.</span></div>'
    + '</div></div>'
    + '<div class="builder-sec"><div class="bs-title">Overrides <span class="bs-note">optional — leave blank to use the config</span></div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Mode</label><select id="nr-mode">'
      + ['','fixed','varied','adversarial','hybrid'].map(m => '<option value="' + m + '">' + (m || "inherit from config") + '</option>').join("")
      + '</select><span class="field-hint">How prompts are sourced for the run.</span></div>'
    + '<div class="field"><label>Count (varied / adversarial)</label><input type="number" id="nr-count" min="1" placeholder="inherit from config">'
      + '<span class="field-hint">Total prompts to generate.</span></div>'
    + '<div class="field"><label>Per category</label><input type="number" id="nr-percat" min="1" placeholder="inherit from config">'
      + '<span class="field-hint">Prompts for each category.</span></div>'
    + '<div class="field"><label>Difficulty</label><select id="nr-diff">'
      + ['','mild','standard','aggressive'].map(m => '<option value="' + m + '">' + (m || "inherit from config") + '</option>').join("")
      + '</select><span class="field-hint">Pressure level for adversarial prompts.</span></div>'
    + '<div class="field"><label>Persona panel</label><select id="nr-personas">' + personaOpts + '</select>'
      + '<span class="field-hint">Reviewer panel that reacts to responses.</span></div>'
    + '</div></div>'
    + '<div class="builder-sec"><div class="bs-title">Scope &amp; output</div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Categories <span class="opt">optional</span></label><div class="checks">' + catChecks + '</div>'
      + '<span class="field-hint">Pick a subset, or leave all unchecked for the config\'s categories.</span></div>'
    + '<div class="field"><label>Report formats</label><div class="checks">' + fmtChecks + '</div></div>'
    + '<div class="field"><label>Backend</label><div class="checks"><label><input type="checkbox" id="nr-mock" checked> Mock (offline)</label></div>'
      + '<span class="field-hint">Mock needs no API key.</span></div>'
    + '</div></div>'
    + corpusSel
    + '<div class="launchbar"><button class="btn primary" id="nr-launch" onclick="launchRun()">Launch run</button>'
    + cfgEditBtn
    + '<span class="hint">Runs in-process against this dashboard\'s store; progress appears below.</span></div>'
    + '<div id="nr-progress"></div>';

  // "Build a config" pane — a real config builder (PART B).
  const buildForm = builderFormHtml()
    + '<div class="launchbar">'
    + '<button class="btn primary" id="bld-launch" onclick="saveBuilderConfig(true)">Save &amp; launch</button>'
    + '<button class="btn" id="bld-save" onclick="saveBuilderConfig(false)">Save config</button>'
    + '<span class="hint">Saved configs appear in the picker; Inject from the AI Designer fills this form.</span></div>'
    + '<div id="bld-result"></div>'
    + '<div id="nr-progress"></div>';

  const paths = '<div class="nr-paths">'
    + '<div class="nr-path' + (newRunPath === "pick" ? " active" : "") + '" id="nrp-pick" onclick="setNewRunPath(\'pick\')">Pick an existing config</div>'
    + '<div class="nr-path' + (newRunPath === "build" ? " active" : "") + '" id="nrp-build" onclick="setNewRunPath(\'build\')">Build a config</div>'
    + '</div>';

  const form = '<div class="panel"><h2>New run</h2>'
    + paths
    + '<div id="nr-pick-pane"' + (newRunPath === "pick" ? "" : ' style="display:none"') + '>' + pickForm + '</div>'
    + '<div id="nr-build-pane"' + (newRunPath === "build" ? "" : ' style="display:none"') + '>' + buildForm + '</div>'
    + '</div>';

  const studioLink = '<div class="muted" style="padding:0 2px 8px">Need a prompt corpus or persona panel? Build one in the '
    + '<a href="#" onclick="showStudio();return false;">Studio</a> '
    + '(<a href="#" onclick="showStudio(\'prompts\');return false;">Prompts</a> · '
    + '<a href="#" onclick="showStudio(\'personas\');return false;">Persona studio</a>). '
    + 'Or click <b>✦ Designer</b> in the header to draft a config from a description.</div>';
  app.innerHTML = form + studioLink;
  if (newRunPath === "build") ensureBuilderProviders();
  updateNrConfigHint();
}

// Read-only hint: resolve what the currently-picked config actually uses, so
// "inherit from config" reads as a concrete amount rather than a vague word.
// Fetches GET /api/config?path=<picker value>; never mutates request bodies or
// element ids the launch flow relies on.
let _nrHintToken = 0;
async function updateNrConfigHint() {
  const hint = document.getElementById("nr-config-hint");
  const sel = document.getElementById("nr-config");
  if (!hint || !sel) return;
  const path = sel.value || "";
  if (!path) {
    hint.innerHTML = "No config selected — a built-in default config will be used.";
    return;
  }
  const token = ++_nrHintToken;
  hint.innerHTML = 'Reading this config…';
  let data;
  try { data = await getJSON("/api/config?path=" + encodeURIComponent(path)); }
  catch (e) { if (token === _nrHintToken) hint.innerHTML = "Blank fields below inherit this config’s own settings."; return; }
  if (token !== _nrHintToken) return;  // a newer selection superseded this one
  const cfg = (data && data.config) || {};
  const co = cfg.corpus || {};
  const bits = [];
  if (co.mode) bits.push('mode <b>' + esc(co.mode) + '</b>');
  // amount: per_category pins a number; count pins a total; fixed corpus loads a dir
  if (co.per_category != null && co.per_category !== "") bits.push('<b>' + esc(co.per_category) + '</b>/category');
  else if (co.count != null && co.count !== "") bits.push('<b>' + esc(co.count) + '</b> total');
  else if (co.mode === "fixed" || co.path || co.dir || co.corpus_dir) bits.push('loads the config’s corpus (no fixed count)');
  if (co.difficulty) bits.push('difficulty <b>' + esc(co.difficulty) + '</b>');
  const cats = co.categories || [];
  if (Array.isArray(cats) && cats.length) bits.push('<b>' + cats.length + '</b> categor' + (cats.length === 1 ? 'y' : 'ies'));
  hint.innerHTML = bits.length
    ? 'This config runs ' + bits.join(' · ') + '. Blank overrides below inherit these.'
    : 'This config pins no corpus amount — blank fields use its built-in defaults.';
}

async function launchRun() {
  const btn = document.getElementById("nr-launch");
  if (btn) { btn.classList.add("disabled-btn"); btn.textContent = "Launching…"; }
  const cats = Array.from(document.querySelectorAll(".cat-chk:checked")).map(el => el.value);
  const fmts = Array.from(document.querySelectorAll(".fmt-chk:checked")).map(el => el.value);
  const overrides = {
    mode: (document.getElementById("nr-mode").value || ""),
    count: (document.getElementById("nr-count").value || ""),
    per_category: (document.getElementById("nr-percat").value || ""),
    categories: cats,
    difficulty: (document.getElementById("nr-diff").value || ""),
    mock: document.getElementById("nr-mock").checked,
    formats: fmts.length ? fmts : ["md","html"],
  };
  if (selectedCorpusPath) overrides.path = selectedCorpusPath;
  const body = { overrides: overrides };
  const cfgPath = document.getElementById("nr-config").value;
  if (cfgPath) body.config_path = cfgPath;
  const pp = document.getElementById("nr-personas").value;
  if (pp) body.personas_path = pp;

  let resp;
  try {
    resp = await postJSON("/api/run", body);
  } catch (e) {
    const pe = document.getElementById("nr-progress");
    if (pe) pe.innerHTML = '<div class="err">Could not start run: ' + esc(e.message) + '</div>';
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Launch run"; }
    return;
  }
  if (!resp || !resp.run_id) {
    const pe = document.getElementById("nr-progress");
    if (pe) pe.innerHTML = '<div class="err">Could not start run: ' + esc((resp && resp.error) || "unknown error") + '</div>';
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Launch run"; }
    return;
  }
  pollLaunch(resp.run_id);
}

const STAGES = ["corpus","run","analyze","audit","report","done"];

function pollLaunch(runId) {
  if (launchProgressTimer) { clearInterval(launchProgressTimer); launchProgressTimer = null; }
  const tick = async () => {
    let st;
    try { st = await getJSON("/api/run/" + encodeURIComponent(runId) + "/status"); }
    catch (e) { return; }
    drawLaunchProgress(runId, st);
    if (st.done) {
      if (launchProgressTimer) { clearInterval(launchProgressTimer); launchProgressTimer = null; }
      const btn = document.getElementById("nr-launch");
      if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Launch run"; }
      if (!st.error) {
        // refresh runs list in the background and offer to open the new run
        const pe = document.getElementById("nr-progress");
        if (pe) pe.innerHTML += '<div class="launchbar" style="padding-left:0">'
          + '<button class="btn primary" onclick="showRun(\'' + esc(runId) + '\')">Open run</button>'
          + '<button class="btn" onclick="showRuns()">Back to all runs</button></div>';
      }
    }
  };
  tick();
  launchProgressTimer = setInterval(tick, 1200);
}

function drawLaunchProgress(runId, st) {
  const pe = document.getElementById("nr-progress");
  if (!pe) return;
  const stage = st.stage || "queued";
  const erred = stage === "error" || !!st.error;
  let reached = STAGES.indexOf(stage);
  if (stage === "queued") reached = -1;
  const frac = st.total ? Math.round(100 * (st.completed || 0) / st.total) : (stage === "done" ? 100 : 0);
  let pips = "";
  for (let i = 0; i < STAGES.length; i++) {
    let cls = "stagepip";
    if (st.done && !erred && i <= STAGES.indexOf("done")) cls += " done";
    else if (i < reached) cls += " done";
    else if (i === reached) cls += " active";
    pips += '<span class="' + cls + '">' + esc(STAGES[i]) + '</span>';
  }
  let html = '<div class="runprog">'
    + '<div class="muted" style="font-size:12px;margin-bottom:6px">Run <span class="mono">' + shortId(runId) + '</span> · '
    + (erred ? '<span class="mv-down">error</span>' : esc(stage))
    + (st.total ? ' · ' + (st.completed || 0) + '/' + st.total + ' cases' : '') + '</div>'
    + '<div class="bigprog"><i style="width:' + (erred ? 100 : frac) + '%' + (erred ? ';background:var(--fail)' : '') + '"></i></div>'
    + '<div class="stagerow">' + pips + '</div>';
  if (erred) html += '<div class="err" style="padding:6px 0">' + esc(st.error || "run failed") + '</div>';
  else if (st.done) html += '<div class="mv-up" style="padding:4px 0;font-weight:700">Run complete.</div>';
  html += '</div>';
  pe.innerHTML = html;
}

// ---- Studio (Prompts + Personas) ----------------------------------------
async function showStudio(tab) {
  view = "studio"; currentRunId = null;
  setNav("studio");
  stopPoll();
  if (tab === "prompts" || tab === "personas") studioTab = tab;
  crumb.textContent = "Studio";
  renderStudio();
}

// kept as an alias so older links / saved bookmarks still resolve.
function showPersonas() { showStudio("personas"); }

function renderStudio() {
  const subtabs = '<div class="subtabs">'
    + '<div class="subtab' + (studioTab === "prompts" ? " active" : "") + '" onclick="setStudioTab(\'prompts\')">Prompts</div>'
    + '<div class="subtab' + (studioTab === "personas" ? " active" : "") + '" onclick="setStudioTab(\'personas\')">Personas</div>'
    + '</div>';
  app.innerHTML = subtabs + '<div id="studiobody"><div class="empty">Loading…</div></div>';
  if (studioTab === "prompts") renderPromptStudio();
  else loadPersonaStudio();
}

function setStudioTab(t) {
  closeCorpusStream();  // leaving (or re-entering) the sub-tab abandons any live generator
  studioTab = t;
  document.querySelectorAll(".subtab").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".subtab").forEach(el => {
    if ((el.getAttribute("onclick") || "").indexOf("'" + t + "'") >= 0) el.classList.add("active");
  });
  const b = document.getElementById("studiobody");
  if (b) b.innerHTML = '<div class="empty">Loading…</div>';
  if (t === "prompts") renderPromptStudio();
  else loadPersonaStudio();
}

// ---- Studio · Prompt-corpus generator -----------------------------------
const CORPUS_MODES = ["varied", "adversarial", "hybrid"];
const CORPUS_DIFFS = ["mild", "standard", "aggressive"];

function renderPromptStudio() {
  const body = document.getElementById("studiobody");
  if (!body) return;
  const modeOpts = CORPUS_MODES.map(m =>
    '<option value="' + m + '"' + (m === "varied" ? " selected" : "") + '>' + m + '</option>').join("");
  const diffOpts = CORPUS_DIFFS.map(m =>
    '<option value="' + m + '"' + (m === "standard" ? " selected" : "") + '>' + m + '</option>').join("");

  const gen = '<div class="panel"><h2>Generate a prompt corpus</h2>'
    // what to generate
    + '<div class="builder-sec" style="border-top:0;padding-top:14px"><div class="bs-title">Prompts</div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Mode</label><select id="cg-mode">' + modeOpts + '</select>'
      + '<span class="field-hint">Kind of prompts to synthesize.</span></div>'
    + '<div class="field" style="grid-column:span 2"><label>Domain <span class="opt">optional</span></label>'
      + '<input type="text" id="cg-domain" placeholder="e.g. a budgeting assistant for freelancers">'
      + '<span class="field-hint">Grounds the generated prompts in your use case.</span></div>'
    + '<div class="field"><label>Difficulty <span class="opt">adversarial</span></label><select id="cg-diff">' + diffOpts + '</select>'
      + '<span class="field-hint">Pressure level for adversarial prompts.</span></div>'
    + '<div class="field"><label>Count <span class="opt">total</span></label><input type="number" id="cg-count" min="1" placeholder="optional total">'
      + '<span class="field-hint">Alternative to per-category: a grand total spread across categories.</span></div>'
    + '<div class="field"><label>Per category</label><input type="number" id="cg-percat" min="1" placeholder="blank = 8 per category">'
      + '<span class="field-hint">Prompts for each category. Leave both blank for <b>8 per category</b>.</span></div>'
    + '<div class="field" style="grid-column:span 2"><label>Categories <span class="opt">optional, comma-separated</span></label>'
      + '<input type="text" id="cg-cats" placeholder="e.g. factual_qa, how_to, refusal">'
      + '<span class="field-hint">Blank lets the generator pick categories for the domain.</span></div>'
    + '<div class="field"><label>Seed <span class="opt">optional</span></label><input type="number" id="cg-seed" placeholder="reproducible">'
      + '<span class="field-hint">Fix for a repeatable corpus.</span></div>'
    + '</div></div>'
    // backend
    + '<div class="builder-sec"><div class="bs-title">Backend</div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Provider</label><select class="field" id="cg-provider"><option>loading…</option></select></div>'
    + '<div class="field"><label>Model</label><select class="field" id="cg-model"><option>—</option></select>'
      + '<input type="text" id="cg-model-custom" placeholder="custom model name" style="display:none;margin-top:4px"></div>'
    + '<div class="field"><label>Mode</label>'
      + '<div class="checks"><label><input type="checkbox" id="cg-mock" checked> Mock (offline)</label></div>'
      + '<span class="field-hint"><span class="mono">anthropic</span> is the default; use <span class="mono">ollama</span> for local. Mock needs no key.</span></div>'
    + '</div>'
    + '<div id="cg-provider-notice"></div>'
    + '</div>'
    + '<div class="launchbar"><button class="btn primary" id="cg-gen-btn" onclick="generateCorpus()">Generate corpus</button>'
    + '<span class="hint">Saves a loadable corpus dir; preview and exports appear below.</span></div>'
    + '<div id="cg-result"></div></div>';

  body.innerHTML = gen;
  // populate provider/model dropdowns from /api/providers; default to the
  // first available provider (Studio has no IP-locality constraint).
  initProviderSelects({
    providerSel: "cg-provider", modelSel: "cg-model", customInput: "cg-model-custom",
    notice: "cg-provider-notice", preferLocal: false,
  });
  if (lastCorpusResult) drawCorpusResult(lastCorpusResult);
}

// Close + forget any live generator stream. Safe to call repeatedly; used by
// Cancel, by terminal/error events, and as a guard when leaving the sub-tab.
function closeCorpusStream() {
  if (corpusStream) {
    try { corpusStream.close(); } catch (e) { /* already closed */ }
    corpusStream = null;
  }
}

function setGenBtnGenerating(on) {
  const btn = document.getElementById("cg-gen-btn");
  if (!btn) return;
  if (on) { btn.classList.add("disabled-btn"); btn.textContent = "Generating…"; }
  else { btn.classList.remove("disabled-btn"); btn.textContent = "Generate corpus"; }
}

function cancelCorpusStream() {
  closeCorpusStream();
  setGenBtnGenerating(false);
  const note = document.getElementById("cg-prog-note");
  if (note) note.textContent = "Stopped.";
  const cancel = document.getElementById("cg-cancel-btn");
  if (cancel) cancel.remove();
}

function generateCorpus() {
  const out = document.getElementById("cg-result");
  if (!out) return;
  // a generation is already streaming — ignore double-clicks
  if (corpusStream) return;
  closeCorpusStream();

  const numOrParam = id => {
    const v = (document.getElementById(id).value || "").trim();
    return v === "" ? "" : String(Number(v));
  };
  const fields = {
    mode: document.getElementById("cg-mode").value,
    domain: (document.getElementById("cg-domain").value || "").trim(),
    difficulty: document.getElementById("cg-diff").value,
    count: numOrParam("cg-count"),
    per_category: numOrParam("cg-percat"),
    categories: (document.getElementById("cg-cats").value || "").trim(),
    seed: numOrParam("cg-seed"),
    provider: resolveProvider("cg-provider"),
    model: resolveModel("cg-model", "cg-model-custom"),
    mock: document.getElementById("cg-mock").checked ? "1" : "0",
  };
  // same-origin relative URL; every value URL-encoded.
  const qs = Object.keys(fields)
    .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(fields[k]))
    .join("&");
  const url = "/api/corpus/generate/stream?" + qs;

  // scaffold the streaming UI: progress bar + count + scrollable live list.
  out.innerHTML =
      '<div class="cg-stream">'
    + '  <div class="cg-prog-head"><span class="cg-prog-note" id="cg-prog-note">Starting…</span>'
    + '    <span class="cg-prog-count" id="cg-prog-count"></span></div>'
    + '  <div class="cg-bar"><i id="cg-prog-fill"></i></div>'
    + '  <div class="cg-live" id="cg-live"><div class="empty">Waiting for the first prompt…</div></div>'
    + '  <div class="launchbar" style="padding:8px 0 0">'
    + '    <button class="btn" id="cg-cancel-btn" onclick="cancelCorpusStream()">Cancel</button></div>'
    + '</div>';
  setGenBtnGenerating(true);

  let target = 0;
  let produced = 0;
  let firstPrompt = true;

  const setProg = (i, t) => {
    if (t) target = t;
    if (i !== null && i !== undefined) produced = i;
    const fill = document.getElementById("cg-prog-fill");
    const cnt = document.getElementById("cg-prog-count");
    const pctW = target > 0 ? Math.min(100, Math.round((produced / target) * 100)) : 0;
    if (fill) fill.style.width = pctW + "%";
    if (cnt) cnt.textContent = target > 0 ? ("generated " + produced + "/" + target) : "";
  };

  const es = new EventSource(url);
  corpusStream = es;

  es.addEventListener("plan", ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    const note = document.getElementById("cg-prog-note");
    if (note) note.textContent = "Planning " + (d.target || 0) + " prompts…";
    setProg(0, d.target || 0);
  });

  es.addEventListener("batch", ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    const note = document.getElementById("cg-prog-note");
    if (note) note.textContent = "Generating… (batch " + ((d.index || 0) + 1) + ")";
    setProg(d.produced, d.target);
  });

  es.addEventListener("prompt", ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    const live = document.getElementById("cg-live");
    if (live) {
      if (firstPrompt) { live.innerHTML = ""; firstPrompt = false; }
      const row = document.createElement("div");
      row.className = "cg-row";
      row.innerHTML = '<span class="cg-tag">' + esc(d.category || "default") + "</span>" + esc(d.prompt || "");
      live.appendChild(row);
      live.scrollTop = live.scrollHeight;  // keep newest visible
    }
    const note = document.getElementById("cg-prog-note");
    if (note) note.textContent = "Generating prompts…";
    setProg(d.i, d.target);
  });

  es.addEventListener("done", ev => {
    const note = document.getElementById("cg-prog-note");
    if (note) note.textContent = "Saving corpus…";
  });

  es.addEventListener("result", ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { d = null; }
    closeCorpusStream();
    setGenBtnGenerating(false);
    if (!d || !d.path) {
      if (out) out.innerHTML = '<div class="err">' + esc((d && (d.detail || d.error)) || "generation failed") + '</div>';
      return;
    }
    lastCorpusResult = d;
    drawCorpusResult(d);  // terminal: replaces the live list with the final result
  });

  es.addEventListener("error", ev => {
    // SSE "error" event with a payload (server-reported failure)
    let d = null;
    if (ev && ev.data) { try { d = JSON.parse(ev.data); } catch (e) { d = null; } }
    if (d && d.error) {
      closeCorpusStream();
      setGenBtnGenerating(false);
      if (out) out.innerHTML = '<div class="err">Could not generate corpus: ' + esc(d.error) + '</div>';
    }
    // a payload-less error is the EventSource onerror path, handled below.
  });

  // network drop / abort / stream closed before a terminal "result" frame.
  es.onerror = () => {
    if (!corpusStream) return;  // already finished cleanly
    closeCorpusStream();
    setGenBtnGenerating(false);
    const note = document.getElementById("cg-prog-note");
    if (note && firstPrompt && produced === 0) note.textContent = "Stopped.";
    else if (note) note.textContent = "Stopped — stream ended before the corpus was saved.";
    const cancel = document.getElementById("cg-cancel-btn");
    if (cancel) cancel.remove();
  };
}

function drawCorpusResult(resp) {
  const out = document.getElementById("cg-result");
  if (!out) return;
  const cats = resp.categories || {};
  const chips = Object.keys(cats).sort().map(k =>
    '<span class="cchip">' + esc(k) + ' <b>' + (cats[k] || 0) + '</b></span>').join("");
  const isMock = resp.provider === "mock";
  const summary = '<div class="corpus-summary">'
    + '<span class="cchip"><b>' + (resp.count || 0) + '</b> prompts</span>'
    + '<span class="cchip">mode <b>' + esc(resp.mode || "") + '</b></span>'
    + '<span class="cchip">provider <b>' + esc(resp.provider || "") + '</b>' + (isMock ? ' (offline)' : '') + '</span>'
    + chips + '</div>'
    + '<div class="muted" style="padding:2px 16px 6px">Saved to <span class="tag-mono">' + esc(resp.path) + '</span></div>';

  const ep = encodeURIComponent(resp.path);
  const expBase = "/api/corpus/export?path=" + ep;
  const exports = '<div class="btnrow" style="margin:2px 16px 12px">'
    + '<a class="btn" href="' + expBase + '&format=json">Export JSON</a>'
    + '<a class="btn" href="' + expBase + '&format=jsonl">Export JSONL</a>'
    + '<a class="btn" href="' + expBase + '&format=csv">Export CSV</a>'
    + '<a class="btn" href="' + expBase + '&format=json&prompts_only=1">Prompts only (JSON)</a>'
    + '<a class="btn" href="' + expBase + '&format=jsonl&prompts_only=1">Prompts only (JSONL)</a>'
    + '<button class="btn primary" onclick="useCorpusPath(\'' + esc(resp.path) + '\')">Use in new run</button>'
    + '</div>';

  // group preview by category, preserving order of appearance
  const preview = resp.preview || [];
  let previewHtml;
  if (preview.length) {
    const order = [], byCat = {};
    for (const p of preview) {
      const c = p.category || "default";
      if (!byCat[c]) { byCat[c] = []; order.push(c); }
      byCat[c].push(p.prompt || "");
    }
    previewHtml = '<div class="corpus-preview">' + order.map(c =>
      '<div class="pgroup"><div class="pcat">' + esc(c) + ' (' + byCat[c].length + ')</div>'
      + byCat[c].map(t => '<div class="pitem">' + dash(t) + '</div>').join("")
      + '</div>').join("") + '</div>';
    if (resp.count && preview.length < resp.count) {
      previewHtml += '<div class="muted" style="padding:0 16px 10px">Showing first ' + preview.length
        + ' of ' + resp.count + ' prompts — export for the full set.</div>';
    }
  } else {
    previewHtml = '<div class="empty">No prompts returned.</div>';
  }

  out.innerHTML = summary + exports + previewHtml;
}

function useCorpusPath(path) {
  selectedCorpusPath = path;
  showNewRun();
}

function clearSelectedCorpus() {
  selectedCorpusPath = "";
  showNewRun();
}

// ---- Studio · Persona studio --------------------------------------------
async function loadPersonaStudio() {
  let lib = [], files = [];
  try { lib = await getJSON("/api/personas"); } catch (e) { lib = []; }
  try { files = await getJSON("/api/personas/files"); } catch (e) { files = []; }
  renderPersonaStudio(lib, files);
}

function personaCardHtml(p, cls) {
  return '<div class="' + (cls || "persona-card") + '"><h3>' + esc(p.who ? (p.id || "persona") : (p.id || "persona")) + '</h3>'
    + (p.who ? '<div>' + esc(p.who) + '</div>' : '')
    + (p.focus ? '<div class="label">Focus</div><div class="muted">' + esc(p.focus) + '</div>' : '')
    + '</div>';
}

function renderPersonaStudio(lib, files) {
  // create
  const create = '<div class="panel"><h2>Create a persona</h2>'
    + '<div class="form-grid"><div class="field" style="grid-column:1 / -1"><label>One-line description</label>'
    + '<textarea id="ps-desc" placeholder="e.g. a busy nurse manager who skims and distrusts marketing"></textarea></div></div>'
    + '<div class="launchbar"><button class="btn primary" id="ps-create-btn" onclick="createPersona()">Create</button>'
    + '<label class="hint"><input type="checkbox" id="ps-create-mock" checked> mock</label></div>'
    + '<div id="ps-create-result"></div></div>';

  // generate panel
  const gen = '<div class="panel"><h2>Generate a domain panel</h2>'
    + '<div class="form-grid">'
    + '<div class="field"><label>Count</label><input type="number" id="ps-count" value="6" min="1" max="24"></div>'
    + '<div class="field" style="grid-column:span 2"><label>Domain</label><input type="text" id="ps-domain" placeholder="e.g. a budgeting assistant for freelancers"></div>'
    + '</div>'
    + '<div class="launchbar"><button class="btn primary" id="ps-gen-btn" onclick="generatePanel()">Generate panel</button>'
    + '<label class="hint"><input type="checkbox" id="ps-gen-mock" checked> mock</label></div>'
    + '<div id="ps-gen-result"></div></div>';

  // saved files
  let filesHtml;
  if (files.length) {
    filesHtml = '<ul class="filelist">' + files.map(f =>
      '<li><b>' + esc(f.name) + '</b> <span class="tag-mono">' + esc(f.path) + '</span>'
      + '<span class="spacer" style="flex:1"></span>'
      + '<a class="btn" href="/api/personas/files/download?path=' + encodeURIComponent(f.path) + '">Export YAML</a>'
      + '<button class="btn" onclick="usePersonaFile(\'' + esc(f.path) + '\')">Use in new run</button></li>'
    ).join("") + '</ul>';
  } else {
    filesHtml = '<div class="empty">No saved persona files yet. Create or generate one above.</div>';
  }
  const savedPanel = '<div class="panel"><h2>Saved persona files</h2><div class="body">' + filesHtml + '</div></div>';

  // library
  let libHtml = lib.length
    ? '<div class="body">' + lib.map(p => personaCardHtml(p)).join("") + '</div>'
    : '<div class="empty">No personas in the bundled library.</div>';
  const libPanel = '<div class="panel"><h2>Persona library</h2>' + libHtml + '</div>';

  const body = document.getElementById("studiobody") || app;
  body.innerHTML = create + gen + savedPanel + libPanel;
}

async function createPersona() {
  const btn = document.getElementById("ps-create-btn");
  const desc = (document.getElementById("ps-desc").value || "").trim();
  const out = document.getElementById("ps-create-result");
  if (!desc) { out.innerHTML = '<div class="err">Enter a description first.</div>'; return; }
  if (btn) { btn.classList.add("disabled-btn"); btn.textContent = "Creating…"; }
  let resp;
  try {
    resp = await postJSON("/api/personas/new", { description: desc, mock: document.getElementById("ps-create-mock").checked });
  } catch (e) {
    out.innerHTML = '<div class="err">' + esc(e.message) + '</div>';
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Create"; }
    return;
  }
  if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Create"; }
  if (!resp || !resp.persona) { out.innerHTML = '<div class="err">' + esc((resp && resp.error) || "create failed") + '</div>'; return; }
  out.innerHTML = personaCardHtml(resp.persona, "persona-result")
    + '<div class="muted" style="padding:0 16px 8px">Saved to <span class="tag-mono">' + esc(resp.path || "") + '</span></div>';
}

async function generatePanel() {
  const btn = document.getElementById("ps-gen-btn");
  const domain = (document.getElementById("ps-domain").value || "").trim();
  const count = Number(document.getElementById("ps-count").value || 6);
  const out = document.getElementById("ps-gen-result");
  if (!domain) { out.innerHTML = '<div class="err">Enter a domain first.</div>'; return; }
  if (btn) { btn.classList.add("disabled-btn"); btn.textContent = "Generating…"; }
  let resp;
  try {
    resp = await postJSON("/api/personas/generate", { count: count, domain: domain, mock: document.getElementById("ps-gen-mock").checked });
  } catch (e) {
    out.innerHTML = '<div class="err">' + esc(e.message) + '</div>';
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Generate panel"; }
    return;
  }
  if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Generate panel"; }
  if (!resp || !resp.panel) { out.innerHTML = '<div class="err">' + esc((resp && resp.error) || "generate failed") + '</div>'; return; }
  let html = '<div class="muted" style="padding:0 16px">Saved ' + resp.panel.length + ' personas to <span class="tag-mono">' + esc(resp.path || "") + '</span>';
  if (resp.path) html += ' <button class="btn" onclick="usePersonaFile(\'' + esc(resp.path) + '\')">Use in new run</button>';
  html += '</div>';
  html += resp.panel.map(p => personaCardHtml(p, "persona-result")).join("");
  out.innerHTML = html;
}

function usePersonaFile(path) {
  selectedPersonaPath = path;
  showNewRun();
}

// ---- New run: pick-existing vs build a config ---------------------------
let newRunPath = "pick";   // "pick" | "build"

function setNewRunPath(p) {
  newRunPath = p;
  document.querySelectorAll(".nr-path").forEach(el => el.classList.remove("active"));
  const el = document.getElementById("nrp-" + p);
  if (el) el.classList.add("active");
  const pick = document.getElementById("nr-pick-pane");
  const build = document.getElementById("nr-build-pane");
  if (pick) pick.style.display = (p === "pick") ? "" : "none";
  if (build) build.style.display = (p === "build") ? "" : "none";
  if (p === "build") ensureBuilderProviders();
  else if (typeof updateNrConfigHint === "function") updateNrConfigHint();
}

// ---- config builder -----------------------------------------------------
const BUILD_ADAPTERS = ["demo", "llm", "http", "callable"];
const BUILD_CORPUS_MODES = ["varied", "adversarial", "hybrid", "fixed"];
const BUILD_DIFFS = ["mild", "standard", "aggressive"];
const BUILD_GATES = ["strict", "weighted"];
const BUILD_RT_PROFILES = ["all_frontier", "deep", "multi_frontier", "mixed", "local_swarm", "pressure", "quick", "jailbreak", "injection"];
const BUILD_FORMATS = ["md", "html", "json", "docx", "pdf"];
let _builderProvidersReady = false;
let _builderLaunchAfterSave = false;

function ensureBuilderProviders() {
  if (_builderProvidersReady) return;
  if (!document.getElementById("bld-provider")) return;
  _builderProvidersReady = true;
  initProviderSelects({
    providerSel: "bld-provider", modelSel: "bld-model", customInput: "bld-model-custom",
    notice: "bld-provider-notice", preferLocal: false,
  });
}

function builderFormHtml() {
  const opts = (arr, sel) => arr.map(v =>
    '<option value="' + esc(v) + '"' + (v === sel ? " selected" : "") + '>' + esc(v) + '</option>').join("");
  const fmtChecks = BUILD_FORMATS.map(f =>
    '<label><input type="checkbox" class="bld-fmt" value="' + esc(f) + '"'
    + (f === "md" || f === "html" ? " checked" : "") + '> ' + esc(f) + '</label>').join("");
  return ''
    // identity
    + '<div class="builder-sec" style="border-top:0;padding-top:14px"><div class="bs-title">Identity</div>'
    + '<div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Name</label><input type="text" id="bld-name" placeholder="my-eval">'
      + '<span class="field-hint">Shown in the runs list and report.</span></div>'
    + '<div class="field" style="grid-column:span 2"><label>Domain <span class="opt">system under test</span></label>'
      + '<input type="text" id="bld-domain" placeholder="e.g. a budgeting assistant for freelancers">'
      + '<span class="field-hint">Plain-language description; grounds generated prompts.</span></div>'
    + '</div></div>'
    // adapter
    + '<div class="builder-sec"><div class="bs-title">Adapter</div><div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Type</label><select id="bld-adapter">' + opts(BUILD_ADAPTERS, "demo") + '</select>'
      + '<span class="field-hint">How the run reaches the system under test.</span></div>'
    + '<div class="field" style="grid-column:span 2"><label>Options <span class="opt">JSON, optional</span></label>'
      + '<textarea id="bld-adapter-opts" placeholder=\'{ "base_url": "/v1/chat" }\'></textarea>'
      + '<span class="field-hint">Adapter-specific settings, e.g. an endpoint URL.</span></div>'
    + '</div></div>'
    // corpus
    + '<div class="builder-sec"><div class="bs-title">Corpus</div><div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Mode</label><select id="bld-mode">' + opts(BUILD_CORPUS_MODES, "varied") + '</select>'
      + '<span class="field-hint">How prompts are sourced.</span></div>'
    + '<div class="field"><label>Per category</label><input type="number" id="bld-percat" min="1" value="8">'
      + '<span class="field-hint">Prompts generated per category (default <b>8</b>).</span></div>'
    + '<div class="field"><label>Difficulty</label><select id="bld-diff">' + opts(BUILD_DIFFS, "standard") + '</select>'
      + '<span class="field-hint">Pressure level for adversarial prompts.</span></div>'
    + '</div>'
    + '<div class="field" style="padding:0 0 4px"><label>Categories</label>'
      + '<div class="catchips" id="bld-catchips"></div>'
      + '<div class="catadd" style="margin-top:8px"><input type="text" id="bld-catnew" placeholder="add a category…" '
      + 'onkeydown="if(event.key===\'Enter\'){event.preventDefault();addBuilderCat();}">'
      + '<button class="btn" onclick="addBuilderCat()">+ Add category</button></div>'
      + '<span class="field-hint">Leave empty to let the generator choose categories for the domain.</span></div>'
    + '</div>'
    // analyze + audit
    + '<div class="builder-sec"><div class="bs-title">Analysis &amp; audit</div><div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Judges</label><select id="bld-judges">' + opts(["1","2","3"], "1") + '</select>'
      + '<span class="field-hint">Scoring models; more raises agreement signal.</span></div>'
    + '<div class="field"><label>Gate mode</label><select id="bld-gate">' + opts(BUILD_GATES, "weighted") + '</select>'
      + '<span class="field-hint">How dimension scores combine into pass / fail.</span></div>'
    + '<div class="field"><label>Persona pool</label><input type="number" id="bld-personapool" min="0" value="5">'
      + '<span class="field-hint">Reviewer personas; <b>0</b> disables the panel.</span></div>'
    + '</div>'
    + '<div class="checks" style="padding:2px 0 4px"><label><input type="checkbox" id="bld-forensic" checked> Forensic audit</label></div>'
    + '</div>'
    // report
    + '<div class="builder-sec"><div class="bs-title">Report</div>'
    + '<div class="field" style="padding:2px 0 4px"><label>Formats</label><div class="checks">' + fmtChecks + '</div>'
      + '<span class="field-hint">Artifacts written when the run finishes.</span></div>'
    + '</div>'
    // red team + backend
    + '<div class="builder-sec"><div class="bs-title">Red team &amp; backend</div><div class="form-grid" style="padding:0 0 4px">'
    + '<div class="field"><label>Red-team profile</label><select id="bld-rtprofile">' + opts(BUILD_RT_PROFILES, "all_frontier") + '</select>'
      + '<span class="field-hint">Attack suite the run probes with.</span></div>'
    + '<div class="field"><label>Provider</label><select class="field" id="bld-provider"><option>loading…</option></select></div>'
    + '<div class="field"><label>Model</label><select class="field" id="bld-model"><option>—</option></select>'
      + '<input type="text" id="bld-model-custom" placeholder="custom model name" style="display:none;margin-top:4px"></div>'
    + '</div>'
    + '<div id="bld-provider-notice"></div>'
    + '<div class="checks" style="padding:2px 0 4px"><label><input type="checkbox" id="bld-mock" checked> Mock (offline) when launching</label></div>'
    + '</div>';
}

// custom-category chip editor — each chip is an editable name + remove button.
function addBuilderCat(name) {
  const host = document.getElementById("bld-catchips");
  if (!host) return;
  const val = (typeof name === "string") ? name : ((document.getElementById("bld-catnew") || {}).value || "").trim();
  if (typeof name !== "string") {
    if (!val) return;
    const inp = document.getElementById("bld-catnew");
    if (inp) inp.value = "";
  }
  const chip = document.createElement("span");
  chip.className = "catchip";
  chip.innerHTML = '<input class="catname" type="text" value="' + esc(val) + '">'
    + '<button class="catx" title="remove" onclick="this.parentNode.remove()">&times;</button>';
  host.appendChild(chip);
}
function setBuilderCats(cats) {
  const host = document.getElementById("bld-catchips");
  if (!host) return;
  host.innerHTML = "";
  (cats || []).forEach(c => addBuilderCat(String(c)));
}
function getBuilderCats() {
  return Array.from(document.querySelectorAll("#bld-catchips .catname"))
    .map(el => (el.value || "").trim()).filter(Boolean);
}

// assemble the builder form into a Config-shaped object.
function assembleConfig() {
  let adapterOpts = {};
  const rawOpts = (document.getElementById("bld-adapter-opts").value || "").trim();
  if (rawOpts) { try { adapterOpts = JSON.parse(rawOpts); } catch (e) { adapterOpts = {}; } }
  const cfg = {
    name: (document.getElementById("bld-name").value || "").trim() || "polygraph-run",
    domain: (document.getElementById("bld-domain").value || "").trim() || null,
    adapter: { type: document.getElementById("bld-adapter").value, options: adapterOpts },
    corpus: {
      mode: document.getElementById("bld-mode").value,
      per_category: Number(document.getElementById("bld-percat").value || 8),
      categories: getBuilderCats(),
      difficulty: document.getElementById("bld-diff").value,
    },
    analyze: {
      judges: Number(document.getElementById("bld-judges").value || 1),
      gate_mode: document.getElementById("bld-gate").value,
    },
    audit: {
      forensic: document.getElementById("bld-forensic").checked,
      persona_pool: Number(document.getElementById("bld-personapool").value || 0) || null,
    },
    report: { formats: Array.from(document.querySelectorAll(".bld-fmt:checked")).map(el => el.value) },
    redteam: { profile: document.getElementById("bld-rtprofile").value },
    llm: { provider: resolveProvider("bld-provider") || "anthropic" },
    mock: document.getElementById("bld-mock").checked,
  };
  const model = resolveModel("bld-model", "bld-model-custom");
  if (model) { cfg.model = model; cfg.llm.model = model; }
  return cfg;
}

// populate the builder form FROM a config (Save→Load round-trip, or Inject).
function loadConfigIntoBuilder(cfg) {
  cfg = cfg || {};
  ensureBuilderProviders();
  const set = (id, v) => { const el = document.getElementById(id); if (el != null && v != null) el.value = v; };
  set("bld-name", cfg.name || "");
  set("bld-domain", cfg.domain || "");
  const ad = cfg.adapter || {};
  set("bld-adapter", BUILD_ADAPTERS.indexOf(ad.type) >= 0 ? ad.type : "demo");
  const opts = ad.options || ad.opts;
  if (opts && typeof opts === "object" && Object.keys(opts).length) {
    set("bld-adapter-opts", JSON.stringify(opts, null, 2));
  } else { set("bld-adapter-opts", ""); }
  const co = cfg.corpus || {};
  set("bld-mode", BUILD_CORPUS_MODES.indexOf(co.mode) >= 0 ? co.mode : "varied");
  if (co.per_category != null) set("bld-percat", co.per_category);
  set("bld-diff", BUILD_DIFFS.indexOf(co.difficulty) >= 0 ? co.difficulty : "standard");
  setBuilderCats(co.categories || []);
  const an = cfg.analyze || {};
  set("bld-judges", String(Math.max(1, Math.min(3, Number(an.judges || 1)))));
  set("bld-gate", BUILD_GATES.indexOf(an.gate_mode) >= 0 ? an.gate_mode : "weighted");
  const au = cfg.audit || {};
  const fchk = document.getElementById("bld-forensic"); if (fchk) fchk.checked = (au.forensic !== false);
  if (au.persona_pool != null) set("bld-personapool", au.persona_pool);
  const rt = cfg.redteam || {};
  set("bld-rtprofile", BUILD_RT_PROFILES.indexOf(rt.profile) >= 0 ? rt.profile : "all_frontier");
  const fmts = (cfg.report && cfg.report.formats) || ["md", "html"];
  document.querySelectorAll(".bld-fmt").forEach(el => { el.checked = fmts.indexOf(el.value) >= 0; });
  // provider/model are async (selects may still be loading) — best-effort
  const llm = cfg.llm || {};
  setTimeout(() => {
    const pv = document.getElementById("bld-provider");
    if (pv && llm.provider) { pv.value = llm.provider; fillModelSelect({ providerSel: "bld-provider", modelSel: "bld-model", customInput: "bld-model-custom" }); }
    const mv = cfg.model || llm.model;
    const ms = document.getElementById("bld-model");
    if (ms && mv) {
      const has = Array.from(ms.options).some(o => o.value === mv);
      if (has) ms.value = mv;
      else { ms.value = CUSTOM_OPT; const c = document.getElementById("bld-model-custom"); if (c) { c.style.display = ""; c.value = mv; } }
    }
  }, 60);
}

async function saveBuilderConfig(thenLaunch) {
  const out = document.getElementById("bld-result");
  const cfg = assembleConfig();
  if (out) out.innerHTML = '<div class="muted" style="padding:6px 0">Saving…</div>';
  let resp;
  try {
    resp = await postJSON("/api/configs", { name: cfg.name, config: cfg });
  } catch (e) {
    if (out) out.innerHTML = '<div class="err">Could not save config: ' + esc(e.message) + '</div>';
    return null;
  }
  if (out) out.innerHTML = '<div class="mv-up" style="padding:6px 0;font-weight:700">Saved '
    + esc(resp.name) + ' <span class="tag-mono">' + esc(resp.path) + '</span></div>';
  if (thenLaunch) launchBuiltConfig(resp.path, cfg.mock);
  return resp;
}

function launchBuiltConfig(cfgPath, mock) {
  const btn = document.getElementById("bld-launch");
  if (btn) { btn.classList.add("disabled-btn"); btn.textContent = "Launching…"; }
  const body = { config_path: cfgPath, overrides: { mock: !!mock } };
  postJSON("/api/run", body).then(resp => {
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Save & launch"; }
    if (!resp || !resp.run_id) {
      const out = document.getElementById("bld-result");
      if (out) out.innerHTML += '<div class="err">Could not start run: ' + esc((resp && resp.error) || "unknown") + '</div>';
      return;
    }
    pollLaunch(resp.run_id);
  }).catch(e => {
    if (btn) { btn.classList.remove("disabled-btn"); btn.textContent = "Save & launch"; }
    const out = document.getElementById("bld-result");
    if (out) out.innerHTML += '<div class="err">Could not start run: ' + esc(e.message) + '</div>';
  });
}

// Load an existing config into the builder for editing (from the picker).
async function loadConfigForEdit(pathOrName) {
  if (!pathOrName) return;
  setNewRunPath("build");
  let resp;
  try {
    resp = await getJSON("/api/config?path=" + encodeURIComponent(pathOrName));
  } catch (e) {
    const out = document.getElementById("bld-result");
    if (out) out.innerHTML = '<div class="err">Could not load config: ' + esc(e.message) + '</div>';
    return;
  }
  if (resp && resp.config) loadConfigIntoBuilder(resp.config);
}

// ---- dashboard AI Designer wiring (context: Run config) -----------------
window.__dkDesignUrl = "/api/config/design";
window.__dkRenderPreview = function(res) {
  const cfg = res.config || {};
  const co = cfg.corpus || {}, an = cfg.analyze || {}, au = cfg.audit || {}, rt = cfg.redteam || {};
  const ad = cfg.adapter || {};
  let secs = "";
  secs += dkSection("Name", esc(cfg.name || "—"), true);
  if (cfg.domain) secs += dkSection("Domain", esc(cfg.domain));
  secs += dkSection("Adapter", esc(ad.type || "demo"), true);
  secs += dkSection("Corpus", esc(co.mode || "varied") + ' · per-category ' + esc(co.per_category != null ? co.per_category : "—") + ' · ' + esc(co.difficulty || "standard"));
  if (co.categories && co.categories.length) secs += dkSection("Categories (" + co.categories.length + ")", dkChips(co.categories));
  secs += dkSection("Analyze", esc(an.judges != null ? an.judges : 1) + ' judge(s) · gate ' + esc(an.gate_mode || "weighted"));
  secs += dkSection("Audit", (au.forensic ? "forensic on" : "forensic off") + ' · persona pool ' + esc(au.persona_pool != null ? au.persona_pool : "—"));
  secs += dkSection("Report", dkChips((cfg.report && cfg.report.formats) || []));
  secs += dkSection("Red team", esc(rt.profile || "all_frontier"), true);
  return dkPreviewShell("Designed run config", res.provider, secs, res.notes);
};
window.__dkInject = function(cfg) {
  setNewRunPath("build");
  loadConfigIntoBuilder(cfg);
  closeDesigner();
};

// ---- boot ---------------------------------------------------------------
"""
    + DESIGNER_DOCK_JS
    + r"""
showRuns();
</script>
</body>
</html>
"""
)

# Assemble the full self-contained dashboard document: shared <head> (theme),
# shared header bar (in-page view switchers — this page is the dashboard), then
# the SPA body/script.
PAGE: str = _HEAD + header_html("runs", links=False) + _BODY
