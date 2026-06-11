"""The Red-Team Arena — a live, single-page visualization of an authorized
red-team run against a target you own.

This module exposes a single function, :func:`render_arena_page`, which returns
a fully self-contained HTML document (inline CSS + vanilla JS, inline SVG — no
CDN, no external assets). The page opens a live stream (Server-Sent Events by
default, or a WebSocket) and dramatizes the run:

* attacker agents split across a left and right rail, each streaming its
  "thinking" before it fires a probe;
* a target node in the center that pulses on every response;
* probe arcs that fly rail -> center on each attack;
* a defended (green) pile and a breached (red) pile, blocks heated by severity;
* a live breach counter + severity gauge;
* a severity-ranked vulnerability + mitigation panel; and
* a click-through drawer with the full probe, response, and judge rationale.

The same page is reused by the hosted service with ``transport="ws"``.

Nothing in this module imports the red-team engine or any heavy dependency — it
is pure string templating so it stays trivially safe to call from a request
handler.
"""

from __future__ import annotations

import json

__all__ = ["render_arena_page"]


def render_arena_page(*, stream_url: str, transport: str = "sse") -> str:
    """Return the self-contained Red-Team Arena HTML page.

    Args:
        stream_url: the URL the page connects to for the live event stream. For
            ``transport="sse"`` this is opened with ``EventSource``; for
            ``transport="ws"`` it is opened with ``WebSocket`` (the caller is
            responsible for handing a ``ws(s)://`` or scheme-relative URL).
        transport: ``"sse"`` (default) or ``"ws"``.

    The returned document contains inline CSS + JS only and references no
    external origins, so it works fully offline.
    """
    transport = "ws" if str(transport).lower() == "ws" else "sse"
    # JSON-encode the config so it is safely embedded as a JS object literal.
    # json.dumps escapes quotes/backslashes; we additionally neutralize the
    # "</" sequence so the data block can never close the <script> element.
    cfg = json.dumps({"streamUrl": stream_url, "transport": transport})
    cfg = cfg.replace("</", "<\\/")
    return _TEMPLATE.replace("__ARENA_CONFIG__", cfg)


# The page is a single template; the only interpolation point is the config
# blob, injected as a JSON object literal. Everything else is static.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Red-Team Arena — PromptPolygraph</title>
<style>
  :root {
    --bg: #07080d;
    --bg2: #0c0e16;
    --panel: #11141f;
    --panel-2: #161a28;
    --line: #232838;
    --text: #e8ecf6;
    --muted: #8a93a8;
    --accent: #6ee7ff;
    --accent2: #b07cff;
    --green: #2fe08a;
    --green-deep: #0e7a4a;
    --red: #ff5470;
    --red-deep: #8a1733;
    --amber: #ffcf5c;
    --sev-none: #2fe08a;
    --sev-low: #9be36a;
    --sev-medium: #ffcf5c;
    --sev-high: #ff9248;
    --sev-critical: #ff3860;
    --shadow: 0 8px 30px rgba(0,0,0,.55);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    background:
      radial-gradient(1200px 700px at 50% -10%, rgba(110,231,255,.08), transparent 60%),
      radial-gradient(900px 600px at 10% 110%, rgba(176,124,255,.07), transparent 55%),
      var(--bg);
    color: var(--text);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header.top {
    display: flex; align-items: center; gap: 14px;
    padding: 12px 20px; border-bottom: 1px solid var(--line);
    background: linear-gradient(180deg, rgba(20,24,38,.9), rgba(12,14,22,.6));
    backdrop-filter: blur(6px);
    position: sticky; top: 0; z-index: 30;
  }
  header.top h1 { font-size: 17px; margin: 0; letter-spacing: .3px; font-weight: 700; }
  header.top h1 .spark { color: var(--accent); }
  header.top .sub { color: var(--muted); font-size: 12px; }
  header.top a.home {
    color: var(--muted); text-decoration: none; font-size: 13px; font-weight: 600;
    padding: 5px 11px; border-radius: 7px; border: 1px solid var(--line);
  }
  header.top a.home:hover { color: var(--text); background: var(--panel-2); }
  header.top .spacer { flex: 1; }
  .pill {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 11px; border-radius: 999px; border: 1px solid var(--line);
    background: var(--panel); font-size: 12px; color: var(--muted);
  }
  .pill b { color: var(--text); font-variant-numeric: tabular-nums; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.live { background: var(--green); box-shadow: 0 0 0 0 rgba(47,224,138,.6); animation: ping 1.6s infinite; }
  .dot.done { background: var(--accent); animation: none; }
  .dot.err { background: var(--red); animation: none; }
  @keyframes ping { 0%{box-shadow:0 0 0 0 rgba(47,224,138,.5)} 70%{box-shadow:0 0 0 8px rgba(47,224,138,0)} 100%{box-shadow:0 0 0 0 rgba(47,224,138,0)} }

  .gauges { display: flex; gap: 10px; align-items: center; }
  .gauge { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
  .gauge .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); }
  .gauge .val { font-size: 20px; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1; }
  .gauge.breach .val { color: var(--red); }
  .gauge.def .val { color: var(--green); }
  .sevbar { width: 150px; height: 9px; border-radius: 999px; overflow: hidden; background: var(--panel-2); display: flex; border: 1px solid var(--line); }
  .sevbar > span { height: 100%; transition: width .4s ease; }

  .stage {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) minmax(420px, 1.6fr) minmax(220px, 1fr);
    gap: 14px; padding: 16px 18px; align-items: start;
  }
  @media (max-width: 1100px) { .stage { grid-template-columns: 1fr; } }

  .rail { display: flex; flex-direction: column; gap: 12px; }
  .rail h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin: 2px 4px; }

  .agent {
    border: 1px solid var(--line); border-radius: 14px; padding: 11px 12px;
    background: linear-gradient(180deg, var(--panel), var(--bg2));
    position: relative; overflow: hidden; transition: border-color .2s, box-shadow .2s, transform .2s;
  }
  .agent::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: linear-gradient(180deg, var(--accent), var(--accent2)); opacity: .5;
  }
  .agent.firing { border-color: var(--accent); box-shadow: 0 0 0 1px rgba(110,231,255,.3), var(--shadow); transform: translateY(-1px); }
  .agent.breached::before { background: linear-gradient(180deg, var(--red), var(--red-deep)); opacity: 1; }
  .agent.defended::before { background: linear-gradient(180deg, var(--green), var(--green-deep)); opacity: 1; }
  .agent .ahead { display: flex; align-items: center; gap: 8px; }
  .agent .strat { font-weight: 700; font-size: 13px; letter-spacing: .2px; }
  .agent .badge {
    margin-left: auto; font-size: 10px; color: var(--muted); border: 1px solid var(--line);
    padding: 2px 7px; border-radius: 999px; background: var(--panel-2); white-space: nowrap;
  }
  .agent .turnchip { font-size: 10px; color: var(--accent); font-variant-numeric: tabular-nums; }
  .agent .think {
    margin-top: 8px; min-height: 16px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11.5px; color: var(--accent); white-space: pre-wrap; word-break: break-word;
    max-height: 64px; overflow: hidden; opacity: .92;
  }
  .agent .think .caret { display: inline-block; width: 7px; background: var(--accent); animation: blink 1s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }
  .agent .last { margin-top: 6px; font-size: 11px; color: var(--muted); }
  .agent .verdictchip {
    display: inline-block; margin-top: 6px; font-size: 10px; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line);
  }
  .verdictchip.breach { color: #fff; background: rgba(255,84,112,.18); border-color: var(--red); }
  .verdictchip.def { color: #fff; background: rgba(47,224,138,.16); border-color: var(--green); }

  .center { display: flex; flex-direction: column; gap: 14px; }
  .arena-wrap {
    position: relative; border: 1px solid var(--line); border-radius: 16px; overflow: hidden;
    background: radial-gradient(600px 360px at 50% 40%, rgba(110,231,255,.06), transparent 65%), var(--panel);
    min-height: 340px;
  }
  svg.arena { display: block; width: 100%; height: 360px; }

  .piles { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .pile { border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; background: var(--panel); }
  .pile h3 { margin: 0 0 8px; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .pile.green h3 { color: var(--green); }
  .pile.red h3 { color: var(--red); }
  .pile .blocks { display: flex; flex-wrap: wrap; gap: 5px; align-content: flex-start; min-height: 64px; max-height: 150px; overflow: auto; }
  .block {
    width: 20px; height: 20px; border-radius: 5px; cursor: pointer; position: relative;
    border: 1px solid rgba(255,255,255,.14); transition: transform .12s, box-shadow .12s;
    animation: drop .45s cubic-bezier(.2,.9,.25,1.2);
  }
  .block:hover { transform: scale(1.22); box-shadow: 0 0 0 2px rgba(255,255,255,.35); z-index: 2; }
  @keyframes drop { 0% { transform: translateY(-26px) scale(.4); opacity: 0; } 100% { transform: translateY(0) scale(1); opacity: 1; } }

  .panel { border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; background: var(--panel); }
  .panel h3 { margin: 0 0 10px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  .vuln { border: 1px solid var(--line); border-radius: 11px; padding: 9px 11px; margin-bottom: 8px; background: var(--panel-2); }
  .vuln .vh { display: flex; align-items: center; gap: 8px; }
  .vuln .sev { font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px; padding: 2px 8px; border-radius: 999px; color: #07080d; }
  .vuln .vc { font-weight: 700; font-size: 13px; }
  .vuln .cnt { margin-left: auto; font-size: 11px; color: var(--muted); }
  .vuln .mit { margin-top: 6px; font-size: 12px; color: var(--text); }
  .vuln .mit b { color: var(--green); }
  .muted { color: var(--muted); }
  .empty { color: var(--muted); padding: 8px 2px; font-size: 12.5px; }

  /* drawer */
  .scrim { position: fixed; inset: 0; background: rgba(3,4,8,.6); backdrop-filter: blur(3px); opacity: 0; pointer-events: none; transition: opacity .2s; z-index: 40; }
  .scrim.open { opacity: 1; pointer-events: auto; }
  .drawer {
    position: fixed; top: 0; right: 0; height: 100%; width: min(560px, 94vw);
    background: linear-gradient(180deg, var(--panel), var(--bg2)); border-left: 1px solid var(--line);
    transform: translateX(102%); transition: transform .26s cubic-bezier(.2,.8,.2,1);
    z-index: 41; box-shadow: var(--shadow); display: flex; flex-direction: column;
  }
  .drawer.open { transform: translateX(0); }
  .drawer .dh { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--line); }
  .drawer .dh .x { margin-left: auto; cursor: pointer; color: var(--muted); border: 1px solid var(--line); border-radius: 8px; padding: 3px 9px; }
  .drawer .dh .x:hover { color: var(--text); background: var(--panel-2); }
  .drawer .body { padding: 14px 16px; overflow: auto; }
  .drawer .seg { margin-bottom: 14px; }
  .drawer .seg .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 5px; }
  .drawer pre {
    margin: 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 9px; padding: 9px 11px; color: var(--text);
  }
  .tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); margin-right: 6px; }
  .banner { padding: 9px 14px; border-radius: 10px; font-size: 13px; margin: 0 18px 4px; }
  .banner.err { background: rgba(255,84,112,.12); border: 1px solid var(--red); color: #ffd5dd; }
  .banner.done { background: rgba(110,231,255,.1); border: 1px solid var(--accent); color: #cdf6ff; }
</style>
</head>
<body>
<header class="top">
  <h1><span class="spark">&#9889;</span> Red-Team Arena</h1>
  <span class="sub">authorized adversarial testing</span>
  <a class="home" href="/">&#8592; Dashboard</a>
  <span class="spacer"></span>
  <div class="gauges">
    <div class="gauge def"><span class="lbl">Defended</span><span class="val" id="g-def">0</span></div>
    <div class="gauge breach"><span class="lbl">Breaches</span><span class="val" id="g-breach">0</span></div>
    <div class="gauge"><span class="lbl">Severity</span>
      <div class="sevbar" id="sevbar" title="breaches by severity"></div>
    </div>
  </div>
  <span class="pill"><span class="dot" id="status-dot"></span><b id="status-text">connecting</b></span>
</header>

<div id="banner-slot"></div>

<div class="stage">
  <div class="rail" id="rail-left"><h2>Attackers</h2></div>

  <div class="center">
    <div class="arena-wrap">
      <svg class="arena" id="arena" viewBox="0 0 600 360" preserveAspectRatio="xMidYMid meet" aria-label="red-team arena">
        <defs>
          <radialGradient id="targetGrad" cx="50%" cy="45%" r="60%">
            <stop offset="0%" stop-color="#9bf0ff"/>
            <stop offset="55%" stop-color="#3aa6c8"/>
            <stop offset="100%" stop-color="#123445"/>
          </radialGradient>
          <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        <!-- defensive rings -->
        <circle id="ring1" cx="300" cy="180" r="92" fill="none" stroke="#2a3346" stroke-width="1.2" stroke-dasharray="4 7"/>
        <circle id="ring2" cx="300" cy="180" r="64" fill="none" stroke="#34405a" stroke-width="1.4" stroke-dasharray="3 6"/>
        <g id="arc-layer"></g>
        <g id="target">
          <circle id="target-core" cx="300" cy="180" r="42" fill="url(#targetGrad)" filter="url(#glow)"/>
          <text x="300" y="176" text-anchor="middle" fill="#04222e" font-size="13" font-weight="800">TARGET</text>
          <text id="target-name" x="300" y="192" text-anchor="middle" fill="#063244" font-size="9" font-weight="600">demo</text>
        </g>
      </svg>
    </div>

    <div class="piles">
      <div class="pile green"><h3>Defended &#8226; <span id="pile-def-n">0</span></h3><div class="blocks" id="pile-def"></div></div>
      <div class="pile red"><h3>Breached &#8226; <span id="pile-breach-n">0</span></h3><div class="blocks" id="pile-breach"></div></div>
    </div>

    <div class="panel">
      <h3>Vulnerabilities &amp; mitigations</h3>
      <div id="vulns"><div class="empty">No vulnerabilities surfaced yet. Probes in flight&#8230;</div></div>
    </div>
  </div>

  <div class="rail" id="rail-right"><h2>Attackers</h2></div>
</div>

<div class="scrim" id="scrim" onclick="closeDrawer()"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true">
  <div class="dh">
    <strong id="dr-title">Probe</strong>
    <span id="dr-sev" class="vuln" style="padding:2px 8px;border:none;background:transparent"></span>
    <span class="x" onclick="closeDrawer()">close &#10005;</span>
  </div>
  <div class="body" id="dr-body"></div>
</aside>

<script>
"use strict";
var CONFIG = __ARENA_CONFIG__;

// ---- safe helpers ---------------------------------------------------------
function esc(s) {
  s = (s == null) ? "" : String(s);
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function $(id) { return document.getElementById(id); }
function el(tag, cls, txt) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

var SEV = ["none", "low", "medium", "high", "critical"];
var SEV_RANK = { none: 0, low: 1, medium: 2, high: 3, critical: 4 };
var SEV_COLOR = {
  none: getCss("--sev-none"), low: getCss("--sev-low"), medium: getCss("--sev-medium"),
  high: getCss("--sev-high"), critical: getCss("--sev-critical")
};
function getCss(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888"; }
function sevColor(s) { return SEV_COLOR[s] || SEV_COLOR.medium; }

// ---- state ----------------------------------------------------------------
var agents = {};       // attacker_id -> { card, think, strat, breaches, side }
var attempts = {};     // key -> { prompt, response, verdict, strat, attacker_id, turn, block }
var lastProbe = {};    // attacker_id -> { text, turn }
var counts = { def: 0, breach: 0 };
var sevCounts = { none: 0, low: 0, medium: 0, high: 0, critical: 0 };
var leftCount = 0, rightCount = 0;
var ended = false;

function attemptKey(aid, turn) { return aid + "#" + (turn == null ? "?" : turn); }

// ---- agent cards ----------------------------------------------------------
function ensureAgent(aid, strat, meta) {
  if (agents[aid]) return agents[aid];
  var side = (Object.keys(agents).length % 2 === 0) ? "left" : "right";
  var rail = (side === "left") ? $("rail-left") : $("rail-right");
  if (side === "left") leftCount++; else rightCount++;

  var card = el("div", "agent");
  card.id = "agent-" + aid;
  var head = el("div", "ahead");
  head.appendChild(el("span", "strat", prettyStrat(strat)));
  var badge = el("span", "badge", backendLabel(meta));
  head.appendChild(badge);
  card.appendChild(head);
  var sub = el("div", "last");
  sub.innerHTML = '<span class="turnchip" id="turn-' + esc(aid) + '"></span> '
    + '<span class="tag">' + esc((meta && meta.intensity) || "standard") + '</span>';
  card.appendChild(sub);
  var think = el("div", "think");
  think.textContent = "";
  card.appendChild(think);
  rail.appendChild(card);

  return (agents[aid] = { card: card, think: think, strat: strat, breaches: 0, side: side });
}
function prettyStrat(s) { return String(s || "agent").replace(/_/g, " "); }
function backendLabel(meta) {
  if (!meta) return "agent";
  var p = meta.provider || "?";
  var m = meta.model ? (" / " + meta.model) : "";
  return p + m;
}

// ---- thinking stream (typewriter) -----------------------------------------
function onThinking(ev) {
  var a = ensureAgent(ev.attacker_id, ev.strategy, null);
  a.card.classList.add("firing");
  if (a._freshThink !== ev.turn) { a.think.textContent = ""; a._freshThink = ev.turn; }
  a.think.textContent += (ev.delta || "");
  a.think.innerHTML = esc(a.think.textContent) + '<span class="caret">&nbsp;</span>';
  var tc = $("turn-" + ev.attacker_id);
  if (tc && ev.turn) tc.textContent = "turn " + ev.turn;
}

// ---- attack: fly an arc from the rail to the center -----------------------
function onAttack(ev) {
  var a = ensureAgent(ev.attacker_id, ev.strategy, null);
  a.card.classList.add("firing");
  a.think.innerHTML = esc(ev.text || a.think.textContent || "");
  lastProbe[ev.attacker_id] = { text: ev.text || "", turn: ev.turn };
  flyArc(a.side);
}
function flyArc(side) {
  var layer = $("arc-layer");
  if (!layer) return;
  var x0 = side === "left" ? 20 : 580;
  var y0 = 60 + Math.random() * 240;
  var cx = side === "left" ? 150 : 450, cy = 30 + Math.random() * 60;
  var d = "M " + x0 + " " + y0 + " Q " + cx + " " + cy + " 300 180";
  var color = side === "left" ? getCss("--accent") : getCss("--accent2");
  var len = 600;
  // insertAdjacentHTML inside the <g> parses in SVG-namespace context, so we
  // never need to spell out the namespace URI as a literal in this file.
  var html = '<path d="' + d + '" fill="none" stroke="' + color
    + '" stroke-width="2" stroke-linecap="round" opacity="0.9"'
    + ' stroke-dasharray="' + len + '" stroke-dashoffset="' + len + '"></path>';
  layer.insertAdjacentHTML("beforeend", html);
  var path = layer.lastElementChild;
  if (!path) return;
  var t0 = null, dur = 620;
  function step(ts) {
    if (t0 == null) t0 = ts;
    var k = Math.min(1, (ts - t0) / dur);
    path.setAttribute("stroke-dashoffset", String(len * (1 - k)));
    path.setAttribute("opacity", String(0.95 * (1 - k * 0.4)));
    if (k < 1) requestAnimationFrame(step);
    else { path.setAttribute("opacity", "0"); setTimeout(function(){ if (path.parentNode) path.parentNode.removeChild(path); }, 200); }
  }
  requestAnimationFrame(step);
}

// ---- response: pulse the target -------------------------------------------
function onResponse(ev) {
  var key = attemptKey(ev.attacker_id, ev.turn);
  var rec = attempts[key] || (attempts[key] = {});
  rec.response = ev.text || "";
  rec.attacker_id = ev.attacker_id; rec.strat = ev.strategy; rec.turn = ev.turn;
  var p = lastProbe[ev.attacker_id];
  if (p) rec.prompt = p.text;
  pulseTarget();
  var a = agents[ev.attacker_id];
  if (a) a.card.classList.remove("firing");
}
function pulseTarget() {
  var core = $("target-core");
  if (!core) return;
  core.setAttribute("r", "52");
  core.style.transition = "none";
  requestAnimationFrame(function() {
    core.style.transition = "all .5s cubic-bezier(.2,.8,.2,1)";
    core.setAttribute("r", "42");
  });
}

// ---- verdict: drop a block onto a pile -------------------------------------
function onVerdict(ev) {
  var v = ev.verdict || {};
  var key = attemptKey(ev.attacker_id, ev.turn);
  var rec = attempts[key] || (attempts[key] = {});
  rec.verdict = v; rec.attacker_id = ev.attacker_id; rec.strat = ev.strategy; rec.turn = ev.turn;
  var p = lastProbe[ev.attacker_id];
  if (p && rec.prompt == null) rec.prompt = p.text;

  var breached = !!v.breached;
  var sev = v.severity || (breached ? "medium" : "none");
  var pileId = breached ? "pile-breach" : "pile-def";
  var block = el("div", "block");
  block.style.background = breached ? heatColor(sev) : sevColor("none");
  block.style.boxShadow = breached ? ("0 0 8px " + sevColor(sev)) : "none";
  block.title = (breached ? "BREACH" : "defended") + " · " + sev + " · " + prettyStrat(ev.strategy);
  block.tabIndex = 0;
  block.addEventListener("click", function() { openDrawer(rec); });
  block.addEventListener("keydown", function(e){ if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(rec); } });
  $(pileId).appendChild(block);
  rec.block = block;

  if (breached) { counts.breach++; sevCounts[sev] = (sevCounts[sev] || 0) + 1; }
  else { counts.def++; }
  $("pile-breach-n").textContent = counts.breach;
  $("pile-def-n").textContent = counts.def;
  $("g-breach").textContent = counts.breach;
  $("g-def").textContent = counts.def;
  renderSevBar();

  var a = agents[ev.attacker_id];
  if (a) {
    a.card.classList.remove("firing");
    a.card.classList.toggle("breached", breached);
    a.card.classList.toggle("defended", !breached);
    var chip = a.card.querySelector(".verdictchip");
    if (!chip) { chip = el("span", "verdictchip"); a.card.appendChild(chip); }
    chip.className = "verdictchip " + (breached ? "breach" : "def");
    chip.textContent = breached ? ("BREACH · " + sev) : "defended";
  }
}
function heatColor(sev) {
  // none -> green, escalating to deep red at critical
  return sevColor(sev);
}
function renderSevBar() {
  var bar = $("sevbar");
  bar.innerHTML = "";
  var total = 0; SEV.forEach(function(s){ if (s !== "none") total += (sevCounts[s] || 0); });
  if (total === 0) { bar.innerHTML = '<span style="width:100%;background:var(--panel-2)"></span>'; return; }
  ["low", "medium", "high", "critical"].forEach(function(s) {
    var n = sevCounts[s] || 0;
    if (!n) return;
    var seg = el("span");
    seg.style.width = (100 * n / total) + "%";
    seg.style.background = sevColor(s);
    seg.title = s + ": " + n;
    bar.appendChild(seg);
  });
}

// ---- vulnerabilities + summary --------------------------------------------
var vulns = {};
function onVuln(ev) {
  var d = ev.data || {};
  if (!d.vuln_class) return;
  vulns[d.vuln_class] = d;
  renderVulns();
}
function renderVulns() {
  var box = $("vulns");
  var list = Object.keys(vulns).map(function(k){ return vulns[k]; });
  if (!list.length) { box.innerHTML = '<div class="empty">No vulnerabilities surfaced yet. Probes in flight&#8230;</div>'; return; }
  list.sort(function(a, b){ return (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0); });
  box.innerHTML = "";
  list.forEach(function(v) {
    var card = el("div", "vuln");
    var head = el("div", "vh");
    var sev = el("span", "sev", v.severity || "medium");
    sev.style.background = sevColor(v.severity || "medium");
    head.appendChild(sev);
    head.appendChild(el("span", "vc", prettyStrat(v.vuln_class)));
    head.appendChild(el("span", "cnt", (v.count || 0) + "×"));
    card.appendChild(head);
    if (v.mitigation) {
      var mit = el("div", "mit");
      mit.innerHTML = "<b>Mitigation:</b> " + esc(v.mitigation);
      card.appendChild(mit);
    }
    box.appendChild(card);
  });
}

function onSummary(ev) {
  var d = ev.data || {};
  if (typeof d.breaches === "number") { $("g-breach").textContent = d.breaches; }
  if (typeof d.defended === "number") { $("g-def").textContent = d.defended; }
  var by = d.by_severity || {};
  Object.keys(by).forEach(function(s){ sevCounts[s] = by[s]; });
  renderSevBar();
}

function onProfile(ev) {
  var d = ev.data || {};
  if (d.target) { var tn = $("target-name"); if (tn) tn.textContent = String(d.target).slice(0, 14); }
  // Pre-spawn cards so the roster is visible immediately.
  (d.attackers || []).forEach(function(a) {
    ensureAgent(a.id, a.strategy, { provider: a.provider, model: a.model, intensity: a.intensity });
  });
}

// ---- drawer ---------------------------------------------------------------
function openDrawer(rec) {
  var v = rec.verdict || {};
  var breached = !!v.breached;
  var sev = v.severity || (breached ? "medium" : "none");
  $("dr-title").textContent = (breached ? "BREACH" : "Defended") + "  ·  " + prettyStrat(rec.strat);
  var sevTag = $("dr-sev");
  sevTag.textContent = sev + (v.vuln_class && v.vuln_class !== "none" ? ("  ·  " + prettyStrat(v.vuln_class)) : "");
  sevTag.style.color = sevColor(sev);
  sevTag.style.fontWeight = "800";

  var body = $("dr-body");
  body.innerHTML = "";
  body.appendChild(seg("Attacker", esc((rec.attacker_id || "?")) + "  ·  turn " + esc(rec.turn || 1)));
  body.appendChild(segPre("Probe", rec.prompt || "(probe not captured)"));
  body.appendChild(segPre("Target response", rec.response || "(no response)"));
  if (v.rationale) body.appendChild(segPre("Judge rationale", v.rationale));
  if (v.evidence) body.appendChild(segPre("Evidence", v.evidence));
  if (v.suggested_mitigation) {
    var s = segPre("Suggested mitigation", v.suggested_mitigation);
    s.querySelector("pre").style.borderColor = getCss("--green");
    body.appendChild(s);
  }
  $("scrim").classList.add("open");
  $("drawer").classList.add("open");
}
function seg(label, html) {
  var d = el("div", "seg");
  d.appendChild(el("div", "lbl", label));
  var v = el("div"); v.innerHTML = html; d.appendChild(v);
  return d;
}
function segPre(label, text) {
  var d = el("div", "seg");
  d.appendChild(el("div", "lbl", label));
  var pre = el("pre"); pre.textContent = (text == null ? "" : String(text)); d.appendChild(pre);
  return d;
}
function closeDrawer() { $("scrim").classList.remove("open"); $("drawer").classList.remove("open"); }
document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDrawer(); });

// ---- status + banners -----------------------------------------------------
function setStatus(kind, text) {
  var dot = $("status-dot");
  dot.className = "dot" + (kind === "live" ? " live" : kind === "done" ? " done" : kind === "err" ? " err" : "");
  $("status-text").textContent = text;
}
function banner(kind, text) {
  var slot = $("banner-slot");
  slot.innerHTML = "";
  var b = el("div", "banner " + kind, text);
  slot.appendChild(b);
}

// ---- event dispatch -------------------------------------------------------
function dispatch(type, payload) {
  try {
    switch (type) {
      case "profile": onProfile(payload); break;
      case "agent_spawned":
        ensureAgent(payload.attacker_id, payload.strategy, payload.data || {}); break;
      case "thinking": onThinking(payload); break;
      case "attack": onAttack(payload); break;
      case "response": onResponse(payload); break;
      case "verdict": onVerdict(payload); break;
      case "vuln": onVuln(payload); break;
      case "summary": onSummary(payload); break;
      case "done": onDone(payload); break;
      case "error": onError(payload); break;
    }
  } catch (e) { /* never let a malformed frame break the stream */ }
}
function onDone(ev) {
  ended = true;
  setStatus("done", "run complete");
  var d = ev.data || {};
  banner("done", "Run complete — " + (counts.breach) + " breach(es), " + counts.def + " defended."
    + (d.vulnerabilities ? (" " + d.vulnerabilities + " vulnerability class(es).") : ""));
  Object.keys(agents).forEach(function(k){ agents[k].card.classList.remove("firing"); });
  closeStream();
}
function onError(ev) {
  ended = true;
  setStatus("err", "stream error");
  var d = ev.data || {};
  banner("err", "Stream error: " + esc((d && d.message) || (ev && ev.text) || "unknown"));
  closeStream();
}

// ---- transport ------------------------------------------------------------
var es = null, ws = null, reconnects = 0;
var EVENT_TYPES = ["profile","agent_spawned","thinking","attack","response","verdict","vuln","summary","done","error"];

function parseData(raw) { try { return JSON.parse(raw); } catch (e) { return {}; } }

function startSSE() {
  setStatus("live", "live (SSE)");
  es = new EventSource(CONFIG.streamUrl);
  EVENT_TYPES.forEach(function(t) {
    es.addEventListener(t, function(e) { dispatch(t, parseData(e.data)); });
  });
  es.onerror = function() {
    if (ended) { return; }
    setStatus("", "reconnecting…");
    // EventSource auto-reconnects; if the server already finished, the next
    // open will immediately error again — cap the noise.
    reconnects++;
    if (reconnects > 8) { closeStream(); setStatus("done", "stream closed"); }
  };
}
function startWS() {
  setStatus("live", "live (WS)");
  try { ws = new WebSocket(CONFIG.streamUrl); }
  catch (e) { setStatus("err", "cannot open socket"); banner("err", "Could not open WebSocket."); return; }
  ws.onmessage = function(e) {
    // The service frames each event as JSON {type, ...} OR an SSE-style blob.
    var msg = parseData(e.data);
    if (msg && msg.type) dispatch(msg.type, msg);
  };
  ws.onclose = function() { if (!ended) { setStatus("done", "stream closed"); } };
  ws.onerror = function() { if (!ended) setStatus("err", "socket error"); };
}
function closeStream() {
  try { if (es) es.close(); } catch (e) {}
  try { if (ws && ws.readyState <= 1) ws.close(); } catch (e) {}
}

(function start() {
  renderSevBar();
  if (CONFIG.transport === "ws") startWS(); else startSSE();
  window.addEventListener("beforeunload", closeStream);
})();
</script>
</body>
</html>
"""
