"""Shared application chrome — the single source of the dashboard shell.

Both the dashboard (:mod:`promptpolygraph.ui.page`) and the Red-Team Arena
(:mod:`promptpolygraph.ui.arena`) render inside the same shell so they look like
one product: the same color tokens, fonts, buttons, fields, and the same top
header bar with the nav tabs ``Runs`` / ``New run`` / ``Studio`` / ``Red Team``.

* :data:`THEME_CSS` — the ``:root`` color tokens + base element styles (body,
  links, ``.btn``, ``.field`` / ``select.field``, ``.panel``, ``header.top``,
  ``.navtab``, ``.check``, ``.pill``, ``.empty`` / ``.err`` / ``.muted``). Each
  page may add its own component CSS on top, but it bases everything on these
  tokens so the two surfaces stay visually consistent.
* :func:`header_html` — the top header bar. ``links=False`` (dashboard) keeps
  the existing in-page JS view-switchers; ``links=True`` (Arena, a separate
  page) turns the dashboard tabs into ``<a href>`` links back to ``/``.

Everything here is plain inline CSS / HTML strings — no external URLs, CDNs, or
web fonts — so both pages remain fully self-contained and offline-capable.
"""

from __future__ import annotations

__all__ = ["THEME_CSS", "header_html", "designer_dock_html", "DESIGNER_DOCK_JS"]


# The canonical look comes from the dashboard's original palette. Both pages
# import these tokens verbatim so colors/fonts/spacing are identical.
THEME_CSS: str = r"""
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --panel-2: #1d212b;
    --border: #2a2f3a;
    --text: #e6e9ef;
    --muted: #98a0ad;
    --accent: #6aa3ff;
    --muted-2: #6a7280;
    --pass: #46c08a;
    --fail: #e5736b;
    --warn: #e6b450;
    --row-hover: #20242f;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    /* shared spacing scale (4px rhythm) + radii — one ruler for the whole app */
    --sp-1: 4px;
    --sp-2: 8px;
    --sp-3: 12px;
    --sp-4: 16px;
    --sp-5: 22px;
    --radius: 10px;
    --radius-sm: 7px;
    --radius-lg: 12px;
    --focus-ring: 0 0 0 3px rgba(106,163,255,.28);
    /* uppercase micro-label (section headers, field labels) */
    --label-size: 11px;
    --label-spacing: .5px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text); font-family: var(--sans);
    font-size: 14px; line-height: 1.5;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* ── shared top header / nav ─────────────────────────────────────────── */
  header.top {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    padding: 11px 22px; border-bottom: 1px solid var(--border);
    background: var(--panel); position: sticky; top: 0; z-index: 30;
  }
  header.top h1 { font-size: 16px; font-weight: 700; margin: 0; letter-spacing: .3px; white-space: nowrap; }
  header.top .sub { color: var(--muted); font-size: 12px; white-space: nowrap; }
  header.top .spacer { flex: 1 1 16px; min-width: 0; }
  header.top .crumb { color: var(--muted); font-size: 13px; cursor: pointer; transition: color .14s; white-space: nowrap; }
  header.top .crumb:hover { color: var(--text); }
  /* right-aligned cluster: crumb + Designer button + status pill, real gaps,
     never overlapping. Shrinks/wraps before it can collide with the nav. */
  header.top .top-right {
    display: flex; align-items: center; gap: 12px; margin-left: auto;
    flex-wrap: wrap; justify-content: flex-end; min-width: 0;
  }
  header.top .navtabs { display: flex; gap: 2px; margin-left: 4px; flex-wrap: wrap; }
  header.top .navtab {
    padding: 6px 13px; cursor: pointer; color: var(--muted); border-radius: var(--radius-sm);
    font-weight: 600; font-size: 13px; text-decoration: none; transition: background .14s, color .14s;
  }
  header.top .navtab:hover { background: var(--panel-2); color: var(--text); text-decoration: none; }
  header.top .navtab.active { color: var(--text); background: var(--panel-2); }
  header.top .navtab:focus-visible { outline: none; box-shadow: var(--focus-ring); }

  /* ── shared surfaces ─────────────────────────────────────────────────── */
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 0; margin-bottom: var(--sp-5); overflow: hidden; }
  .panel h2 { font-size: 13px; font-weight: 700; margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--border); letter-spacing: .2px; }
  .panel .body { padding: var(--sp-2) 0; }

  /* ── shared controls ─────────────────────────────────────────────────── */
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 13px; border: 1px solid var(--border);
    border-radius: var(--radius-sm); background: var(--panel); color: var(--text);
    cursor: pointer; font-size: 13px; font-weight: 600; font-family: var(--sans);
    line-height: 1.2; transition: background .14s, border-color .14s, filter .14s;
  }
  .btn:hover { background: var(--panel-2); border-color: var(--muted-2, #3a4150); text-decoration: none; }
  .btn:active { filter: brightness(.96); }
  .btn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
  .btn.primary { background: var(--accent); color: #0b0d11; border-color: var(--accent); font-weight: 700; }
  .btn.primary:hover { filter: brightness(1.08); background: var(--accent); border-color: var(--accent); }
  .btn[disabled], .btn.disabled-btn { opacity: .5; cursor: default; pointer-events: none; }

  .field { display: flex; flex-direction: column; gap: var(--sp-1); }
  .field label { color: var(--muted); font-size: var(--label-size); text-transform: uppercase; letter-spacing: var(--label-spacing); font-weight: 600; }
  .field input[type=text], .field input[type=number], .field select, .field textarea {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 7px 10px; font-size: 13px; font-family: var(--sans);
    transition: border-color .14s, box-shadow .14s; }
  .field input::placeholder, .field textarea::placeholder { color: var(--muted-2, #6a7280); }
  .field textarea { resize: vertical; min-height: 38px; line-height: 1.5; }
  .field input:focus, .field select:focus, .field textarea:focus { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
  select.field {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 7px 10px; font-size: 13px; font-family: var(--sans);
    transition: border-color .14s, box-shadow .14s; }
  select.field:focus { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }

  .check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
  .check input { accent-color: var(--accent); }

  .pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px;
          font-weight: 600; border: 1px solid var(--border); color: var(--muted); line-height: 1.45; }

  /* ── shared status text ──────────────────────────────────────────────── */
  .empty { color: var(--muted); padding: 28px 16px; text-align: center; font-size: 13px; }
  .err { color: var(--fail); padding: 12px 16px; border: 1px solid rgba(229,115,107,.3); border-radius: var(--radius-sm); background: rgba(229,115,107,.07); }
  .muted { color: var(--muted); }
  .mono { font-family: var(--mono); font-size: 12px; }

  /* ── shared readiness / connection status pill (header) ──────────────── */
  /* Present on both surfaces; populated on load from the readiness endpoint so
     the user sees at a glance whether the harness will run live or mock-only. */
  header.top .status-pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--panel-2); color: var(--muted); font-size: 12.5px; font-weight: 600;
    cursor: default; line-height: 1.4; white-space: nowrap;
  }
  header.top .status-pill .sdot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--muted-2, #6a7280); flex: 0 0 auto;
  }
  header.top .status-pill.live { border-color: rgba(70,192,138,.5); color: var(--pass); background: rgba(70,192,138,.12); }
  header.top .status-pill.live .sdot { background: var(--pass); }
  header.top .status-pill.mock { border-color: rgba(230,180,80,.5); color: var(--warn); background: rgba(230,180,80,.12); }
  header.top .status-pill.mock .sdot { background: var(--warn); }

  /* ── shared tooltip system ───────────────────────────────────────────── */
  /* A small "?" (or any element) carrying class .tip + a title=. The CSS bubble
     shows on hover AND keyboard focus; the title= is the accessible fallback so
     screen readers and no-CSS clients still get the text. */
  .tip {
    position: relative; display: inline-flex; align-items: center; justify-content: center;
    width: 15px; height: 15px; margin-left: 5px; border-radius: 50%;
    border: 1px solid var(--border); background: var(--panel-2); color: var(--muted);
    font: 700 10px/1 var(--sans); cursor: help; vertical-align: middle;
    text-transform: none; letter-spacing: 0; user-select: none; transition: color .14s, border-color .14s;
  }
  .tip:hover, .tip:focus-visible { color: var(--text); border-color: var(--accent); outline: none; }
  .tip:focus-visible { box-shadow: var(--focus-ring); }
  /* When a tip is hovered/focused, lift its whole positioning chain out of any
     overflow:hidden/auto ancestor clipping so the bubble is never cut off.
     `isolation:isolate` is harmless and keeps the high z-index honest. */
  .tip:hover, .tip:focus-within, .tip:focus-visible { z-index: 200; }
  .tip-host { overflow: visible !important; }
  /* the bubble — opens UPWARD by default; .tip-below opens downward (header). */
  .tip::after {
    content: attr(data-tip); position: absolute; bottom: calc(100% + 8px); left: 50%;
    transform: translateX(-50%) translateY(4px);
    width: max-content; max-width: 260px; padding: 8px 11px;
    background: #0a0c11; color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); font: 400 11.5px/1.5 var(--sans); text-align: left;
    white-space: normal; word-break: normal; overflow-wrap: anywhere;
    box-shadow: 0 10px 28px rgba(0,0,0,.55);
    opacity: 0; pointer-events: none; transition: opacity .14s, transform .14s; z-index: 1000;
  }
  /* the arrow */
  .tip::before {
    content: ""; position: absolute; bottom: calc(100% + 3px); left: 50%;
    transform: translateX(-50%) translateY(4px);
    border: 5px solid transparent; border-top-color: var(--border);
    opacity: 0; pointer-events: none; transition: opacity .14s, transform .14s; z-index: 1001;
  }
  .tip:hover::after, .tip:focus-visible::after,
  .tip:hover::before, .tip:focus-visible::before { opacity: 1; }
  .tip:hover::after, .tip:focus-visible::after { transform: translateX(-50%) translateY(0); }
  .tip:hover::before, .tip:focus-visible::before { transform: translateX(-50%) translateY(0); }
  /* edge-aware: pin to the right so a tip near the right edge can't run off. */
  .tip.tip-left::after { left: auto; right: -4px; transform: translateX(0) translateY(4px); }
  .tip.tip-left:hover::after, .tip.tip-left:focus-visible::after { transform: translateX(0) translateY(0); }
  /* open downward (use near the top edge / sticky header) */
  .tip.tip-below::after {
    bottom: auto; top: calc(100% + 8px); transform: translateX(-50%) translateY(-4px);
  }
  .tip.tip-below.tip-left::after { left: auto; right: -4px; transform: translateX(0) translateY(-4px); }
  .tip.tip-below::before {
    bottom: auto; top: calc(100% + 3px);
    border-top-color: transparent; border-bottom-color: var(--border);
    transform: translateX(-50%) translateY(-4px);
  }
  .tip.tip-below:hover::after, .tip.tip-below:focus-visible::after,
  .tip.tip-below.tip-left:hover::after, .tip.tip-below.tip-left:focus-visible::after { transform: translateX(0) translateY(0); }
  .tip.tip-below:not(.tip-left):hover::after, .tip.tip-below:not(.tip-left):focus-visible::after { transform: translateX(-50%) translateY(0); }
  .tip.tip-below:hover::before, .tip.tip-below:focus-visible::before { transform: translateX(-50%) translateY(0); }

  /* ── shared "Test connection" result line ────────────────────────────── */
  .conn-result { font-size: 12.5px; line-height: 1.5; margin-top: 8px; display: block; }
  .conn-result .cdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .conn-result.ok { color: var(--pass); }
  .conn-result.ok .cdot { background: var(--pass); }
  .conn-result.bad { color: var(--fail); }
  .conn-result.bad .cdot { background: var(--fail); }
  .conn-result.busy { color: var(--accent); }
  .conn-result.busy .cdot { background: var(--accent); }
  .conn-result .csample {
    display: block; margin-top: 5px; padding: 7px 10px; border: 1px solid var(--border);
    border-radius: var(--radius-sm); background: var(--bg); color: var(--muted);
    font-family: var(--mono); font-size: 11.5px; white-space: pre-wrap; word-break: break-word;
  }

  /* ── shared header Designer toggle ───────────────────────────────────── */
  header.top .designer-toggle {
    appearance: none; border: 1px solid var(--accent); border-radius: 8px;
    background: rgba(106,163,255,.12); color: var(--text); cursor: pointer;
    font: 700 12.5px/1 var(--sans); padding: 7px 12px; letter-spacing: .2px;
    display: inline-flex; align-items: center; gap: 6px;
  }
  header.top .designer-toggle:hover { background: rgba(106,163,255,.2); }
  header.top .designer-toggle .glyph { color: var(--accent); font-size: 13px; }
  header.top .designer-toggle[aria-expanded="true"] { background: var(--accent); color: #0b0d11; }
  header.top .designer-toggle[aria-expanded="true"] .glyph { color: #0b0d11; }

  /* ── shared AI Designer dock (slides in from the right) ──────────────── */
  .dock-scrim {
    position: fixed; inset: 0; background: rgba(3,4,8,.42); z-index: 44;
    opacity: 0; pointer-events: none; transition: opacity .2s;
  }
  .dock-scrim.open { opacity: 1; pointer-events: auto; }
  .designer-dock {
    position: fixed; top: 0; right: 0; height: 100%; width: min(440px, 96vw);
    background: var(--panel); border-left: 1px solid var(--border);
    transform: translateX(102%); transition: transform .26s cubic-bezier(.2,.8,.2,1);
    z-index: 45; display: flex; flex-direction: column;
    box-shadow: -10px 0 34px rgba(0,0,0,.45);
  }
  .designer-dock.open { transform: translateX(0); }
  .designer-dock .dk-head {
    display: flex; align-items: center; gap: 9px; padding: 14px 16px;
    border-bottom: 1px solid var(--border); background: var(--panel-2);
  }
  .designer-dock .dk-head .dk-glyph { color: var(--accent); font-size: 15px; }
  .designer-dock .dk-head strong { font-size: 14px; font-weight: 700; }
  .designer-dock .dk-head .dk-ctx {
    font-size: 11px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase;
    color: var(--accent); border: 1px solid var(--border); border-radius: 999px; padding: 2px 9px;
    background: rgba(106,163,255,.08);
  }
  .designer-dock .dk-head .dk-x {
    margin-left: auto; cursor: pointer; color: var(--muted);
    border: 1px solid var(--border); border-radius: 8px; padding: 4px 10px; font-size: 13px;
  }
  .designer-dock .dk-head .dk-x:hover { color: var(--text); background: var(--panel); }
  .designer-dock .dk-body { padding: 16px; overflow: auto; display: flex; flex-direction: column; gap: var(--sp-4); }
  .designer-dock .dk-body > .field label { color: var(--muted); }
  .designer-dock .dk-row { display: flex; gap: var(--sp-3); flex-wrap: wrap; }
  .designer-dock .dk-row > .field { flex: 1; min-width: 130px; }
  .designer-dock .dk-actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; align-items: center; }
  .designer-dock textarea { min-height: 84px; }

  /* structured design preview (labelled fields, NOT chat bubbles) */
  .dk-preview { border: 1px solid var(--border); border-radius: 10px; background: var(--bg); overflow: hidden; }
  .dk-preview .dk-pv-head {
    padding: 9px 12px; border-bottom: 1px solid var(--border); background: var(--panel-2);
    font-size: 12px; font-weight: 700; display: flex; align-items: center; gap: 8px;
  }
  .dk-preview .dk-pv-head .dk-prov {
    margin-left: auto; font-size: 10px; font-weight: 600; color: var(--muted);
    border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px;
  }
  .dk-section { padding: 10px 13px; border-top: 1px solid var(--border); }
  .dk-section:first-child { border-top: 0; }
  .dk-section .dk-k {
    font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); margin-bottom: 5px;
  }
  .dk-section .dk-v { font-size: 12.5px; line-height: 1.5; word-break: break-word; }
  .dk-section .dk-v.mono { font-family: var(--mono); }
  .dk-chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .dk-chip {
    font-size: 11px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--panel-2); color: var(--text); line-height: 1.5;
  }
  .dk-lane {
    border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; margin-top: 6px;
    background: var(--panel-2); font-size: 12px;
  }
  .dk-lane:first-child { margin-top: 0; }
  .dk-lane .dk-lane-h { font-weight: 700; }
  .dk-lane .dk-lane-m { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .dk-notes { font-size: 12px; color: var(--warn); padding: 9px 12px; border-top: 1px solid var(--border); white-space: pre-wrap; }
  .dk-status { font-size: 12.5px; color: var(--muted); }
  .dk-status.err { color: var(--fail); }
  .dk-status.busy { color: var(--accent); }
"""


# Canonical tab order + labels for the shared nav.
_TABS: tuple[tuple[str, str], ...] = (
    ("runs", "Runs"),
    ("newrun", "New run"),
    ("studio", "Studio"),
    ("redteam", "Red Team"),
)

# Dashboard in-page view switchers, by tab key (only used when links=False).
_DASH_ONCLICK: dict[str, str] = {
    "runs": "showRuns()",
    "newrun": "showNewRun()",
    "studio": "showStudio()",
}


def header_html(active: str, *, links: bool) -> str:
    """Return the shared top header bar markup.

    Args:
        active: the active tab key (``"runs"``, ``"newrun"``, ``"studio"``,
            ``"redteam"``); marks that tab ``active`` + ``aria-current``.
        links: ``False`` for the dashboard — the ``Runs`` / ``New run`` /
            ``Studio`` tabs keep their in-page JS ``onclick`` view-switchers and
            ``Red Team`` is an ``<a href="/redteam">`` to the separate page.
            ``True`` for the Arena (a separate page) — those three tabs become
            ``<a href="/">`` links back to the dashboard and ``Red Team`` is the
            active, link-less tab.

    The crumb element is shared too: on the dashboard it is a clickable
    ``showRuns()`` switcher; on the Arena it just labels the current surface.
    """
    tabs_html = []
    for key, label in _TABS:
        cls = "navtab" + (" active" if key == active else "")
        cur = ' aria-current="page"' if key == active else ""
        tab_id = f'id="nav-{key}"'
        if links:
            # Arena (separate page): dashboard tabs link back to "/"; Red Team is
            # the active surface, rendered without a link.
            if key == "redteam":
                tabs_html.append(f'<span class="{cls}" {tab_id}{cur}>{label}</span>')
            else:
                tabs_html.append(f'<a class="{cls}" {tab_id} href="/"{cur}>{label}</a>')
        else:
            # Dashboard: in-page switchers for the SPA views; Red Team links out.
            if key == "redteam":
                tabs_html.append(f'<a class="{cls}" {tab_id} href="/redteam"{cur}>{label}</a>')
            else:
                onclick = _DASH_ONCLICK[key]
                tabs_html.append(
                    f'<span class="{cls}" {tab_id} onclick="{onclick}"{cur}>{label}</span>'
                )

    nav = '<span class="navtabs" id="navtabs">' + "".join(tabs_html) + "</span>"

    if links:
        # Arena: the crumb labels the surface (no in-page switching).
        crumb = '<span class="crumb" id="crumb">Authorized red-team of a target you control</span>'
    else:
        # Dashboard: the crumb is a clickable "back to all runs" switcher.
        crumb = '<span class="crumb" id="crumb" onclick="showRuns()">All runs</span>'

    # Shared Designer toggle — identical on both surfaces. Each page defines its
    # own toggleDesigner() (open/close) and design/inject handlers; the dock
    # markup + CSS are shared via designer_dock_html() + THEME_CSS.
    # Shared readiness / connection status pill — identical on both surfaces.
    # Populated on page load by initStatusPill() (in DESIGNER_DOCK_JS) from
    # GET /api/health: green "Live" when any provider is wired, amber
    # "Mock-only (offline)" otherwise. The title= lists each provider + reason
    # as an accessible fallback; the same text fills the CSS tooltip bubble.
    status_pill = (
        '<span class="status-pill" id="status-pill" tabindex="0" role="status" '
        'aria-live="polite" data-tip="Checking which model backends are wired…" '
        'title="Checking which model backends are wired…">'
        '<span class="sdot" aria-hidden="true"></span>'
        '<span id="status-pill-text">Checking…</span></span>'
    )

    designer_btn = (
        '<button type="button" class="designer-toggle" id="designer-toggle" '
        'aria-expanded="false" aria-controls="designer-dock" '
        'onclick="toggleDesigner()" title="Open the AI Designer (Esc to close)">'
        '<span class="glyph" aria-hidden="true">&#10022;</span> Designer</button>'
    )

    return (
        '<header class="top">'
        '<h1>PromptPolygraph</h1>'
        '<span class="sub">control plane</span>'
        + nav
        + '<span class="top-right">'
        + crumb
        + designer_btn
        + status_pill
        + "</span>"
        + "</header>"
    )


def designer_dock_html(*, context_label: str) -> str:
    """Return the shared AI Designer dock markup.

    The dock is a structured (non-chat) side panel: a description textarea, the
    provider/model selects (wired by each page from ``/api/providers``), a
    Design button, and a structured result preview with Inject + Refine. The
    markup is identical on both surfaces; only ``context_label`` differs
    ("Run config" on the dashboard, "Red team" in the Arena). Each page wires
    ``designerDesign()`` / ``designerInject()`` / ``designerRefine()`` and the
    provider-select init against these stable IDs.

    Args:
        context_label: the short label shown beside the dock title.
    """
    return (
        '<div class="dock-scrim" id="dock-scrim" onclick="closeDesigner()"></div>'
        '<aside class="designer-dock" id="designer-dock" role="dialog" aria-modal="false" '
        'aria-label="AI Designer">'
        '<div class="dk-head">'
        '<span class="dk-glyph" aria-hidden="true">&#10022;</span>'
        '<strong>AI Designer</strong>'
        '<span class="dk-ctx" id="dk-context">' + context_label + '</span>'
        '<span class="dk-x" id="dk-close" onclick="closeDesigner()" role="button" '
        'tabindex="0">close &#10005;</span>'
        '</div>'
        '<div class="dk-body">'
        '<div class="field"><label for="dk-desc">Describe your system under test '
        'and what you want to evaluate / attack</label>'
        '<textarea id="dk-desc" placeholder="e.g. a budgeting assistant for freelancers '
        'with a tool that reads bank records; check it refuses risky money moves and '
        'never leaks another user&#39;s data"></textarea></div>'
        '<div class="dk-row">'
        '<div class="field"><label for="dk-provider">Provider</label>'
        '<select class="field" id="dk-provider"><option>loading&hellip;</option></select></div>'
        '<div class="field"><label for="dk-model">Model</label>'
        '<select class="field" id="dk-model"><option>&mdash;</option></select>'
        '<input type="text" class="field" id="dk-model-custom" placeholder="custom model name" '
        'style="display:none;margin-top:4px"></div>'
        '</div>'
        '<div id="dk-provider-notice"></div>'
        '<label class="check"><input type="checkbox" id="dk-mock" checked> Mock (offline)</label>'
        '<div class="dk-actions">'
        '<button class="btn primary" id="dk-design" onclick="designerDesign()">Design</button>'
        '<span class="dk-status" id="dk-status"></span>'
        '</div>'
        '<div id="dk-result"></div>'
        '</div>'
        '</aside>'
    )


# Shared dock behavior, identical on both surfaces. It covers open/close (with
# Esc), the provider/model dropdown init, the busy/error/empty status line, and
# the Design→preview→Inject/Refine flow skeleton. The page-specific pieces are
# injected as three globals the page MUST define before this runs:
#   * window.__dkDesignUrl  — the design endpoint to POST {description,provider,model,mock}
#   * window.__dkRenderPreview(result) -> HTML  — structured (non-chat) preview
#   * window.__dkInject(config)  — fill that page's form/controls from the design
# Both pages reuse the provider-dropdown helpers (initProviderSelects / resolve*)
# already defined on each page. No external URLs; all fetches are relative.
DESIGNER_DOCK_JS: str = r"""
var _dkLastDesign = null;     // last {config, notes, provider} from a Design call
var _dkProviderReady = false; // lazily populate provider/model selects on first open

function _dkStatus(msg, kind) {
  var el = document.getElementById("dk-status");
  if (!el) return;
  el.className = "dk-status" + (kind ? " " + kind : "");
  el.textContent = msg || "";
}
function _dkSetBusy(on) {
  var b = document.getElementById("dk-design");
  if (b) { b.classList.toggle("disabled-btn", !!on); b.textContent = on ? "Designing…" : "Design"; }
}

function openDesigner() {
  var dock = document.getElementById("designer-dock");
  var scrim = document.getElementById("dock-scrim");
  var tog = document.getElementById("designer-toggle");
  if (!dock) return;
  dock.classList.add("open");
  if (scrim) scrim.classList.add("open");
  if (tog) tog.setAttribute("aria-expanded", "true");
  if (!_dkProviderReady && typeof initProviderSelects === "function") {
    _dkProviderReady = true;
    initProviderSelects({
      providerSel: "dk-provider", modelSel: "dk-model", customInput: "dk-model-custom",
      notice: "dk-provider-notice", preferLocal: false,
    });
  }
  var ta = document.getElementById("dk-desc");
  if (ta) ta.focus();
}
function closeDesigner() {
  var dock = document.getElementById("designer-dock");
  var scrim = document.getElementById("dock-scrim");
  var tog = document.getElementById("designer-toggle");
  if (dock) dock.classList.remove("open");
  if (scrim) scrim.classList.remove("open");
  if (tog) tog.setAttribute("aria-expanded", "false");
}
function toggleDesigner() {
  var dock = document.getElementById("designer-dock");
  if (dock && dock.classList.contains("open")) closeDesigner(); else openDesigner();
}
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape") {
    var dock = document.getElementById("designer-dock");
    if (dock && dock.classList.contains("open")) closeDesigner();
  }
});

// Run a Design call against the page-supplied endpoint, then hand the result to
// the page-supplied structured renderer. Keeps the description for Refine.
function designerDesign() {
  if (typeof postJSON !== "function" || !window.__dkDesignUrl) return;
  var ta = document.getElementById("dk-desc");
  var desc = (ta && ta.value || "").trim();
  var out = document.getElementById("dk-result");
  if (!desc) { _dkStatus("Describe the system under test first.", "err"); if (ta) ta.focus(); return; }
  var provider = (typeof resolveProvider === "function") ? resolveProvider("dk-provider") : "";
  var model = (typeof resolveModel === "function") ? resolveModel("dk-model", "dk-model-custom") : "";
  var mockEl = document.getElementById("dk-mock");
  var body = { description: desc, mock: !!(mockEl && mockEl.checked) };
  if (provider) body.provider = provider;
  if (model) body.model = model;
  _dkSetBusy(true);
  _dkStatus("Designing…", "busy");
  if (out) out.innerHTML = "";
  postJSON(window.__dkDesignUrl, body).then(function(res) {
    _dkSetBusy(false);
    if (!res || !res.config) { _dkStatus((res && res.error) || "design returned nothing", "err"); return; }
    _dkLastDesign = res;
    _dkStatus("", "");
    if (out && typeof window.__dkRenderPreview === "function") out.innerHTML = window.__dkRenderPreview(res);
    _dkBindResultActions();
  }).catch(function(e) {
    _dkSetBusy(false);
    _dkStatus("Design failed: " + (e && e.message ? e.message : String(e)), "err");
  });
}

// Refine = keep the description, re-run Design (the user can edit the text first).
function designerRefine() { designerDesign(); }

function _dkBindResultActions() {
  var inj = document.getElementById("dk-inject");
  if (inj) inj.addEventListener("click", function() {
    if (_dkLastDesign && _dkLastDesign.config && typeof window.__dkInject === "function") {
      window.__dkInject(_dkLastDesign.config);
      _dkStatus("Injected into the form. Review, then Save / Launch.", "");
    }
  });
  var ref = document.getElementById("dk-refine");
  if (ref) ref.addEventListener("click", designerRefine);
}

// Shared structured-preview chrome the page renderers wrap their fields in.
// `sections` is pre-built HTML of .dk-section blocks; `notes` is the rationale.
function dkPreviewShell(title, provider, sections, notes) {
  var head = '<div class="dk-pv-head"><span>' + esc(title) + '</span>'
    + (provider ? '<span class="dk-prov">' + esc(provider) + '</span>' : '') + '</div>';
  var notesHtml = notes ? '<div class="dk-notes">' + esc(notes) + '</div>' : '';
  var actions = '<div class="dk-section" style="display:flex;gap:8px">'
    + '<button class="btn primary" id="dk-inject">Inject</button>'
    + '<button class="btn" id="dk-refine">Refine</button></div>';
  return '<div class="dk-preview">' + head + sections + notesHtml + actions + '</div>';
}
function dkSection(label, valueHtml, mono) {
  return '<div class="dk-section"><div class="dk-k">' + esc(label) + '</div>'
    + '<div class="dk-v' + (mono ? " mono" : "") + '">' + valueHtml + '</div></div>';
}
function dkChips(items) {
  return '<div class="dk-chips">' + (items || []).map(function(i){
    return '<span class="dk-chip">' + esc(i) + '</span>';
  }).join("") + '</div>';
}

// ── shared readiness status pill (header) ────────────────────────────────
// Runs on BOTH the dashboard and the Arena. Given the readiness endpoint path
// (passed in so each surface controls the exact literal it embeds), GET it and
// set the pill to green "● Live" (a provider is wired) or amber
// "● Mock-only (offline)", and fill its tooltip with each provider + reason so
// the user sees exactly what is wired and what is missing. Relative URL only.
function initStatusPill(readyUrl) {
  var pill = document.getElementById("status-pill");
  var txt = document.getElementById("status-pill-text");
  if (!pill || !txt) return;
  fetch(readyUrl).then(function(r){ return r.json(); }).then(function(h){
    h = h || {};
    var live = (h.status === "live");
    pill.classList.remove("live", "mock");
    pill.classList.add(live ? "live" : "mock");
    txt.textContent = live ? "Live" : "Mock-only";  // concise; full detail in the tooltip
    var provs = h.providers || [];
    var lines = [];
    if (live) lines.push("Live — at least one model backend is wired.");
    else lines.push("Mock-only — no model backend is wired; runs use offline mock.");
    if (provs.length) {
      provs.forEach(function(p){
        var mark = p.available ? "✓" : "✗";
        var reason = p.available ? "ready" : (p.reason || "unavailable");
        lines.push(mark + " " + (p.id || "?") + " - " + reason);
      });
    } else {
      lines.push("No providers discovered - run polygraph init, set an API key, or start a local model.");
    }
    var tipText = lines.join("\n");
    pill.setAttribute("data-tip", tipText);
    pill.setAttribute("title", tipText);
  }).catch(function(){
    pill.classList.remove("live");
    pill.classList.add("mock");
    txt.textContent = "Status unavailable";
    var msg = "Backend readiness check failed - status unknown.";
    pill.setAttribute("data-tip", msg);
    pill.setAttribute("title", msg);
  });
}
"""
