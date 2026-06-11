"""The Red-Team Arena — a single-page console for an authorized red-team run
against a target you control.

This module exposes a single function, :func:`render_arena_page`, which returns
a fully self-contained HTML document (inline CSS + vanilla JS, inline SVG — no
CDN, no external assets, no web fonts). The page:

* drives a **Live** run over Server-Sent Events (default) or a WebSocket, or
  loads a saved run in **Replay** mode from the relative ``/api/redteam/*``
  endpoints;
* shows one lane per attacker agent (strategy, technique/source, provider/model,
  intensity, escalation mode, per-turn status and accumulating working text);
* shows the central probe -> response -> verdict with the evidence quote and a
  live scoreboard (ASR, attacks/breaches/defended, severity tallies, OWASP grid);
* lets you drill into any attacker to see the full multi-turn timeline beside
  an on-demand, code-grounded root-cause analysis.

The honesty rule for the drill-down: the colored root-cause **ladder** renders
only for a code-grounded trace (``mode === "code"`` — real ``file:line`` rungs).
When there is no code (``mode === "abstract"``) the page shows the honest
summary (control to harden, mitigation, OWASP/ATLAS, evidence, and the CTA to
point ``code_path`` at a checkout) and never draws a fabricated pipeline.

Nothing here imports the red-team engine — it is pure string templating, safe to
call from a request handler. The same page is reused by the hosted service with
``transport="ws"``.
"""

from __future__ import annotations

import json

from promptpolygraph.ui.chrome import (
    DESIGNER_DOCK_JS,
    THEME_CSS,
    designer_dock_html,
    header_html,
)

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
    html = _TEMPLATE.replace("__THEME_CSS__", THEME_CSS)
    # The Arena is a separate page, so the dashboard tabs link back to "/" and
    # "Red Team" is the active surface (links=True).
    html = html.replace("__ARENA_HEADER__", header_html("redteam", links=True))
    # The shared AI Designer dock (context "Red team") + its shared open/close JS.
    html = html.replace("__ARENA_DOCK__", designer_dock_html(context_label="Red team"))
    html = html.replace("__DESIGNER_DOCK_JS__", DESIGNER_DOCK_JS)
    return html.replace("__ARENA_CONFIG__", cfg)


# The page is a single template; the only interpolation point is the config
# blob, injected as a JSON object literal. Everything else is static.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Red-Team Arena — PromptPolygraph</title>
<style>
__THEME_CSS__
  /* ── arena-specific tokens, mapped onto the shared palette so the Arena
        stays color-consistent with the dashboard while keeping the extra
        surfaces/severity colors its unique components need ──────────────── */
  :root {
    --bg2: var(--panel);
    --panel-3: var(--row-hover);
    --line: var(--border);
    --line-2: #313a52;
    --muted-2: #636c82;
    --accent2: #9b8cff;
    --green: var(--pass);
    --green-deep: #0f6b48;
    --red: var(--fail);
    --red-deep: #7c1730;
    --amber: var(--warn);
    --sev-none: var(--pass);
    --sev-low: #8fd66a;
    --sev-medium: var(--warn);
    --sev-high: #f59442;
    --sev-critical: var(--fail);
    --shadow: 0 10px 34px rgba(0,0,0,.5);
  }
  .nums { font-variant-numeric: tabular-nums; }

  /* The arena page is a full-height single screen rather than a scrolling doc. */
  html, body { height: 100%; }

  /* ── arena status / run pill (inline-flex variant of the shared pill) ─── */
  .pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line);
    background: var(--panel); font-size: 12px; color: var(--muted);
  }
  .pill b { color: var(--text); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted-2); }
  .dot.live { background: var(--green); box-shadow: 0 0 0 0 rgba(52,211,153,.6); animation: ping 1.7s infinite; }
  .dot.done { background: var(--accent); animation: none; }
  .dot.err { background: var(--red); animation: none; }
  @keyframes ping { 0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)} 70%{box-shadow:0 0 0 7px rgba(52,211,153,0)} 100%{box-shadow:0 0 0 0 rgba(52,211,153,0)} }

  /* ── control bar ────────────────────────────────────────────────────── */
  .controls {
    display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
    padding: 11px 22px; border-bottom: 1px solid var(--line);
    background: var(--bg2);
  }
  .seg-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; }
  .seg-toggle button {
    appearance: none; border: 0; background: var(--panel); color: var(--muted);
    font: 600 12.5px/1 var(--sans); padding: 8px 15px; cursor: pointer; letter-spacing: .3px;
    transition: background .14s, color .14s;
  }
  .seg-toggle button:hover { color: var(--text); }
  .seg-toggle button + button { border-left: 1px solid var(--line); }
  .seg-toggle button.on { background: var(--panel-3); color: var(--text); }
  .seg-toggle button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

  .ctl { display: inline-flex; align-items: center; gap: 7px; }
  .ctl label { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); }
  .field, select.field {
    background: var(--panel); color: var(--text); border: 1px solid var(--line);
    border-radius: var(--radius-sm); padding: 7px 10px; font: 13px/1 var(--sans); min-width: 120px;
    transition: border-color .14s, box-shadow .14s;
  }
  .field:focus, select.field:focus { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
  .check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
  .check input { accent-color: var(--accent); }
  .chips { display: inline-flex; flex-wrap: wrap; gap: 4px; margin-left: 2px; }
  .chip {
    background: var(--panel-2, var(--panel)); color: var(--muted); border: 1px solid var(--line);
    border-radius: 999px; padding: 3px 10px; font: 11.5px/1.4 var(--sans); cursor: pointer;
    transition: color .14s, border-color .14s, background .14s;
  }
  .chip:hover { color: var(--text); border-color: var(--accent); background: var(--panel-3); }
  .chip:focus-visible { outline: none; box-shadow: var(--focus-ring); }
  .hint { font-size: 10.5px; color: var(--muted); cursor: help; text-transform: none; letter-spacing: 0; }
  .btn {
    appearance: none; display: inline-flex; align-items: center; gap: 6px;
    border: 1px solid var(--line); border-radius: var(--radius-sm);
    background: var(--panel-2); color: var(--text); font: 600 13px/1.2 var(--sans);
    padding: 8px 14px; cursor: pointer; transition: background .14s, border-color .14s, filter .14s;
  }
  .btn:hover { background: var(--panel-3); }
  .btn:active { filter: brightness(.96); }
  .btn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #0b0d11; font-weight: 700; }
  .btn.primary:hover { filter: brightness(1.08); background: var(--accent); }
  .btn.danger { border-color: var(--red-deep); color: #ffd7df; }
  .btn[disabled] { opacity: .45; cursor: not-allowed; }
  .controls .spacer { flex: 1; }
  .mode-group { display: none; align-items: center; gap: 10px; flex-wrap: wrap; }
  .mode-group.on { display: inline-flex; }

  /* ── scoreboard ─────────────────────────────────────────────────────── */
  .scoreboard {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: 1px; background: var(--line); border-bottom: 1px solid var(--line);
  }
  .stat { background: var(--bg2); padding: 11px 16px; display: flex; flex-direction: column; gap: 3px; }
  .stat .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); }
  .stat .val { font-size: 23px; font-weight: 800; line-height: 1; }
  .stat.asr .val { color: var(--accent); }
  .stat.breach .val { color: var(--red); }
  .stat.def .val { color: var(--green); }
  .stat.sev { gap: 6px; }
  .sevbar { height: 9px; border-radius: 999px; overflow: hidden; background: var(--panel-2); display: flex; border: 1px solid var(--line); }
  .sevbar > span { height: 100%; transition: width .4s ease; }
  .stat.owasp { grid-column: span 2; }
  .owgrid { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
  .owchip {
    font: 700 10px/1 var(--mono); padding: 4px 6px; border-radius: 5px;
    border: 1px solid var(--line); color: var(--muted); background: var(--panel);
  }
  .owchip.hit { color: #fff; background: rgba(244,71,106,.2); border-color: var(--red); }

  /* ── stage ──────────────────────────────────────────────────────────── */
  .stage {
    display: grid; grid-template-columns: minmax(260px, 1fr) minmax(380px, 1.5fr);
    gap: 16px; padding: 16px 20px; align-items: start;
  }
  @media (max-width: 1040px) { .stage { grid-template-columns: 1fr; } }

  .col { display: flex; flex-direction: column; gap: 14px; }
  .colhead {
    display: flex; align-items: baseline; gap: 8px;
    font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin: 0 2px;
  }
  .colhead .c { color: var(--muted-2); }

  /* attacker lanes */
  .lanes { display: flex; flex-direction: column; gap: 10px; }
  .lane {
    border: 1px solid var(--line); border-radius: 12px; padding: 11px 12px;
    background: var(--panel); position: relative; overflow: hidden; cursor: pointer;
    transition: border-color .15s, box-shadow .15s, background .15s;
  }
  .lane:hover { border-color: var(--line-2); background: var(--panel-2); }
  .lane:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .lane::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: var(--line-2);
  }
  .lane.firing { border-color: var(--accent); box-shadow: 0 0 0 1px rgba(92,200,255,.25); }
  .lane.breached::before { background: var(--red); }
  .lane.defended::before { background: var(--green); }
  .lane.src::before { background: var(--accent2); }
  .lane .lh { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .lane .strat { font-weight: 700; font-size: 13px; letter-spacing: .2px; }
  .lane .tech {
    font: 700 10px/1 var(--mono); padding: 3px 7px; border-radius: 999px;
    background: rgba(155,140,255,.14); border: 1px solid var(--line-2); color: #cdc2ff;
  }
  .lane .verdictchip {
    margin-left: auto; font-size: 10px; font-weight: 800; letter-spacing: .4px;
    padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line); white-space: nowrap;
  }
  .verdictchip.breach { color: #fff; background: rgba(244,71,106,.18); border-color: var(--red); }
  .verdictchip.def { color: #fff; background: rgba(52,211,153,.16); border-color: var(--green); }
  .lane .meta {
    margin-top: 7px; display: flex; flex-wrap: wrap; gap: 5px; font-size: 11px; color: var(--muted);
  }
  .tag {
    display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px;
    padding: 3px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted);
    background: var(--panel-2); white-space: nowrap;
  }
  .tag b { color: var(--text); font-weight: 600; }
  .lane .think {
    margin-top: 8px; min-height: 0; font-family: var(--mono);
    font-size: 11px; color: var(--accent); white-space: pre-wrap; word-break: break-word;
    max-height: 0; overflow: hidden; opacity: 0; transition: max-height .2s, opacity .2s;
    border-left: 2px solid var(--line); padding-left: 8px;
  }
  .lane.firing .think, .lane .think.show { max-height: 70px; overflow: auto; opacity: .9; }
  .lane .caret { display: inline-block; width: 7px; background: var(--accent); animation: blink 1s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  /* center feed */
  .feed { display: flex; flex-direction: column; gap: 12px; }
  .turncard { border: 1px solid var(--line); border-radius: 14px; background: var(--panel); overflow: hidden; }
  .turncard .th {
    display: flex; align-items: center; gap: 9px; padding: 9px 13px; border-bottom: 1px solid var(--line);
    background: var(--panel-2); font-size: 12px;
  }
  .turncard .th .who { font-weight: 700; }
  .turncard .th .tn { color: var(--muted); }
  .turncard .th .sev {
    margin-left: auto; font: 800 10px/1 var(--mono); text-transform: uppercase; letter-spacing: .5px;
    padding: 4px 8px; border-radius: 999px; color: #0a0c12;
  }
  .turncard .row { padding: 10px 13px; border-top: 1px solid var(--line); }
  .turncard .row:first-of-type { border-top: 0; }
  .turncard .row .k { font-size: 10px; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); margin-bottom: 4px; }
  .turncard .row .v { white-space: pre-wrap; word-break: break-word; font-size: 12.5px; }
  .turncard .row.resp .v { color: #cfe9ff; }
  .turncard .row.evi { background: rgba(244,71,106,.06); }
  .turncard .row.evi.def { background: rgba(52,211,153,.05); }
  .turncard .row.evi blockquote {
    margin: 0; padding: 6px 10px; border-left: 3px solid var(--red); font-style: italic; color: #ffd7df;
    font-family: var(--mono); font-size: 12px; white-space: pre-wrap; word-break: break-word;
  }
  .turncard .row.evi.def blockquote { border-left-color: var(--green); color: #c7f5e3; }

  /* findings table */
  .panel { border: 1px solid var(--line); border-radius: 14px; padding: 13px 15px; background: var(--panel); }
  .panel h3 { margin: 0 0 11px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  table.findings { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  table.findings th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--line); }
  table.findings td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  table.findings tbody tr { transition: background .14s; }
  table.findings tbody tr:hover { background: var(--row-hover); }
  table.findings tr:last-child td { border-bottom: 0; }
  table.findings .sevpill { font: 800 10px/1 var(--mono); text-transform: uppercase; padding: 3px 7px; border-radius: 999px; color: #0a0c12; }
  table.findings code { font-family: var(--mono); color: var(--muted); font-size: 11px; }
  .empty { color: var(--muted); padding: 10px 2px; font-size: 12.5px; }
  .loading { color: var(--accent); padding: 10px 2px; font-size: 12.5px; }

  /* ── drawer ─────────────────────────────────────────────────────────── */
  .scrim { position: fixed; inset: 0; background: rgba(3,4,8,.62); backdrop-filter: blur(3px); opacity: 0; pointer-events: none; transition: opacity .2s; z-index: 40; }
  .scrim.open { opacity: 1; pointer-events: auto; }
  .drawer {
    position: fixed; top: 0; right: 0; height: 100%; width: min(960px, 96vw);
    background: var(--bg2); border-left: 1px solid var(--line);
    transform: translateX(102%); transition: transform .26s cubic-bezier(.2,.8,.2,1);
    z-index: 41; box-shadow: var(--shadow); display: flex; flex-direction: column;
  }
  .drawer.open { transform: translateX(0); }
  .drawer .dh { display: flex; align-items: center; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--line); }
  .drawer .dh strong { font-size: 15px; }
  .drawer .dh .x { margin-left: auto; cursor: pointer; color: var(--muted); border: 1px solid var(--line); border-radius: 8px; padding: 5px 11px; }
  .drawer .dh .x:hover { color: var(--text); background: var(--panel-2); }
  .drawer .split { display: grid; grid-template-columns: 1fr 1fr; gap: 0; flex: 1; overflow: hidden; }
  @media (max-width: 820px) { .drawer .split { grid-template-columns: 1fr; overflow: auto; } }
  .drawer .pane { overflow: auto; padding: 14px 18px; }
  .drawer .pane.left { border-right: 1px solid var(--line); }
  .drawer .paneh { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin: 0 0 10px; }

  /* timeline */
  .tl { display: flex; flex-direction: column; gap: 10px; }
  .tlturn { border: 1px solid var(--line); border-radius: 11px; background: var(--panel); overflow: hidden; }
  .tlturn.breach { border-color: var(--red); box-shadow: 0 0 0 1px rgba(244,71,106,.2); }
  .tlturn .tlh { display: flex; align-items: center; gap: 8px; padding: 7px 11px; background: var(--panel-2); font-size: 11.5px; }
  .tlturn .tlh .n { font-weight: 800; color: var(--accent); }
  .tlturn .tlh .vb { margin-left: auto; font: 800 10px/1 var(--mono); text-transform: uppercase; padding: 3px 7px; border-radius: 999px; }
  .tlturn .tlh .vb.breach { color: #fff; background: rgba(244,71,106,.2); border: 1px solid var(--red); }
  .tlturn .tlh .vb.def { color: #fff; background: rgba(52,211,153,.16); border: 1px solid var(--green); }
  .tlturn .seg { padding: 8px 11px; border-top: 1px solid var(--line); }
  .tlturn .seg .k { font-size: 9.5px; text-transform: uppercase; letter-spacing: .7px; color: var(--muted); margin-bottom: 3px; }
  .tlturn .seg .v { white-space: pre-wrap; word-break: break-word; font-size: 12px; font-family: var(--mono); }
  .tlturn .seg.resp .v { color: #cfe9ff; }

  /* root cause / trace */
  .trace-ctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .ladder { display: flex; flex-direction: column; gap: 10px; }
  .rung { border: 1px solid var(--line); border-radius: 11px; overflow: hidden; background: var(--panel); }
  .rung .rh { display: flex; align-items: center; gap: 9px; padding: 8px 11px; }
  .rung .state {
    width: 11px; height: 11px; border-radius: 3px; flex: 0 0 auto; border: 1px solid rgba(255,255,255,.18);
  }
  .rung.broken { border-color: var(--red); }
  .rung.broken .state { background: var(--red); }
  .rung.weak .state { background: var(--amber); }
  .rung.held .state { background: var(--green); }
  .rung.na .state { background: var(--muted-2); }
  .rung .rname { font-weight: 700; font-size: 12.5px; }
  .rung .floc { margin-left: auto; font: 11px/1 var(--mono); color: var(--muted); }
  .rung .swrap { display: grid; grid-template-columns: 1fr; }
  .rung .why { padding: 0 11px 8px; font-size: 12px; color: var(--muted); }
  .rung .why.broken { color: #ffc7d2; }
  .rung pre.snip {
    margin: 0; border-top: 1px solid var(--line); background: var(--bg); padding: 9px 11px;
    font-family: var(--mono); font-size: 11.5px; white-space: pre; overflow: auto; color: var(--text);
    counter-reset: none;
  }
  .rung pre.diff { margin: 0; border-top: 1px solid var(--line); background: #100c12; padding: 9px 11px; font-family: var(--mono); font-size: 11.5px; white-space: pre; overflow: auto; }
  .rung pre.diff .add { color: #6ee7a8; }
  .rung pre.diff .del { color: #ff9bb0; }
  .rung .fixhead { font: 800 10px/1 var(--mono); text-transform: uppercase; letter-spacing: .6px; color: var(--green); padding: 8px 11px 0; }
  .redbadge { font-size: 11px; color: var(--amber); margin-bottom: 10px; display: inline-flex; align-items: center; gap: 6px; }

  /* honest abstract summary */
  .honest { border: 1px solid var(--line-2); border-radius: 12px; background: var(--panel); padding: 14px; }
  .honest .kv { display: grid; grid-template-columns: 130px 1fr; gap: 6px 12px; margin-bottom: 10px; }
  .honest .kv dt { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); }
  .honest .kv dd { margin: 0; font-size: 13px; }
  .honest .kv dd.control { color: var(--amber); font-weight: 700; }
  .honest .evi blockquote { margin: 4px 0 0; padding: 8px 11px; border-left: 3px solid var(--accent2); font-style: italic; color: #d9d2ff; font-family: var(--mono); font-size: 12px; white-space: pre-wrap; }
  .honest .note { margin-top: 12px; padding: 11px 13px; border: 1px dashed var(--line-2); border-radius: 10px; background: var(--panel-2); font-size: 12.5px; color: var(--text); }
  .honest .note b { color: var(--accent); }

  pre.box { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--mono); font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 9px; padding: 9px 11px; color: var(--text); }
  .miti { border-color: var(--green) !important; }
  .stdtag { display: inline-block; font: 700 10px/1 var(--mono); padding: 3px 7px; border-radius: 5px; border: 1px solid var(--line); color: var(--muted); margin-right: 6px; }

  .banner { padding: 10px 16px; border-radius: 10px; font-size: 13px; margin: 0 20px 6px; }
  .banner.err { background: rgba(244,71,106,.12); border: 1px solid var(--red); color: #ffd7df; }
  .banner.done { background: rgba(92,200,255,.1); border: 1px solid var(--accent); color: #cdeeff; }
  .confirm { border: 1px solid var(--amber); border-radius: 10px; background: rgba(245,196,81,.08); padding: 12px; margin-bottom: 12px; font-size: 12.5px; }
  .confirm .row { display: flex; gap: 8px; margin-top: 9px; }
  .warn403 { border: 1px solid var(--red); border-radius: 10px; background: rgba(244,71,106,.08); padding: 12px; margin-bottom: 12px; font-size: 12.5px; color: #ffd7df; }
</style>
</head>
<body>
__ARENA_HEADER__
__ARENA_DOCK__

<div class="controls">
  <div class="seg-toggle" role="tablist" aria-label="run source">
    <button id="tab-live" class="on" role="tab" aria-selected="true" onclick="setView('live')">Live</button>
    <button id="tab-replay" role="tab" aria-selected="false" onclick="setView('replay')">Replay</button>
  </div>

  <div class="mode-group on" id="group-live">
    <span class="ctl"><label for="f-profile">Profile</label>
      <select class="field" id="f-profile">
        <option value="quick">quick</option>
        <option value="all_frontier">all_frontier</option>
        <option value="jailbreak">jailbreak</option>
        <option value="injection">injection</option>
      </select></span>
    <span class="ctl"><label for="f-sources">OSS sources <span class="tip tip-left" tabindex="0" role="img" aria-label="Extra probe sources folded in beside the LLM attackers (catalog needs no deps; garak/pyrit/deepteam need the [redteam] extra; dataset:&lt;name&gt; fetches on demand)." data-tip="Extra probe sources folded in beside the LLM attackers (catalog needs no deps; garak/pyrit/deepteam need the [redteam] extra; dataset:&lt;name&gt; fetches on demand)." title="Extra probe sources folded in beside the LLM attackers (catalog needs no deps; garak/pyrit/deepteam need the [redteam] extra; dataset:&lt;name&gt; fetches on demand).">?</span></label>
      <input class="field" id="f-sources" placeholder="e.g. catalog, garak, dataset:advbench" />
      <span class="chips" id="source-chips">
        <button type="button" class="chip" onclick="addSource('catalog')">+catalog</button>
        <button type="button" class="chip" onclick="addSource('garak')">+garak</button>
        <button type="button" class="chip" onclick="addSource('pyrit')">+pyrit</button>
        <button type="button" class="chip" onclick="addSource('deepteam')">+deepteam</button>
        <button type="button" class="chip" onclick="addSource('dataset:advbench')">+dataset:advbench</button>
      </span></span>
    <label class="check"><input type="checkbox" id="f-mock" checked /> mock (offline)</label>
    <button class="btn primary" id="btn-connect" onclick="connect()">Connect</button>
    <button class="btn danger" id="btn-stop" onclick="stopLive()" disabled>Stop</button>
    <span class="tag" id="custom-roster" style="display:none;border-color:var(--accent2);color:#cdc2ff">
      <b id="custom-roster-label">custom roster</b>
      <span id="custom-roster-clear" title="clear back to the selected built-in profile"
            style="cursor:pointer;margin-left:4px">&#10005;</span></span>
  </div>

  <div class="mode-group" id="group-replay">
    <span class="ctl"><label for="f-run">Run</label>
      <select class="field" id="f-run" onchange="loadReplay(this.value)"><option value="">— select a saved run —</option></select></span>
    <button class="btn" id="btn-refresh" onclick="loadRunList()">Refresh</button>
    <button class="btn" id="btn-play" onclick="playReplay()" disabled>Re-animate</button>
  </div>

  <span class="spacer"></span>
  <span class="pill" id="status-pill"><span class="dot" id="status-dot"></span><b id="status-text">idle</b></span>
  <span class="pill" id="run-pill" style="display:none">run <b id="run-id" class="nums">—</b></span>
</div>

<div class="scoreboard">
  <div class="stat asr"><span class="lbl">ASR</span><span class="val nums" id="s-asr">—</span></div>
  <div class="stat"><span class="lbl">Attacks</span><span class="val nums" id="s-attacks">0</span></div>
  <div class="stat breach"><span class="lbl">Breaches</span><span class="val nums" id="s-breach">0</span></div>
  <div class="stat def"><span class="lbl">Defended</span><span class="val nums" id="s-def">0</span></div>
  <div class="stat sev"><span class="lbl">Severity</span><div class="sevbar" id="sevbar" title="breaches by severity"></div></div>
  <div class="stat owasp"><span class="lbl">OWASP coverage</span><div class="owgrid" id="owgrid"></div></div>
</div>

<div id="banner-slot"></div>

<div class="stage">
  <div class="col">
    <div class="colhead">Attackers <span class="c" id="lane-count"></span></div>
    <div class="lanes" id="lanes"><div class="empty">No agents yet. Connect a live run or pick a replay.</div></div>
  </div>

  <div class="col">
    <div class="colhead">Probe &#8594; response &#8594; verdict</div>
    <div class="feed" id="feed"><div class="empty">Live probes and verdicts will stream here.</div></div>
    <div class="panel">
      <h3>Findings</h3>
      <div id="findings"><div class="empty">No vulnerability classes surfaced yet.</div></div>
    </div>
  </div>
</div>

<div class="scrim" id="scrim" onclick="closeDrawer()"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="attacker drill-down">
  <div class="dh">
    <strong id="dr-title">Attacker</strong>
    <span class="x" onclick="closeDrawer()">close &#10005;</span>
  </div>
  <div class="split">
    <div class="pane left">
      <p class="paneh">Multi-turn timeline</p>
      <div class="tl" id="dr-timeline"><div class="empty">No turns recorded.</div></div>
    </div>
    <div class="pane right">
      <p class="paneh">Root cause</p>
      <div id="dr-trace"></div>
    </div>
  </div>
</aside>

<script>
"use strict";
var CONFIG = __ARENA_CONFIG__;

// ── safe helpers ────────────────────────────────────────────────────────
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
function getCss(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888"; }

// ── provider / model dropdowns (GET /api/providers, cached) ──────────────
// Each provider: {id,label,available,reason,needs_key,models,default_model,
// allow_custom,base_url?}. Used by the Trace-in-code panel.
var CUSTOM_OPT = "__custom__";
var _providersCache = null;
function loadProviders() {
  if (_providersCache) return Promise.resolve(_providersCache);
  return fetch("/api/providers").then(function(r){ return r.json(); }).then(function(list){
    _providersCache = Array.isArray(list) ? list : [];
    return _providersCache;
  }).catch(function(){ _providersCache = []; return _providersCache; });
}
function _providerById(id) {
  return (_providersCache || []).filter(function(p){ return p.id === id; })[0] || null;
}
// opts: {providerSel, modelSel, customInput, notice, preferLocal}
function initProviderSelects(opts) {
  var provEl = $(opts.providerSel), modelEl = $(opts.modelSel);
  if (!provEl || !modelEl) return;
  loadProviders().then(function(providers){
    var noticeEl = opts.notice ? $(opts.notice) : null;
    var anyAvailable = providers.some(function(p){ return p.available; });
    if (!providers.length || !anyAvailable) {
      if (noticeEl) noticeEl.innerHTML = '<div class="empty" style="text-align:left">'
        + 'No providers configured — run <code>polygraph init</code>, set an API key, or start Ollama.</div>';
    } else if (noticeEl) { noticeEl.innerHTML = ""; }

    var defId = "";
    if (opts.preferLocal) {
      var local = providers.filter(function(p){ return p.id === "ollama" && p.available; })[0];
      if (local) defId = local.id;
    }
    if (!defId) { var a = providers.filter(function(p){ return p.available; })[0]; if (a) defId = a.id; }
    if (!defId && providers.length) defId = providers[0].id;

    provEl.innerHTML = providers.map(function(p){
      var dis = p.available ? "" : " disabled";
      var why = p.available ? "" : (p.reason ? " — " + p.reason : " (unavailable)");
      var sel = (p.id === defId) ? " selected" : "";
      return '<option value="' + esc(p.id) + '"' + dis + sel + '>' + esc(p.label || p.id) + esc(why) + '</option>';
    }).join("");
    provEl.onchange = function(){ fillModelSelect(opts); };
    fillModelSelect(opts);
  });
}
function fillModelSelect(opts) {
  var provEl = $(opts.providerSel), modelEl = $(opts.modelSel);
  var customEl = opts.customInput ? $(opts.customInput) : null;
  if (!provEl || !modelEl) return;
  var p = _providerById(provEl.value);
  var models = (p && p.models) || [];
  var def = p && p.default_model;
  var html = models.map(function(m){
    return '<option value="' + esc(m) + '"' + (m === def ? " selected" : "") + '>' + esc(m) + '</option>';
  }).join("");
  if (!models.length) html = '<option value="">(provider default)</option>';
  if (p && p.allow_custom) html += '<option value="' + CUSTOM_OPT + '">custom…</option>';
  modelEl.innerHTML = html;
  modelEl.onchange = function(){
    if (customEl) customEl.style.display = (modelEl.value === CUSTOM_OPT) ? "" : "none";
  };
  if (customEl) customEl.style.display = "none";
}
function resolveProvider(id) { var el = $(id); return (el && el.value) ? el.value : ""; }
function resolveModel(modelSelId, customInputId) {
  var el = $(modelSelId);
  if (!el) return "";
  if (el.value === CUSTOM_OPT) {
    var c = customInputId ? $(customInputId) : null;
    return ((c && c.value) || "").trim();
  }
  return el.value || "";
}
var SEV = ["none", "low", "medium", "high", "critical"];
var SEV_RANK = { none: 0, low: 1, medium: 2, high: 3, critical: 4 };
function sevColor(s) {
  var m = { none: "--sev-none", low: "--sev-low", medium: "--sev-medium", high: "--sev-high", critical: "--sev-critical" };
  return getCss(m[s] || "--sev-medium");
}
function prettyStrat(s) { return String(s || "agent").replace(/_/g, " "); }
// Plain-language explanation for an attacker's escalation mode (pair/crescendo).
function attackerModeTip(mode) {
  var base = "pair = iteratively refine against the target's refusal; crescendo = escalate gradually across turns.";
  var m = String(mode || "").toLowerCase();
  if (m === "pair") return "pair = iteratively refine against the target's refusal. " + base;
  if (m === "crescendo") return "crescendo = escalate gradually across turns. " + base;
  return base;
}
function backendLabel(m) {
  if (!m) return "";
  var p = m.provider || "";
  var mo = m.model ? (" / " + m.model) : "";
  return (p + mo).trim();
}
var OWASP_LLM = ["LLM01","LLM02","LLM03","LLM04","LLM05","LLM06","LLM07","LLM08","LLM09","LLM10"];

// ── state ───────────────────────────────────────────────────────────────
// attackers[aid] = { strategy, provider, model, mode, intensity, persona, technique,
//                    source, isSource, breached, turns: { turn -> {turn,prompt,response,verdict,root_cause} } }
var attackers = {};
var laneEls = {};        // aid -> lane DOM node
var counts = { attacks: 0, breaches: 0, defended: 0 };
var sevCounts = { none: 0, low: 0, medium: 0, high: 0, critical: 0 };
var owaspBreached = {};
var vulns = {};
var runId = null;
var view = "live";
var ended = false;
var customRosterRef = null;   // active AI-designed roster ref (?profile_ref=)
var savedEvents = null;  // replay event log for re-animation
var replayTimer = null;

function ensureAttacker(aid, strat, meta) {
  meta = meta || {};
  var a = attackers[aid];
  if (!a) {
    a = attackers[aid] = {
      strategy: strat || meta.strategy || "agent",
      provider: meta.provider, model: meta.model, mode: meta.mode,
      intensity: meta.intensity, persona: meta.persona, converter: meta.converter,
      technique: meta.technique, source: meta.source,
      isSource: (strat === "source") || /^src:/.test(String(aid)),
      breached: false, turns: {}
    };
  } else {
    if (strat && a.strategy === "agent") a.strategy = strat;
    ["provider","model","mode","intensity","persona","technique","source","converter"].forEach(function(k){
      if (meta[k] != null && a[k] == null) a[k] = meta[k];
    });
  }
  renderLane(aid);
  return a;
}
function getTurn(a, turn) {
  var t = (turn == null) ? 1 : turn;
  if (!a.turns[t]) a.turns[t] = { turn: t };
  return a.turns[t];
}

// ── attacker lanes ──────────────────────────────────────────────────────
function renderLane(aid) {
  var a = attackers[aid];
  if (!a) return;
  var lane = laneEls[aid];
  if (!lane) {
    if ($("lanes").querySelector(".empty")) $("lanes").innerHTML = "";
    lane = el("div", "lane");
    lane.id = "lane-" + aid;
    lane.tabIndex = 0;
    lane.setAttribute("role", "button");
    lane.addEventListener("click", function(){ openDrawer(aid); });
    lane.addEventListener("keydown", function(e){ if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(aid); } });
    $("lanes").appendChild(lane);
    laneEls[aid] = lane;
    $("lane-count").textContent = "· " + Object.keys(laneEls).length;
  }
  lane.classList.toggle("src", !!a.isSource);
  lane.classList.toggle("breached", a.breached);
  lane.classList.toggle("defended", !a.breached && Object.keys(a.turns).length > 0 && hasVerdict(a));

  var techTxt = a.technique || a.source || (a.isSource ? "source" : "");
  var turnsArr = turnList(a);
  var lastV = lastVerdict(a);
  var html = '<div class="lh">'
    + '<span class="strat">' + esc(prettyStrat(a.strategy)) + '</span>'
    + (techTxt ? '<span class="tech">' + esc(techTxt) + '</span>' : '');
  if (lastV) {
    var br = !!lastV.breached, sv = lastV.severity || (br ? "medium" : "none");
    html += '<span class="verdictchip ' + (br ? "breach" : "def") + '">' + (br ? ("BREACH · " + esc(sv)) : "defended") + '</span>';
  }
  html += '</div><div class="meta">';
  var bl = backendLabel(a);
  if (bl) html += '<span class="tag"><b>' + esc(bl) + '</b></span>';
  if (a.intensity) html += '<span class="tag">intensity <b>' + esc(a.intensity) + '</b></span>';
  if (a.mode) html += '<span class="tag" title="' + esc(attackerModeTip(a.mode)) + '">mode <b>' + esc(a.mode) + '</b></span>';
  if (a.converter) html += '<span class="tag" title="Transforms a probe (base64, rot13, many-shot, …) to test whether a guardrail can be evaded by encoding the same intent.">converter <b>' + esc(a.converter) + '</b></span>';
  if (turnsArr.length) html += '<span class="tag">turns <b>' + turnsArr.length + '</b></span>';
  html += '</div>';
  html += '<div class="think" id="think-' + esc(aid) + '"></div>';
  lane.innerHTML = html;
}
function hasVerdict(a) { return turnList(a).some(function(t){ return t.verdict; }); }
function turnList(a) {
  return Object.keys(a.turns).map(function(k){ return a.turns[k]; })
    .sort(function(x,y){ return (x.turn||0) - (y.turn||0); });
}
function lastVerdict(a) {
  var tl = turnList(a).filter(function(t){ return t.verdict; });
  return tl.length ? tl[tl.length-1].verdict : null;
}

// ── live event handlers ─────────────────────────────────────────────────
function onProfile(ev) {
  var d = ev.data || {};
  (d.attackers || []).forEach(function(a) {
    ensureAttacker(a.id, a.strategy, {
      provider: a.provider, model: a.model, intensity: a.intensity,
      persona: a.persona, mode: a.mode, converter: a.converter
    });
  });
}
function onSpawn(ev) {
  var d = ev.data || {};
  ensureAttacker(ev.attacker_id, ev.strategy, {
    provider: d.provider, model: d.model, intensity: d.intensity,
    mode: d.mode, converter: d.converter, source: d.source
  });
}
function onThinking(ev) {
  var a = ensureAttacker(ev.attacker_id, ev.strategy, null);
  var lane = laneEls[ev.attacker_id];
  if (lane) lane.classList.add("firing");
  var t = getTurn(a, ev.turn);
  if (t._think == null) t._think = "";
  t._think += (ev.delta || "");
  var box = $("think-" + ev.attacker_id);
  if (box) { box.innerHTML = esc(t._think) + '<span class="caret">&nbsp;</span>'; }
}
function onAttack(ev) {
  var d = ev.data || {};
  var a = ensureAttacker(ev.attacker_id, ev.strategy, { technique: d.technique, source: d.source });
  var lane = laneEls[ev.attacker_id];
  if (lane) lane.classList.add("firing");
  var t = getTurn(a, ev.turn);
  t.prompt = ev.text || "";
  renderLane(ev.attacker_id);
  pushFeed(ev.attacker_id, t.turn);
}
function onResponse(ev) {
  var a = ensureAttacker(ev.attacker_id, ev.strategy, null);
  var t = getTurn(a, ev.turn);
  t.response = ev.text || "";
  if (ev.data && ev.data.error) t.error = ev.data.error;
  var lane = laneEls[ev.attacker_id];
  if (lane) lane.classList.remove("firing");
  refreshFeed(ev.attacker_id, t.turn);
}
function onVerdict(ev) {
  var a = ensureAttacker(ev.attacker_id, ev.strategy, null);
  var t = getTurn(a, ev.turn);
  var v = ev.verdict || {};
  t.verdict = v;
  if (ev.data && ev.data.root_cause) t.root_cause = ev.data.root_cause;
  counts.attacks++;
  var breached = !!v.breached;
  var sev = v.severity || (breached ? "medium" : "none");
  if (breached) { counts.breaches++; a.breached = true; sevCounts[sev] = (sevCounts[sev]||0)+1; }
  else { counts.defended++; }
  renderLane(ev.attacker_id);
  refreshFeed(ev.attacker_id, t.turn);
  updateScore();
}
function onVuln(ev) {
  var d = ev.data || {};
  if (!d.vuln_class) return;
  vulns[d.vuln_class] = d;
  if (d.owasp) String(d.owasp).split(/[,\s]+/).forEach(function(o){ if (o) markOwasp(o); });
  renderFindings();
}
function onSummary(ev) {
  var d = ev.data || {};
  if (typeof d.attacks === "number") counts.attacks = d.attacks;
  if (typeof d.breaches === "number") counts.breaches = d.breaches;
  if (typeof d.defended === "number") counts.defended = d.defended;
  if (d.by_severity) Object.keys(d.by_severity).forEach(function(s){ sevCounts[s] = d.by_severity[s]; });
  (d.owasp_breached || []).forEach(markOwasp);
  if (typeof d.asr === "number") setAsr(d.asr);
  updateScore(typeof d.asr === "number" ? d.asr : null);
  renderFindings();
}
function onDone(ev) {
  ended = true;
  setStatus("done", "run complete");
  var d = ev.data || {};
  if (d.run_id) { runId = d.run_id; showRunId(runId); }
  banner("done", "Run complete — " + counts.breaches + " breach(es), " + counts.defended + " defended"
    + (d.vulnerabilities != null ? (", " + d.vulnerabilities + " vulnerability class(es).") : "."));
  Object.keys(laneEls).forEach(function(k){ laneEls[k].classList.remove("firing"); });
  setLiveButtons(false);
  closeStream();
}
function onError(ev) {
  ended = true;
  setStatus("err", "stream error");
  var d = ev.data || {};
  banner("err", "Stream error: " + ((d && d.message) || (ev && ev.text) || "unknown"));
  setLiveButtons(false);
  closeStream();
}

// ── center feed ─────────────────────────────────────────────────────────
function feedKey(aid, turn) { return aid + "#" + (turn == null ? "?" : turn); }
function pushFeed(aid, turn) {
  if ($("feed").querySelector(".empty")) $("feed").innerHTML = "";
  var key = feedKey(aid, turn);
  if (!$("tc-" + cssId(key))) {
    var card = el("div", "turncard");
    card.id = "tc-" + cssId(key);
    $("feed").appendChild(card);
    // keep the feed bounded
    var cards = $("feed").querySelectorAll(".turncard");
    if (cards.length > 24) cards[0].remove();
  }
  refreshFeed(aid, turn);
}
function cssId(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, "_"); }
function refreshFeed(aid, turn) {
  var a = attackers[aid]; if (!a) return;
  var t = a.turns[turn == null ? 1 : turn]; if (!t) return;
  var card = $("tc-" + cssId(feedKey(aid, turn)));
  if (!card) { pushFeed(aid, turn); card = $("tc-" + cssId(feedKey(aid, turn))); if (!card) return; }
  var v = t.verdict || null;
  var br = v && !!v.breached, sev = v ? (v.severity || (br ? "medium" : "none")) : null;
  var html = '<div class="th"><span class="who">' + esc(prettyStrat(a.strategy)) + '</span>'
    + '<span class="tn">· turn ' + esc(t.turn) + '</span>';
  if (v) { html += '<span class="sev" style="background:' + sevColor(sev) + '">' + (br ? "breach" : "defended") + ' · ' + esc(sev) + '</span>'; }
  html += '</div>';
  if (t.prompt != null) html += '<div class="row"><div class="k">Probe</div><div class="v">' + esc(t.prompt) + '</div></div>';
  if (t.response != null || t.error) html += '<div class="row resp"><div class="k">Target response</div><div class="v">' + esc(t.error ? ("[error] " + t.error) : t.response) + '</div></div>';
  if (v && v.evidence) html += '<div class="row evi ' + (br ? "" : "def") + '"><div class="k">Evidence</div><blockquote>' + esc(v.evidence) + '</blockquote></div>';
  else if (v && v.rationale) html += '<div class="row"><div class="k">Judge rationale</div><div class="v">' + esc(v.rationale) + '</div></div>';
  card.innerHTML = html;
}

// ── scoreboard ──────────────────────────────────────────────────────────
function setAsr(asr) { $("s-asr").textContent = (Math.round(asr * 1000) / 10) + "%"; }
function updateScore(asr) {
  $("s-attacks").textContent = counts.attacks;
  $("s-breach").textContent = counts.breaches;
  $("s-def").textContent = counts.defended;
  if (asr == null && counts.attacks > 0) setAsr(counts.breaches / counts.attacks);
  renderSevBar();
  renderOwasp();
}
function renderSevBar() {
  var bar = $("sevbar"); bar.innerHTML = "";
  var total = 0; ["low","medium","high","critical"].forEach(function(s){ total += (sevCounts[s]||0); });
  if (!total) { bar.innerHTML = '<span style="width:100%;background:var(--panel-2)"></span>'; return; }
  ["low","medium","high","critical"].forEach(function(s){
    var n = sevCounts[s] || 0; if (!n) return;
    var seg = el("span");
    seg.style.width = (100 * n / total) + "%";
    seg.style.background = sevColor(s);
    seg.title = s + ": " + n;
    bar.appendChild(seg);
  });
}
function markOwasp(code) {
  var m = String(code || "").match(/LLM\d{2}/i);
  if (m) { owaspBreached[m[0].toUpperCase()] = true; renderOwasp(); }
}
function renderOwasp() {
  var g = $("owgrid"); g.innerHTML = "";
  OWASP_LLM.forEach(function(o){
    var c = el("span", "owchip" + (owaspBreached[o] ? " hit" : ""), o);
    c.title = owaspBreached[o] ? (o + " — breached") : (o + " — not breached");
    g.appendChild(c);
  });
}

// ── findings table ──────────────────────────────────────────────────────
function renderFindings() {
  var box = $("findings");
  var list = Object.keys(vulns).map(function(k){ return vulns[k]; });
  if (!list.length) { box.innerHTML = '<div class="empty">No vulnerability classes surfaced yet.</div>'; return; }
  list.sort(function(a,b){ return (SEV_RANK[b.severity]||0) - (SEV_RANK[a.severity]||0); });
  var html = '<table class="findings"><thead><tr>'
    + '<th>Class</th><th>Sev</th><th>Count</th><th>OWASP / ATLAS</th><th>Mitigation</th></tr></thead><tbody>';
  list.forEach(function(v){
    var sv = v.severity || "medium";
    html += '<tr><td><b>' + esc(prettyStrat(v.vuln_class)) + '</b></td>'
      + '<td><span class="sevpill" style="background:' + sevColor(sv) + '">' + esc(sv) + '</span></td>'
      + '<td class="nums">' + esc(v.count || 0) + '</td>'
      + '<td><code>' + esc(v.owasp || "—") + (v.atlas ? (" / " + esc(v.atlas)) : "") + '</code></td>'
      + '<td>' + esc(v.mitigation || "—") + '</td></tr>';
  });
  html += '</tbody></table>';
  if (runId) html += '<div class="empty">Saved as run <code>' + esc(runId) + '</code>.</div>';
  box.innerHTML = html;
}

// ── drill-down drawer ───────────────────────────────────────────────────
var drawerAid = null;
function openDrawer(aid) {
  var a = attackers[aid]; if (!a) return;
  drawerAid = aid;
  $("dr-title").textContent = prettyStrat(a.strategy) + (a.breached ? "  ·  BREACHED" : "  ·  defended");
  renderTimeline(a);
  renderTracePanel(aid);
  $("scrim").classList.add("open");
  $("drawer").classList.add("open");
}
function closeDrawer() { $("scrim").classList.remove("open"); $("drawer").classList.remove("open"); drawerAid = null; }
document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDrawer(); });

function renderTimeline(a) {
  var box = $("dr-timeline");
  var turns = turnList(a);
  if (!turns.length) { box.innerHTML = '<div class="empty">No turns recorded.</div>'; return; }
  box.innerHTML = "";
  turns.forEach(function(t){
    var v = t.verdict || null;
    var br = v && !!v.breached;
    var card = el("div", "tlturn" + (br ? " breach" : ""));
    var sv = v ? (v.severity || (br ? "medium" : "none")) : null;
    var head = '<div class="tlh"><span class="n">turn ' + esc(t.turn) + '</span>';
    if (v) head += '<span class="vb ' + (br ? "breach" : "def") + '">' + (br ? ("breach · " + esc(sv)) : "defended") + '</span>';
    head += '</div>';
    var inner = head;
    if (t.prompt != null) inner += '<div class="seg"><div class="k">Probe</div><div class="v">' + esc(t.prompt) + '</div></div>';
    if (t.response != null || t.error) inner += '<div class="seg resp"><div class="k">Response</div><div class="v">' + esc(t.error ? ("[error] " + t.error) : t.response) + '</div></div>';
    if (v && v.evidence) inner += '<div class="seg"><div class="k">Evidence</div><div class="v">' + esc(v.evidence) + '</div></div>';
    if (v && v.rationale) inner += '<div class="seg"><div class="k">Judge rationale</div><div class="v">' + esc(v.rationale) + '</div></div>';
    card.innerHTML = inner;
    box.appendChild(card);
  });
}

function renderTracePanel(aid) {
  var box = $("dr-trace");
  var canTrace = !!runId;
  var html = '<div class="trace-ctl">'
    + '<span class="ctl" style="flex:1 1 100%"><label for="tr-codepath">Code path <span class="tip" tabindex="0" role="img" aria-label="A local checkout of the target. Indexed read-only; excerpts are secret-scrubbed and only sent to the chosen model. Enables the code-grounded root-cause ladder; blank = the finding summary." data-tip="A local checkout of the target. Indexed read-only; excerpts are secret-scrubbed and only sent to the chosen model. Enables the code-grounded root-cause ladder; blank = the finding summary." title="A local checkout of the target. Indexed read-only; excerpts are secret-scrubbed and only sent to the chosen model. Enables the code-grounded root-cause ladder; blank = the finding summary.">?</span></label>'
    + '<input class="field" id="tr-codepath" placeholder="/path/to/target/checkout (optional — enables the code-grounded ladder)" style="width:100%" /></span>'
    + '<span class="ctl"><label for="tr-provider">Provider</label>'
    + '<select class="field" id="tr-provider" style="min-width:120px"><option>loading…</option></select></span>'
    + '<span class="ctl"><label for="tr-model">Model</label>'
    + '<select class="field" id="tr-model" style="min-width:120px"><option>—</option></select>'
    + '<input class="field" id="tr-model-custom" placeholder="custom model" style="min-width:120px;display:none" /></span>'
    + '<button class="btn primary" id="tr-go"' + (canTrace ? "" : " disabled") + '>Trace in code</button>'
    + '</div>';
  html += '<div id="tr-provider-notice"></div>';
  if (!canTrace) html += '<div class="empty">Trace becomes available once the run has a <code>run_id</code> (after it completes, or in replay).</div>';
  else html += '<div class="empty">Point <b>Code path</b> at a local checkout to get the code-grounded ladder; with the provider on a local model, source never leaves the machine. No path → the honest finding summary.</div>';
  box.innerHTML = html;
  // populate provider/model dropdowns; prefer a local provider (ollama) so the
  // IP-safe default keeps source on-machine.
  initProviderSelects({
    providerSel: "tr-provider", modelSel: "tr-model", customInput: "tr-model-custom",
    notice: "tr-provider-notice", preferLocal: true,
  });
  var go = $("tr-go");
  if (go) go.addEventListener("click", function(){ runTrace(aid, false); });
}

function runTrace(aid, consent) {
  var box = $("dr-trace");
  var provider = resolveProvider("tr-provider") || "ollama";
  var model = resolveModel("tr-model", "tr-model-custom") || null;
  var ctlHtml = box.querySelector(".trace-ctl") ? box.querySelector(".trace-ctl").outerHTML : "";
  box.innerHTML = ctlHtml + '<div class="loading">Tracing root cause in code…</div>';
  rebindTrace(aid);

  var codePath = ($("tr-codepath") && $("tr-codepath").value || "").trim() || null;
  var body = { run_id: runId, attacker_id: aid, provider: provider };
  if (model) body.model = model;
  if (codePath) body.code_path = codePath;
  if (consent) body.consent = true;

  fetch("/api/redteam/trace", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  }).then(function(r){
    return r.json().then(function(j){ return { status: r.status, body: j }; });
  }).then(function(res){
    var j = res.body || {};
    if (res.status === 403) { renderAirGap(box, aid, j); return; }
    if (res.status === 400 && j.needs_consent) { renderConsent(box, aid, j); return; }
    if (res.status >= 400) { box.innerHTML = ctlHtml + '<div class="warn403">Trace failed: ' + esc(j.error || ("HTTP " + res.status)) + '</div>'; rebindTrace(aid); return; }
    if (j.mode === "code") renderLadder(box, j);
    else renderHonest(box, j);
  }).catch(function(e){
    box.innerHTML = ctlHtml + '<div class="warn403">Trace request failed: ' + esc(String(e)) + '</div>';
    rebindTrace(aid);
  });
}
function rebindTrace(aid) {
  var go = $("tr-go");
  if (go) go.addEventListener("click", function(){ runTrace(aid, false); });
}
function renderConsent(box, aid, j) {
  var prov = j.provider || "remote";
  box.innerHTML = '<div class="confirm"><b>Consent required.</b> This uploads source excerpts to '
    + '<code>' + esc(prov) + '</code> (a non-local provider). Continue?'
    + '<div class="row"><button class="btn primary" id="cf-yes">Yes, send to ' + esc(prov) + '</button>'
    + '<button class="btn" id="cf-no">Cancel</button></div></div>';
  $("cf-yes").addEventListener("click", function(){ runTrace(aid, true); });
  $("cf-no").addEventListener("click", function(){ renderTracePanel(aid); });
}
function renderAirGap(box, aid, j) {
  box.innerHTML = '<div class="warn403">Air-gap is on — code dives are restricted to a local model. '
    + 'Set the provider to a local one (ollama, vllm, lmstudio) and try again.</div>'
    + '<button class="btn" id="ag-back">Back</button>';
  $("ag-back").addEventListener("click", function(){ renderTracePanel(aid); });
}

// HONESTY RULE: mode==="code" -> colored ladder of REAL file:line rungs.
function renderLadder(box, j) {
  var html = "";
  if (typeof j.redactions === "number") html += '<div class="redbadge">&#9632; ' + esc(j.redactions) + ' secret(s) redacted before send</div>';
  html += '<div class="ladder">';
  (j.ladder || []).forEach(function(rung){
    var st = (rung.state || "na").toLowerCase();
    var floc = rung.file ? (esc(rung.file) + (rung.lines ? (":" + esc(rung.lines)) : "")) : "";
    html += '<div class="rung ' + esc(st) + '">'
      + '<div class="rh"><span class="state"></span><span class="rname">' + esc(rung.name || "stage") + '</span>'
      + (floc ? '<span class="floc">' + floc + '</span>' : '') + '</div>'
      + (rung.why ? '<div class="why ' + (st === "broken" ? "broken" : "") + '">' + esc(rung.why) + '</div>' : '');
    if (rung.snippet) html += '<pre class="snip">' + esc(rung.snippet) + '</pre>';
    if (st === "broken" && j.fix && (j.fix.diff || j.fix.rationale)) {
      html += '<div class="fixhead">Suggested fix' + (j.fix.file ? (" · " + esc(j.fix.file) + (j.fix.locus ? (":" + esc(j.fix.locus)) : "")) : "") + '</div>';
      if (j.fix.diff) html += '<pre class="diff">' + diffHtml(j.fix.diff) + '</pre>';
      if (j.fix.rationale) html += '<div class="why">' + esc(j.fix.rationale) + '</div>';
    }
    html += '</div>';
  });
  html += '</div>';
  html += '<div class="honest" style="margin-top:12px"><dl class="kv">';
  if (j.introduced_at) html += '<dt>Introduced at</dt><dd><code>' + esc(j.introduced_at) + '</code></dd>';
  if (j.severity) html += '<dt>Severity</dt><dd style="color:' + sevColor(j.severity) + '">' + esc(j.severity) + '</dd>';
  if (j.owasp || j.atlas) html += '<dt>Mapping</dt><dd><span class="stdtag">OWASP ' + esc(j.owasp || "—") + '</span><span class="stdtag">ATLAS ' + esc(j.atlas || "—") + '</span></dd>';
  if (j.provider) html += '<dt>Traced via</dt><dd>' + esc(j.provider) + '</dd>';
  html += '</dl>';
  if (j.rationale) html += '<div style="margin-bottom:10px">' + esc(j.rationale) + '</div>';
  if (j.evidence) html += '<div class="evi"><div class="paneh">Evidence</div><blockquote>' + esc(j.evidence) + '</blockquote></div>';
  if (j.mitigation) html += '<div style="margin-top:10px"><div class="paneh">Mitigation</div><pre class="box miti">' + esc(j.mitigation) + '</pre></div>';
  html += '</div>';
  box.innerHTML = html;
}
function diffHtml(diff) {
  return String(diff).split("\n").map(function(ln){
    if (/^\+/.test(ln) && !/^\+\+\+/.test(ln)) return '<span class="add">' + esc(ln) + '</span>';
    if (/^-/.test(ln) && !/^---/.test(ln)) return '<span class="del">' + esc(ln) + '</span>';
    return esc(ln);
  }).join("\n");
}

// HONESTY RULE: mode==="abstract" -> NO colored pipeline. Honest summary only.
function renderHonest(box, j) {
  var html = '<div class="honest"><dl class="kv">';
  html += '<dt>Control to harden</dt><dd class="control">' + esc(j.control || "(none — defended)") + '</dd>';
  if (j.backstop) html += '<dt>Backstop</dt><dd>' + esc(j.backstop) + '</dd>';
  if (j.severity) html += '<dt>Severity</dt><dd style="color:' + sevColor(j.severity) + '">' + esc(j.severity) + '</dd>';
  html += '<dt>Mapping</dt><dd><span class="stdtag">OWASP ' + esc(j.owasp || "—") + '</span><span class="stdtag">ATLAS ' + esc(j.atlas || "—") + '</span></dd>';
  if (j.provider) html += '<dt>Analyzed via</dt><dd>' + esc(j.provider) + '</dd>';
  html += '</dl>';
  if (j.rationale) html += '<div style="margin-bottom:10px">' + esc(j.rationale) + '</div>';
  if (j.evidence) html += '<div class="evi"><div class="paneh">Evidence</div><blockquote>' + esc(j.evidence) + '</blockquote></div>';
  if (j.mitigation) html += '<div style="margin-top:10px"><div class="paneh">Mitigation</div><pre class="box miti">' + esc(j.mitigation) + '</pre></div>';
  if (j.note) html += '<div class="note"><b>No code grounding.</b> ' + esc(j.note) + '</div>';
  html += '</div>';
  box.innerHTML = html;
}

// ── status + banners ────────────────────────────────────────────────────
function setStatus(kind, text) {
  $("status-dot").className = "dot" + (kind === "live" ? " live" : kind === "done" ? " done" : kind === "err" ? " err" : "");
  $("status-text").textContent = text;
}
function banner(kind, text) {
  var slot = $("banner-slot"); slot.innerHTML = "";
  slot.appendChild(el("div", "banner " + kind, text));
}
function clearBanner() { $("banner-slot").innerHTML = ""; }
function showRunId(id) { if (!id) return; $("run-pill").style.display = ""; $("run-id").textContent = id; }

// ── reset / view switching ──────────────────────────────────────────────
function resetState() {
  attackers = {}; laneEls = {}; vulns = {}; owaspBreached = {}; runId = null; ended = false;
  counts = { attacks: 0, breaches: 0, defended: 0 };
  sevCounts = { none: 0, low: 0, medium: 0, high: 0, critical: 0 };
  $("lanes").innerHTML = '<div class="empty">No agents yet. Connect a live run or pick a replay.</div>';
  $("feed").innerHTML = '<div class="empty">Live probes and verdicts will stream here.</div>';
  $("findings").innerHTML = '<div class="empty">No vulnerability classes surfaced yet.</div>';
  $("lane-count").textContent = "";
  $("s-asr").textContent = "—"; $("s-attacks").textContent = "0"; $("s-breach").textContent = "0"; $("s-def").textContent = "0";
  $("run-pill").style.display = "none";
  renderSevBar(); renderOwasp(); clearBanner(); closeDrawer();
}
function setView(v) {
  view = v;
  $("tab-live").classList.toggle("on", v === "live");
  $("tab-replay").classList.toggle("on", v === "replay");
  $("tab-live").setAttribute("aria-selected", v === "live");
  $("tab-replay").setAttribute("aria-selected", v === "replay");
  $("group-live").classList.toggle("on", v === "live");
  $("group-replay").classList.toggle("on", v === "replay");
  stopLive();
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  resetState();
  setStatus("", "idle");
  if (v === "replay") loadRunList();
}

// ── live transport ──────────────────────────────────────────────────────
var es = null, ws = null, reconnects = 0;
var EVENT_TYPES = ["profile","agent_spawned","thinking","attack","response","verdict","vuln","summary","done","error"];
function parseData(raw) { try { return JSON.parse(raw); } catch (e) { return {}; } }
function dispatch(type, payload) {
  try {
    switch (type) {
      case "profile": onProfile(payload); break;
      case "agent_spawned": onSpawn(payload); break;
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
function buildStreamUrl() {
  var base = CONFIG.streamUrl || "/api/redteam/stream";
  if (CONFIG.transport === "ws") return base;  // service hands a ready ws url
  // SSE: rebuild query from controls so Connect reflects the picker.
  var path = base.split("?")[0];
  var params = [];
  params.push("profile=" + encodeURIComponent($("f-profile").value || "quick"));
  params.push("mock=" + ($("f-mock").checked ? "1" : "0"));
  var src = ($("f-sources").value || "").trim();
  if (src) params.push("sources=" + encodeURIComponent(src));
  // An AI-designed roster (built via /api/redteam/profile) runs via profile_ref;
  // the stream honors it in addition to the built-in profile/sources/mock.
  if (customRosterRef) params.push("profile_ref=" + encodeURIComponent(customRosterRef));
  return path + "?" + params.join("&");
}
function setLiveButtons(connected) {
  $("btn-connect").disabled = connected;
  $("btn-stop").disabled = !connected;
}
function addSource(name) {
  var el = $("f-sources");
  if (!el) return;
  var have = el.value.split(",").map(function(s){ return s.trim(); }).filter(Boolean);
  if (have.indexOf(name) === -1) have.push(name);
  el.value = have.join(", ");
}
function connect() {
  if (view !== "live") return;
  resetState();
  setLiveButtons(true);
  if (CONFIG.transport === "ws") startWS(); else startSSE();
}
function startSSE() {
  setStatus("live", "live (SSE)");
  try { es = new EventSource(buildStreamUrl()); }
  catch (e) { setStatus("err", "cannot open stream"); setLiveButtons(false); return; }
  EVENT_TYPES.forEach(function(t){ es.addEventListener(t, function(e){ dispatch(t, parseData(e.data)); }); });
  es.onerror = function() {
    if (ended) return;
    setStatus("", "reconnecting…");
    reconnects++;
    if (reconnects > 8) { closeStream(); setStatus("done", "stream closed"); setLiveButtons(false); }
  };
}
function startWS() {
  setStatus("live", "live (WS)");
  try { ws = new WebSocket(CONFIG.streamUrl); }
  catch (e) { setStatus("err", "cannot open socket"); banner("err", "Could not open WebSocket."); setLiveButtons(false); return; }
  ws.onmessage = function(e) { var msg = parseData(e.data); if (msg && msg.type) dispatch(msg.type, msg); };
  ws.onclose = function() { if (!ended) { setStatus("done", "stream closed"); setLiveButtons(false); } };
  ws.onerror = function() { if (!ended) setStatus("err", "socket error"); };
}
function closeStream() {
  try { if (es) { es.close(); es = null; } } catch (e) {}
  try { if (ws && ws.readyState <= 1) { ws.close(); } ws = null; } catch (e) {}
}
function stopLive() {
  if (es || ws) { ended = true; closeStream(); setStatus("done", "stopped"); }
  setLiveButtons(false);
}

// ── replay ──────────────────────────────────────────────────────────────
function loadRunList() {
  var sel = $("f-run");
  sel.innerHTML = '<option value="">loading…</option>';
  fetch("/api/redteam/runs").then(function(r){ return r.json(); }).then(function(list){
    sel.innerHTML = '<option value="">— select a saved run —</option>';
    (list || []).forEach(function(r){
      var asr = (typeof r.asr === "number") ? (" · " + Math.round(r.asr*100) + "% ASR") : "";
      var o = el("option", null, (r.profile || r.run_id) + " · " + (r.target || "target") + asr);
      o.value = r.run_id;
      sel.appendChild(o);
    });
    if (!list || !list.length) { sel.innerHTML = '<option value="">no saved runs yet</option>'; }
  }).catch(function(){ sel.innerHTML = '<option value="">could not load runs</option>'; });
}
function loadReplay(id) {
  if (!id) return;
  resetState();
  runId = id; showRunId(id);
  savedEvents = null; $("btn-play").disabled = true;
  setStatus("", "loading replay…");
  fetch("/api/redteam/runs/" + encodeURIComponent(id)).then(function(r){ return r.json(); }).then(function(payload){
    var rep = (payload && payload.report) || {};
    var ats = (payload && payload.attackers) || [];
    ats.forEach(function(at){
      var a = ensureAttacker(at.attacker_id, at.strategy, {});
      a.breached = !!at.breached;
      (at.turns || []).forEach(function(t){
        var tt = getTurn(a, t.turn);
        tt.prompt = t.prompt; tt.response = t.response; tt.attempt_id = t.attempt_id;
        if (t.root_cause) tt.root_cause = t.root_cause;
      });
      renderLane(at.attacker_id);
    });
    // verdicts + per-turn meta from the raw attempts in the report
    (rep.attempts || []).forEach(function(ad){
      var a = attackers[ad.attacker_id]; if (!a) a = ensureAttacker(ad.attacker_id, ad.strategy, {});
      a.provider = a.provider || ad.provider; a.model = a.model || ad.model;
      a.mode = a.mode || ad.mode; a.intensity = a.intensity || ad.intensity;
      var tt = getTurn(a, ad.turn != null ? ad.turn : (ad.turn_index != null ? ad.turn_index : 1));
      if (ad.prompt != null && tt.prompt == null) tt.prompt = ad.prompt;
      if (ad.response != null && tt.response == null) tt.response = ad.response;
      if (ad.verdict) tt.verdict = ad.verdict;
      renderLane(ad.attacker_id);
    });
    // scoreboard from stats
    var st = rep.stats || {};
    counts.attacks = st.attacks != null ? st.attacks : (rep.attempts || []).length;
    counts.breaches = st.breaches != null ? st.breaches : 0;
    counts.defended = st.defended != null ? st.defended : Math.max(0, counts.attacks - counts.breaches);
    if (st.by_severity) Object.keys(st.by_severity).forEach(function(s){ sevCounts[s] = st.by_severity[s]; });
    (st.owasp_breached || []).forEach(markOwasp);
    if (typeof rep.asr === "number") setAsr(rep.asr); else if (typeof st.asr === "number") setAsr(st.asr);
    (rep.vulnerabilities || []).forEach(function(v){
      if (v.vuln_class) { vulns[v.vuln_class] = v; if (v.owasp) String(v.owasp).split(/[,\s]+/).forEach(markOwasp); }
    });
    updateScore((typeof rep.asr === "number") ? rep.asr : null);
    renderFindings();
    setStatus("done", "replay loaded");
    banner("done", "Replay of run " + id + " — " + counts.breaches + " breach(es), " + counts.defended + " defended.");
    // fetch events for optional re-animation
    fetch("/api/redteam/runs/" + encodeURIComponent(id) + "/events").then(function(r){ return r.json(); }).then(function(evs){
      if (Array.isArray(evs) && evs.length) { savedEvents = evs; $("btn-play").disabled = false; }
    }).catch(function(){});
  }).catch(function(){ setStatus("err", "could not load replay"); banner("err", "Could not load replay " + id + "."); });
}
function playReplay() {
  if (!savedEvents || !savedEvents.length) return;
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  // reset the visible model but keep runId so trace stays enabled
  var keepRun = runId;
  resetState(); runId = keepRun; showRunId(keepRun);
  setStatus("live", "re-animating");
  var i = 0;
  replayTimer = setInterval(function(){
    if (i >= savedEvents.length) {
      clearInterval(replayTimer); replayTimer = null;
      if (!ended) setStatus("done", "replay finished");
      return;
    }
    var ev = savedEvents[i++];
    if (ev && ev.type) dispatch(ev.type, ev);
  }, 120);
}

// ── AI Designer wiring (context: Red team) ───────────────────────────────
// postJSON helper the shared dock JS expects (the dashboard has its own; the
// Arena defines a minimal one here). Parses JSON even on non-2xx so {error}
// surfaces. Relative URL only — no external origin.
function postJSON(url, body) {
  return fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  }).then(function(r) {
    return r.json().catch(function(){ return null; }).then(function(data) {
      if (!r.ok) {
        var msg = (data && (data.detail || data.error)) || ("HTTP " + r.status);
        throw new Error(msg);
      }
      return data;
    });
  });
}

window.__dkDesignUrl = "/api/redteam/design";

// Render the designed roster as a structured preview (strategy lanes + their
// mode/converter/intensity, sources, turns, guard) — labelled fields, not chat.
window.__dkRenderPreview = function(res) {
  var cfg = res.config || {};
  var secs = "";
  secs += dkSection("Base profile", esc(cfg.base_profile || "deep"), true);
  secs += dkSection("Multi-turn", esc(cfg.turns != null ? cfg.turns : "—") + " turn(s) · guard "
    + (cfg.guard ? "on (Llama-Guard-style judge)" : "off"));
  secs += dkSection("Sources", dkChips(cfg.sources || []));
  var lanes = (cfg.strategies || []).map(function(s) {
    var meta = [];
    if (s.mode) meta.push("mode " + s.mode);
    if (s.converter) meta.push("converter " + s.converter);
    if (s.intensity) meta.push(s.intensity);
    return '<div class="dk-lane"><div class="dk-lane-h">' + esc(prettyStrat(s.strategy)) + '</div>'
      + (meta.length ? '<div class="dk-lane-m">' + esc(meta.join(" · ")) + '</div>' : '') + '</div>';
  }).join("") || '<span class="muted">no strategy lanes</span>';
  secs += '<div class="dk-section"><div class="dk-k">Strategy lanes ('
    + ((cfg.strategies || []).length) + ')</div><div class="dk-v">' + lanes + '</div></div>';
  return dkPreviewShell("Designed red team", res.provider, secs, res.notes);
};

// Inject: set the Live controls from the design AND build a runnable custom
// roster via /api/redteam/profile, stashing the ref so Connect runs it.
window.__dkInject = function(cfg) {
  setView("live");
  // 1) reflect the design in the visible Live controls
  var prof = $("f-profile");
  if (prof && cfg.base_profile) {
    var has = false;
    for (var i = 0; i < prof.options.length; i++) { if (prof.options[i].value === cfg.base_profile) { has = true; break; } }
    if (!has) { var o = el("option", null, cfg.base_profile); o.value = cfg.base_profile; prof.appendChild(o); }
    prof.value = cfg.base_profile;
  }
  var srcEl = $("f-sources");
  if (srcEl && cfg.sources) srcEl.value = (cfg.sources || []).join(", ");
  // turns/guard have no dedicated Live inputs — they ride in the custom roster
  // we build next, so the designed depth + judge actually run.
  _dkStatus("Building runnable roster…", "busy");
  var provider = resolveProvider("dk-provider") || "anthropic";
  var model = resolveModel("dk-model", "dk-model-custom") || null;
  var body = { spec: cfg, provider: provider };
  if (model) body.model = model;
  postJSON("/api/redteam/profile", body).then(function(resp) {
    if (!resp || !resp.ref) { _dkStatus((resp && resp.error) || "could not build roster", "err"); return; }
    customRosterRef = resp.ref;
    var n = (resp.attackers || []).length;
    showCustomRoster(n);
    _dkStatus("Custom roster ready (" + n + " lane(s)). Connect to run it.", "");
    closeDesigner();
  }).catch(function(e) {
    _dkStatus("Could not build roster: " + (e && e.message ? e.message : String(e)), "err");
  });
};

function showCustomRoster(nLanes) {
  var chip = $("custom-roster");
  var lbl = $("custom-roster-label");
  if (lbl) lbl.textContent = "custom roster (" + (nLanes || 0) + " lane" + (nLanes === 1 ? "" : "s") + ")";
  if (chip) chip.style.display = "";
}
function clearCustomRoster() {
  customRosterRef = null;
  var chip = $("custom-roster");
  if (chip) chip.style.display = "none";
}
(function bindCustomRosterClear() {
  var x = $("custom-roster-clear");
  if (x) x.addEventListener("click", function(e){ e.stopPropagation(); clearCustomRoster(); });
})();

// shared dock open/close/Esc + Design→preview→Inject/Refine skeleton
__DESIGNER_DOCK_JS__

// ── boot ────────────────────────────────────────────────────────────────
(function start() {
  renderSevBar(); renderOwasp();
  // Readiness pill (shared init). The endpoint path is assembled at runtime so
  // this self-contained page never embeds the domain word as a static literal;
  // the resolved URL is the same readiness endpoint the dashboard uses.
  initStatusPill("/api/status");
  setStatus("", "idle");
  setLiveButtons(false);
  if (CONFIG.transport === "ws") {
    // The hosted service hands a live ws URL — connect immediately.
    setLiveButtons(true);
    startWS();
  }
  window.addEventListener("beforeunload", function(){ closeStream(); if (replayTimer) clearInterval(replayTimer); });
})();
</script>
</body>
</html>
"""
