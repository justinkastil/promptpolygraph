"""Pure-Python inline-SVG chart generators for the HTML report.

Every function returns a self-contained ``<svg>…</svg>`` string with no external
assets, scripts, or CDN references — the SVG is embedded directly into the
report HTML so the file stays fully offline and printable. All inputs degrade
gracefully: empty/missing data yields a small "no data" SVG placeholder rather
than raising.

The colour ramp is anchored on the rubric threshold: at/below ``failed`` it is
red, climbing through amber at the threshold to green at the top of the scale.
The branding accent (a hex string) tints structural elements (axes, the active
trend line) so a report carries through a caller's colour.
"""

from __future__ import annotations

from html import escape as _esc
from typing import Any, Optional, Sequence

# Canonical palette — mirrors the report CSS so charts feel native to the page.
_RED = "#b01b1b"
_AMBER = "#d8a200"
_GREEN = "#1b7f37"
_MUTED = "#6b6b70"
_GRID = "#e3e3e8"
_AXIS = "#c4c4cc"
_TEXT = "#1c1c1e"
_PANEL = "#f6f6f8"

_DEFAULT_ACCENT = "#4f46e5"
_DEFAULT_MAX = 10.0


# ─── colour helpers ──────────────────────────────────────────────────────────


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = (hex_str or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (79, 70, 229)  # _DEFAULT_ACCENT
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (79, 70, 229)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = _clamp(t, 0.0, 1.0)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def score_color(value: Optional[float], threshold: float, vmax: float = _DEFAULT_MAX) -> str:
    """Red→amber→green ramp anchored on ``threshold`` over ``[0, vmax]``.

    ``None`` (N/A) renders as the neutral panel fill so empty cells read as
    absent rather than failing.
    """
    if value is None:
        return _PANEL
    red, amber, green = _hex_to_rgb(_RED), _hex_to_rgb(_AMBER), _hex_to_rgb(_GREEN)
    thr = threshold if (threshold and threshold > 0) else (vmax / 2 if vmax else 5.0)
    if value <= thr:
        return _lerp(red, amber, value / thr if thr else 0.0)
    span = (vmax - thr) or 1.0
    return _lerp(amber, green, (value - thr) / span)


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: Optional[float], places: int = 1) -> str:
    return "—" if v is None else f"{v:.{places}f}"


def _empty(msg: str = "No data", w: int = 320, h: int = 60) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" role="img" aria-label="{_esc(msg)}">'
        f'<rect width="{w}" height="{h}" rx="8" fill="{_PANEL}"/>'
        f'<text x="{w // 2}" y="{h // 2 + 4}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="12" fill="{_MUTED}">{_esc(msg)}</text></svg>'
    )


def _txt_color(bg_hex: str) -> str:
    """Pick black/white text for legibility over an arbitrary cell fill."""
    r, g, b = _hex_to_rgb(bg_hex)
    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 140 else _TEXT


# ─── 1. score heatmap ────────────────────────────────────────────────────────


def score_heatmap(summary: dict, *, accent: str = _DEFAULT_ACCENT, vmax: float = _DEFAULT_MAX) -> str:
    """Categories (rows) × dimensions (cols) coloured on the threshold ramp."""
    summary = summary or {}
    dims: list[str] = list(summary.get("dimensions") or [])
    cat_scores: dict = summary.get("category_scores") or {}
    cats = sorted(cat_scores)
    threshold = _num(summary.get("threshold")) or (vmax / 2)
    if not dims or not cats:
        return _empty("No category scores")

    label_w, cell_w, cell_h, pad_top, gap = 130, 78, 30, 56, 3
    grid_w = len(dims) * (cell_w + gap)
    w = label_w + grid_w + 14
    h = pad_top + len(cats) * (cell_h + gap) + 8

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="sans-serif" role="img" aria-label="Score heatmap">',
        f'<rect width="{w}" height="{h}" fill="none"/>',
    ]
    # column headers (rotated-free, short)
    for j, d in enumerate(dims):
        cx = label_w + j * (cell_w + gap) + cell_w / 2
        parts.append(
            f'<text x="{cx:.1f}" y="{pad_top - 38}" text-anchor="middle" font-size="11" '
            f'font-weight="600" fill="{_TEXT}">{_esc(_truncate(d, 11))}</text>'
        )
    # accent rule under headers
    parts.append(
        f'<line x1="{label_w}" y1="{pad_top - 8}" x2="{label_w + grid_w}" y2="{pad_top - 8}" '
        f'stroke="{_esc(accent)}" stroke-width="2"/>'
    )
    for i, cat in enumerate(cats):
        entry = cat_scores.get(cat) or {}
        ry = pad_top + i * (cell_h + gap)
        parts.append(
            f'<text x="{label_w - 10}" y="{ry + cell_h / 2 + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{_TEXT}">{_esc(_truncate(str(cat), 18))}</text>'
        )
        for j, d in enumerate(dims):
            v = _num(entry.get(d))
            rx = label_w + j * (cell_w + gap)
            fill = score_color(v, threshold, vmax)
            tcol = _txt_color(fill) if v is not None else _MUTED
            parts.append(
                f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{cell_w}" height="{cell_h}" rx="4" '
                f'fill="{fill}" stroke="{_GRID}"/>'
                f'<text x="{rx + cell_w / 2:.1f}" y="{ry + cell_h / 2 + 4:.1f}" '
                f'text-anchor="middle" font-size="11.5" font-weight="600" fill="{tcol}">'
                f'{_esc(_fmt(v))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _truncate(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ─── 2. dimension bars ───────────────────────────────────────────────────────


def dimension_bars(summary: dict, *, accent: str = _DEFAULT_ACCENT, vmax: float = _DEFAULT_MAX) -> str:
    """Horizontal bars of the mean score per dimension (across categories)."""
    summary = summary or {}
    dims: list[str] = list(summary.get("dimensions") or [])
    cat_scores: dict = summary.get("category_scores") or {}
    threshold = _num(summary.get("threshold")) or (vmax / 2)
    if not dims or not cat_scores:
        return _empty("No dimension scores")

    means: list[tuple[str, Optional[float]]] = []
    for d in dims:
        vals = [_num(e.get(d)) for e in cat_scores.values() if isinstance(e, dict)]
        vals = [v for v in vals if v is not None]
        means.append((d, (sum(vals) / len(vals)) if vals else None))

    label_w, bar_w, row_h, pad_l, pad_top = 116, 300, 26, 12, 16
    w = pad_l + label_w + bar_w + 56
    h = pad_top + len(means) * (row_h + 8) + 24

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="sans-serif" role="img" aria-label="Mean score by dimension">',
    ]
    track_x = pad_l + label_w
    # threshold guide line
    tx = track_x + bar_w * _clamp(threshold / vmax, 0, 1)
    parts.append(
        f'<line x1="{tx:.1f}" y1="{pad_top - 4}" x2="{tx:.1f}" y2="{h - 16}" '
        f'stroke="{_MUTED}" stroke-width="1" stroke-dasharray="3 3"/>'
        f'<text x="{tx:.1f}" y="{h - 4}" text-anchor="middle" font-size="9.5" '
        f'fill="{_MUTED}">thr {_fmt(threshold)}</text>'
    )
    for i, (d, m) in enumerate(means):
        y = pad_top + i * (row_h + 8)
        parts.append(
            f'<text x="{pad_l + label_w - 8}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{_TEXT}">{_esc(_truncate(d, 14))}</text>'
            f'<rect x="{track_x}" y="{y}" width="{bar_w}" height="{row_h}" rx="5" fill="{_PANEL}" stroke="{_GRID}"/>'
        )
        if m is not None:
            fw = bar_w * _clamp(m / vmax, 0, 1)
            fill = score_color(m, threshold, vmax)
            parts.append(
                f'<rect x="{track_x}" y="{y}" width="{fw:.1f}" height="{row_h}" rx="5" fill="{fill}"/>'
                f'<text x="{track_x + bar_w + 8}" y="{y + row_h / 2 + 4:.1f}" font-size="11" '
                f'font-weight="600" fill="{_TEXT}">{_esc(_fmt(m))}</text>'
            )
        else:
            parts.append(
                f'<text x="{track_x + 8}" y="{y + row_h / 2 + 4:.1f}" font-size="11" '
                f'fill="{_MUTED}">—</text>'
            )
    # subtle accent baseline
    parts.append(
        f'<line x1="{track_x}" y1="{h - 16}" x2="{track_x + bar_w}" y2="{h - 16}" '
        f'stroke="{_esc(accent)}" stroke-width="1" opacity="0.35"/></svg>'
    )
    return "".join(parts)


# ─── 3. persona radar ────────────────────────────────────────────────────────


def _persona_axes(audit: dict) -> list[dict]:
    """Per-persona averages of trust/usefulness/clarity/would_return (0–10)."""
    persona = (audit or {}).get("persona") or {}
    out: list[dict] = []
    for r in persona.get("reactions") or []:
        if not isinstance(r, dict):
            continue
        name = r.get("persona") or r.get("persona_id") or r.get("who") or r.get("id") or "Persona"
        agg: dict[str, list[float]] = {k: [] for k in ("trust", "usefulness", "clarity", "would_return")}
        for cr in r.get("reactions") or []:
            if not isinstance(cr, dict):
                continue
            for k in agg:
                v = cr.get(k)
                # would_return may be a bool in some shapes → map to 0/10
                if isinstance(v, bool):
                    v = 10.0 if v else 0.0
                v = _num(v)
                if v is not None:
                    agg[k].append(v)
        axes = {k: (sum(vs) / len(vs) if vs else None) for k, vs in agg.items()}
        if any(v is not None for v in axes.values()):
            out.append({"name": str(name), "axes": axes})
    return out


def persona_radar(audit: dict, *, accent: str = _DEFAULT_ACCENT, vmax: float = _DEFAULT_MAX) -> str:
    """Radar (spider) chart of averaged persona axes; multiple personas overlaid."""
    import math

    personas = _persona_axes(audit)
    if not personas:
        return _empty("No persona reactions")

    axis_labels = ["Trust", "Usefulness", "Clarity", "Would return"]
    axis_keys = ["trust", "usefulness", "clarity", "would_return"]
    n = len(axis_keys)
    cx, cy, radius = 170.0, 160.0, 108.0
    w, h = 460, 360
    accent_rgb = _hex_to_rgb(accent)
    series_colors = [
        accent,
        _GREEN,
        "#c2410c",
        "#0e7490",
        "#7c3aed",
        "#be185d",
    ]

    def pt(idx: int, frac: float) -> tuple[float, float]:
        ang = -math.pi / 2 + idx * (2 * math.pi / n)
        rr = radius * _clamp(frac, 0, 1)
        return (cx + rr * math.cos(ang), cy + rr * math.sin(ang))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="sans-serif" role="img" aria-label="Persona radar">',
    ]
    # concentric grid rings
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, ring) for i in range(n)))
        parts.append(f'<polygon points="{ring_pts}" fill="none" stroke="{_GRID}" stroke-width="1"/>')
    # spokes + axis labels
    for i, lab in enumerate(axis_labels):
        ex, ey = pt(i, 1.0)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{_AXIS}" stroke-width="1"/>')
        lx, ly = pt(i, 1.22)
        anchor = "middle"
        if lx < cx - 5:
            anchor = "end"
        elif lx > cx + 5:
            anchor = "start"
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}" font-size="10.5" '
            f'font-weight="600" fill="{_TEXT}">{_esc(lab)}</text>'
        )
    # series polygons
    for s_idx, p in enumerate(personas[:6]):
        col = series_colors[s_idx % len(series_colors)]
        ring_pts = []
        for i, k in enumerate(axis_keys):
            v = p["axes"].get(k)
            ring_pts.append(pt(i, (v / vmax) if v is not None else 0.0))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in ring_pts)
        parts.append(
            f'<polygon points="{poly}" fill="{col}" fill-opacity="0.14" '
            f'stroke="{col}" stroke-width="2"/>'
        )
        for x, y in ring_pts:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{col}"/>')
    # legend
    ly = 18
    for s_idx, p in enumerate(personas[:6]):
        col = series_colors[s_idx % len(series_colors)]
        parts.append(
            f'<rect x="{w - 132}" y="{ly - 9}" width="11" height="11" rx="2" fill="{col}"/>'
            f'<text x="{w - 117}" y="{ly}" font-size="10.5" fill="{_TEXT}">'
            f'{_esc(_truncate(p["name"], 16))}</text>'
        )
        ly += 18
    _ = accent_rgb
    parts.append("</svg>")
    return "".join(parts)


# ─── 3b. rubric-vs-persona discordance scatter ───────────────────────────────


def _discordance_points(scores: Sequence[Any], audit: dict, vmax: float) -> list[dict]:
    """Per-case (rubric_mean, persona_mean) pairs.

    x = mean of the case's non-None rubric dimensions; y = mean of the personas'
    trust/usefulness/clarity for that case (0–vmax). Only cases scored on *both*
    axes contribute — the scatter exists to expose where the two disagree.
    """
    rubric_by_case: dict[str, float] = {}
    for s in scores or []:
        dims = getattr(s, "dimensions", None) or {}
        vals = [float(v) for v in dims.values() if v is not None]
        if vals:
            rubric_by_case[getattr(s, "case_id", "")] = sum(vals) / len(vals)

    persona_vals: dict[str, list[float]] = {}
    persona = (audit or {}).get("persona") or {}
    for r in persona.get("reactions") or []:
        if not isinstance(r, dict):
            continue
        for cr in r.get("reactions") or []:
            if not isinstance(cr, dict):
                continue
            cid = cr.get("case_id")
            if not cid:
                continue
            comp = [_num(cr.get(k)) for k in ("trust", "usefulness", "clarity")]
            comp = [c for c in comp if c is not None]
            if comp:
                persona_vals.setdefault(cid, []).append(sum(comp) / len(comp))

    out: list[dict] = []
    for cid, rx in rubric_by_case.items():
        ys = persona_vals.get(cid)
        if not ys:
            continue
        out.append({"case_id": cid, "rubric": _clamp(rx, 0, vmax),
                    "persona": _clamp(sum(ys) / len(ys), 0, vmax)})
    return out


def discordance_scatter(
    scores: Sequence[Any],
    audit: dict,
    *,
    threshold: float,
    accent: str = _DEFAULT_ACCENT,
    vmax: float = _DEFAULT_MAX,
) -> str:
    """Scatter of rubric score (x) vs persona-perceived value (y), per case.

    Threshold lines split the plane into quadrants. The point of the chart is
    the *off-diagonal*: cases the rubric passes but personas distrust (lower-
    right) are the actionable discordance — a high score that does not land with
    real users — and are drawn in red. The agreeing diagonal is muted.
    """
    pts = _discordance_points(scores, audit, vmax)
    if len(pts) < 1:
        return _empty("No rubric/persona overlap")

    pad_l, pad_r, pad_t, pad_b = 46, 18, 18, 40
    plot = 300
    w = pad_l + plot + pad_r + 150  # room for a legend
    h = pad_t + plot + pad_b

    def xpos(v: float) -> float:
        return pad_l + plot * _clamp(v / vmax, 0, 1)

    def ypos(v: float) -> float:
        return pad_t + plot * (1 - _clamp(v / vmax, 0, 1))

    thr = threshold if threshold and threshold > 0 else vmax / 2
    tx, ty = xpos(thr), ypos(thr)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="sans-serif" role="img" '
        f'aria-label="Rubric vs persona discordance scatter">',
    ]
    # discordant quadrant shading (rubric>=thr, persona<thr): lower-right.
    parts.append(
        f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{pad_l + plot - tx:.1f}" '
        f'height="{pad_t + plot - ty:.1f}" fill="{_RED}" fill-opacity="0.06"/>'
    )
    # plot frame + grid at 0/thr/max on both axes
    parts.append(
        f'<rect x="{pad_l}" y="{pad_t}" width="{plot}" height="{plot}" fill="none" stroke="{_GRID}"/>'
    )
    parts.append(
        f'<line x1="{tx:.1f}" y1="{pad_t}" x2="{tx:.1f}" y2="{pad_t + plot}" stroke="{_AMBER}" '
        f'stroke-width="1" stroke-dasharray="4 3"/>'
        f'<line x1="{pad_l}" y1="{ty:.1f}" x2="{pad_l + plot}" y2="{ty:.1f}" stroke="{_AMBER}" '
        f'stroke-width="1" stroke-dasharray="4 3"/>'
    )
    # identity diagonal (agreement)
    parts.append(
        f'<line x1="{xpos(0):.1f}" y1="{ypos(0):.1f}" x2="{xpos(vmax):.1f}" y2="{ypos(vmax):.1f}" '
        f'stroke="{_AXIS}" stroke-width="1" stroke-dasharray="2 4" opacity="0.7"/>'
    )
    # axis labels
    parts.append(
        f'<text x="{pad_l + plot / 2:.1f}" y="{h - 8}" text-anchor="middle" font-size="11" '
        f'fill="{_TEXT}">Rubric score →</text>'
        f'<text x="14" y="{pad_t + plot / 2:.1f}" text-anchor="middle" font-size="11" '
        f'fill="{_TEXT}" transform="rotate(-90 14 {pad_t + plot / 2:.1f})">Persona value →</text>'
    )
    for gv in (0.0, thr, vmax):
        parts.append(
            f'<text x="{xpos(gv):.1f}" y="{pad_t + plot + 14}" text-anchor="middle" font-size="9" '
            f'fill="{_MUTED}">{_fmt(gv, 0)}</text>'
            f'<text x="{pad_l - 6}" y="{ypos(gv) + 3:.1f}" text-anchor="end" font-size="9" '
            f'fill="{_MUTED}">{_fmt(gv, 0)}</text>'
        )

    discordant = 0
    for p in pts:
        rx, ry = p["rubric"], p["persona"]
        disc = rx >= thr and ry < thr  # passes rubric, personas distrust
        if disc:
            discordant += 1
            col, r = _RED, 4.2
        elif rx < thr and ry < thr:
            col, r = _MUTED, 3.0
        else:
            col, r = _GREEN, 3.0
        parts.append(
            f'<circle cx="{xpos(rx):.1f}" cy="{ypos(ry):.1f}" r="{r}" fill="{col}" '
            f'fill-opacity="0.72" stroke="#fff" stroke-width="0.6"/>'
        )

    # legend
    lx = pad_l + plot + 24
    parts.append(
        f'<text x="{lx}" y="{pad_t + 6}" font-size="10.5" font-weight="600" fill="{_TEXT}">'
        f'{len(pts)} cases</text>'
    )
    legend = [(_RED, f"discordant ({discordant})"), (_GREEN, "both pass"), (_MUTED, "both low")]
    for i, (col, lab) in enumerate(legend):
        yy = pad_t + 26 + i * 20
        parts.append(
            f'<circle cx="{lx + 5}" cy="{yy - 3}" r="4" fill="{col}"/>'
            f'<text x="{lx + 16}" y="{yy}" font-size="10" fill="{_TEXT}">{_esc(lab)}</text>'
        )
    parts.append(
        f'<text x="{lx}" y="{pad_t + 26 + 3 * 20 + 8}" font-size="9" fill="{_MUTED}">'
        f'lower-right = high</text>'
        f'<text x="{lx}" y="{pad_t + 26 + 3 * 20 + 20}" font-size="9" fill="{_MUTED}">'
        f'score, low trust</text>'
    )
    _ = accent
    parts.append("</svg>")
    return "".join(parts)


# ─── 4. trend line ───────────────────────────────────────────────────────────


def trend_line(series: Sequence[dict], *, accent: str = _DEFAULT_ACCENT, vmax: float = _DEFAULT_MAX,
               threshold: Optional[float] = None) -> str:
    """Polyline trends across chronological runs.

    ``series`` is a list of ``{"label": str, "points": [float|None, …]}`` where
    each ``points`` list is aligned to a shared, chronological x-axis. A single
    series is fine; multiple series are overlaid with distinct colours.
    """
    series = [s for s in (series or []) if isinstance(s, dict) and s.get("points")]
    if not series:
        return _empty("No trend data")
    n_x = max(len(s["points"]) for s in series)
    if n_x < 1:
        return _empty("No trend data")

    pad_l, pad_r, pad_t, pad_b = 40, 14, 16, 30
    plot_w, plot_h = 460, 220
    w = pad_l + plot_w + pad_r
    h = pad_t + plot_h + pad_b + (18 if len(series) > 1 else 0)
    series_colors = [accent, _GREEN, "#c2410c", "#0e7490", "#7c3aed", "#be185d"]

    def xpos(i: int) -> float:
        if n_x == 1:
            return pad_l + plot_w / 2
        return pad_l + plot_w * i / (n_x - 1)

    def ypos(v: float) -> float:
        return pad_t + plot_h * (1 - _clamp(v / vmax, 0, 1))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="sans-serif" role="img" aria-label="Score trend">',
    ]
    # y grid + labels at 0, vmax/2, vmax
    for gv in (0.0, vmax / 2, vmax):
        gy = ypos(gv)
        parts.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + plot_w}" y2="{gy:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
            f'<text x="{pad_l - 6}" y="{gy + 3:.1f}" text-anchor="end" font-size="9.5" '
            f'fill="{_MUTED}">{_fmt(gv, 0)}</text>'
        )
    if threshold is not None:
        ty = ypos(threshold)
        parts.append(
            f'<line x1="{pad_l}" y1="{ty:.1f}" x2="{pad_l + plot_w}" y2="{ty:.1f}" '
            f'stroke="{_AMBER}" stroke-width="1" stroke-dasharray="4 3"/>'
        )
    # x-axis ticks (run index)
    for i in range(n_x):
        parts.append(
            f'<text x="{xpos(i):.1f}" y="{pad_t + plot_h + 16}" text-anchor="middle" '
            f'font-size="9.5" fill="{_MUTED}">{i + 1}</text>'
        )
    for s_idx, s in enumerate(series):
        col = series_colors[s_idx % len(series_colors)]
        pts = s["points"]
        coords = [(xpos(i), ypos(v)) for i, v in enumerate(pts) if _num(v) is not None]
        if len(coords) >= 2:
            line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            parts.append(f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.2"/>')
        for x, y in coords:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{col}"/>')
    if len(series) > 1:
        lx = pad_l
        legy = pad_t + plot_h + pad_b + 6
        for s_idx, s in enumerate(series):
            col = series_colors[s_idx % len(series_colors)]
            label = _truncate(str(s.get("label") or f"series {s_idx + 1}"), 14)
            parts.append(
                f'<rect x="{lx}" y="{legy - 9}" width="11" height="11" rx="2" fill="{col}"/>'
                f'<text x="{lx + 15}" y="{legy}" font-size="10" fill="{_TEXT}">{_esc(label)}</text>'
            )
            lx += 30 + len(label) * 6
    parts.append("</svg>")
    return "".join(parts)
