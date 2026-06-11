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

__all__ = ["THEME_CSS", "header_html"]


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

  /* ── shared top header / nav ─────────────────────────────────────────── */
  header.top {
    display: flex; align-items: baseline; gap: 14px;
    padding: 14px 22px; border-bottom: 1px solid var(--border);
    background: var(--panel); position: sticky; top: 0; z-index: 30;
  }
  header.top h1 { font-size: 16px; margin: 0; letter-spacing: .3px; }
  header.top .sub { color: var(--muted); font-size: 12px; }
  header.top .spacer { flex: 1; }
  header.top .crumb { color: var(--muted); font-size: 13px; cursor: pointer; }
  header.top .crumb:hover { color: var(--text); }
  header.top .navtabs { display: flex; gap: 2px; }
  header.top .navtab {
    padding: 5px 12px; cursor: pointer; color: var(--muted); border-radius: 7px;
    font-weight: 600; font-size: 13px; text-decoration: none;
  }
  header.top .navtab:hover { background: var(--panel-2); color: var(--text); text-decoration: none; }
  header.top .navtab.active { color: var(--text); background: var(--panel-2); }

  /* ── shared surfaces ─────────────────────────────────────────────────── */
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 4px 0; margin-bottom: 22px; overflow: hidden; }
  .panel h2 { font-size: 14px; margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .panel .body { padding: 4px 0; }

  /* ── shared controls ─────────────────────────────────────────────────── */
  .btn {
    display: inline-block; padding: 7px 13px; border: 1px solid var(--border);
    border-radius: 8px; background: var(--panel); color: var(--text);
    cursor: pointer; font-size: 13px; font-family: var(--sans);
  }
  .btn:hover { background: var(--panel-2); text-decoration: none; }
  .btn.primary { background: var(--accent); color: #0b0d11; border-color: var(--accent); font-weight: 700; }
  .btn.primary:hover { filter: brightness(1.08); background: var(--accent); }
  .btn[disabled], .btn.disabled-btn { opacity: .5; cursor: default; pointer-events: none; }

  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
  .field input[type=text], .field input[type=number], .field select, .field textarea {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 7px; padding: 7px 9px; font-size: 13px; font-family: var(--sans); }
  .field textarea { resize: vertical; min-height: 38px; }
  .field input:focus, .field select:focus, .field textarea:focus { outline: none; border-color: var(--accent); }
  select.field {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 7px; padding: 7px 9px; font-size: 13px; font-family: var(--sans); }
  select.field:focus { outline: none; border-color: var(--accent); }

  .check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
  .check input { accent-color: var(--accent); }

  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
          font-weight: 600; border: 1px solid var(--border); color: var(--muted); }

  /* ── shared status text ──────────────────────────────────────────────── */
  .empty { color: var(--muted); padding: 26px 16px; text-align: center; }
  .err { color: var(--fail); padding: 16px; }
  .muted { color: var(--muted); }
  .mono { font-family: var(--mono); font-size: 12px; }
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

    return (
        '<header class="top">'
        '<h1>PromptPolygraph</h1>'
        '<span class="sub">control plane</span>'
        + nav
        + '<span class="spacer"></span>'
        + crumb
        + "</header>"
    )
