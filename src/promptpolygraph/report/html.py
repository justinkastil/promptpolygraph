"""Self-contained HTML rendering of a polygraph run review.

`render_html` mirrors the Markdown report's content as a single offline HTML
file: inline CSS (no external assets), a sortable/filterable category table, and
per-case detail rendered as collapsible `<details>` blocks. The persona panel,
forensic synthesis, optional A/B section, and the cost & latency footer all
appear. Every optional input degrades gracefully when missing, and all text is
HTML-escaped so arbitrary prompts/responses cannot break the markup.
"""

from __future__ import annotations

from html import escape as _esc
from typing import Any, Optional

from ..models import Case, Response, Rubric, RunMeta, Score
from ._env import render_template
from .context import build_context
from .markdown import _fmt_delta, _fmt_num, _verdict_rank


def _e(v: Any) -> str:
    """HTML-escape any value, mapping None to an em dash."""
    if v is None:
        return "&mdash;"
    return _esc(str(v))


def _pass_badge(ok: Any) -> str:
    cls = "pass" if ok else "fail"
    label = "PASS" if ok else "FAIL"
    return f'<span class="badge {cls}">{label}</span>'


_CSS = """
:root {
  --fg: #1c1c1e; --muted: #6b6b70; --bg: #ffffff; --panel: #f6f6f8;
  --border: #d9d9de; --pass: #1b7f37; --fail: #b01b1b; --accent: #3a5cff;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 0 4rem; color: var(--fg); background: var(--bg);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem; }
h1 { font-size: 1.9rem; margin: 0 0 .25rem; }
h2 { font-size: 1.4rem; margin: 2.25rem 0 .75rem; padding-bottom: .3rem; border-bottom: 2px solid var(--border); }
h3 { font-size: 1.15rem; margin: 1.5rem 0 .5rem; }
h4 { font-size: 1rem; margin: 0; }
.muted { color: var(--muted); }
.cover dl { display: grid; grid-template-columns: max-content 1fr; gap: .15rem 1rem; margin: 1rem 0; }
.cover dt { font-weight: 600; color: var(--muted); }
.cover dd { margin: 0; }
.verdict { font-size: 1.25rem; font-weight: 700; margin: 1rem 0; padding: .75rem 1rem; border-radius: 8px; background: var(--panel); }
.verdict.pass { color: var(--pass); }
.verdict.fail { color: var(--fail); }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 700; letter-spacing: .03em; }
.badge.pass { background: #e3f4e8; color: var(--pass); }
.badge.fail { background: #fae3e3; color: var(--fail); }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; font-size: .92rem; }
th, td { border: 1px solid var(--border); padding: .4rem .55rem; text-align: left; }
th { background: var(--panel); cursor: pointer; user-select: none; position: relative; }
th.sortable::after { content: " \\2195"; color: var(--muted); font-size: .8em; }
tbody tr:nth-child(even) { background: #fbfbfc; }
.filter { margin: .25rem 0 .5rem; }
.filter input { padding: .35rem .5rem; border: 1px solid var(--border); border-radius: 6px; width: 16rem; max-width: 100%; }
details { border: 1px solid var(--border); border-radius: 8px; margin: .5rem 0; background: var(--panel); }
details > summary { cursor: pointer; padding: .6rem .8rem; font-weight: 600; list-style: none; }
details > summary::-webkit-details-marker { display: none; }
details[open] > summary { border-bottom: 1px solid var(--border); }
.case-body { padding: .25rem .8rem .8rem; }
.case-body dl { display: grid; grid-template-columns: max-content 1fr; gap: .1rem .8rem; margin: .5rem 0; }
.case-body dt { font-weight: 600; color: var(--muted); }
.case-body dd { margin: 0; }
pre { background: #1c1c1e; color: #f0f0f2; padding: .75rem; border-radius: 6px; overflow-x: auto; font-family: var(--mono); font-size: .85rem; white-space: pre-wrap; word-break: break-word; }
ul { margin: .35rem 0 .75rem 1.25rem; padding: 0; }
.assert.pass::before { content: "\\2713 "; color: var(--pass); font-weight: 700; }
.assert.fail::before { content: "\\2717 "; color: var(--fail); font-weight: 700; }
code { font-family: var(--mono); background: #ececed; padding: .05rem .3rem; border-radius: 4px; font-size: .85em; }
.footer dl { display: grid; grid-template-columns: max-content 1fr; gap: .1rem 1rem; }
.footer dt { font-weight: 600; color: var(--muted); }
.note { color: var(--muted); font-style: italic; }
"""

_SCRIPT = """
function ppFilter(id, q){
  var t = document.getElementById(id); if(!t) return;
  var rows = t.tBodies[0].rows; q = q.toLowerCase();
  for (var i=0;i<rows.length;i++){
    rows[i].style.display = rows[i].innerText.toLowerCase().indexOf(q) > -1 ? "" : "none";
  }
}
function ppSort(th){
  var t = th.closest("table"), tb = t.tBodies[0];
  var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
  var dir = th.getAttribute("data-dir") === "asc" ? -1 : 1;
  th.setAttribute("data-dir", dir === 1 ? "asc" : "desc");
  var rows = Array.prototype.slice.call(tb.rows);
  rows.sort(function(a,b){
    var x = a.cells[idx].innerText.trim(), y = b.cells[idx].innerText.trim();
    var nx = parseFloat(x), ny = parseFloat(y);
    if(!isNaN(nx) && !isNaN(ny)) return (nx-ny)*dir;
    return x.localeCompare(y)*dir;
  });
  rows.forEach(function(r){ tb.appendChild(r); });
}
"""


def _cover(run_meta: RunMeta, summary: dict, cases: list[Case], scores: list[Score]) -> str:
    passing = summary.get("categories_passing", 0)
    total = summary.get("categories_total", 0)
    overall = bool(summary.get("overall_pass", False))
    vcls = "pass" if overall else "fail"
    vlabel = "PASS" if overall else "FAIL"
    rows = [
        ("Run ID", f"<code>{_e(run_meta.run_id)}</code>"),
        ("Adapter", _e(run_meta.adapter)),
        ("Model", _e(run_meta.model)),
        ("Mode", _e(run_meta.mode)),
        ("Created", _e(run_meta.created_at)),
        ("Completed", _e(run_meta.completed_at)),
        ("Cases executed", _e(f"{run_meta.completed_cases or len(cases)} / {run_meta.total_cases or len(cases)}")),
        ("Cases analyzed", _e(len(scores))),
        ("Threshold", _e(_fmt_num(summary.get("threshold"), 1))),
    ]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return (
        f'<section class="cover"><h1>Polygraph Review &mdash; {_e(run_meta.name)}</h1>'
        f"<dl>{dl}</dl>"
        f'<div class="verdict {vcls}">Overall verdict: {vlabel} &mdash; {passing}/{total} categories passing</div>'
        "</section>"
    )


def _category_table(summary: dict, baseline_diff: Optional[dict]) -> str:
    dims = summary.get("dimensions") or []
    cat_scores = summary.get("category_scores") or {}
    has_base = bool(baseline_diff and baseline_diff.get("by_category"))

    cols = ["Category", "Count", *dims, "Pass"] + (["Δ vs baseline"] if has_base else [])
    head = "".join(f'<th class="sortable" onclick="ppSort(this)">{_e(c)}</th>' for c in cols)

    body_rows = []
    for cat in sorted(cat_scores):
        entry = cat_scores[cat] or {}
        cells = [f"<td>{_e(cat)}</td>", f"<td>{_e(entry.get('count', 0))}</td>"]
        for d in dims:
            cells.append(f"<td>{_e(_fmt_num(entry.get(d)))}</td>")
        cells.append(f"<td>{_pass_badge(entry.get('pass'))}</td>")
        if has_base:
            base_tab = (baseline_diff.get("by_category") or {}).get(cat) or {}
            deltas = []
            for d in dims:
                ent = base_tab.get(d)
                if isinstance(ent, dict) and ent.get("delta") is not None:
                    deltas.append(f"{d} {_fmt_delta(ent.get('delta'))}")
            cells.append(f"<td>{_e(', '.join(deltas)) if deltas else '&mdash;'}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<section><h2>Category scores</h2>'
        '<div class="filter"><input type="text" placeholder="Filter categories…" '
        'oninput="ppFilter(\'cat-table\', this.value)"></div>'
        f'<table id="cat-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></section>'
    )


def _case_detail(case: Case, resp: Optional[Response], score: Optional[Score], dims: list[str]) -> str:
    ok = bool(score and score.verdict_pass)
    summary_line = f"<summary>{_pass_badge(ok)} &nbsp; <code>{_e(case.id)}</code></summary>"

    rows = [("Prompt", _e(case.prompt))]
    if case.expected_behavior:
        rows.append(("Expected behavior", _e(case.expected_behavior)))
    dl_top = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)

    parts = [f'<div class="case-body"><dl>{dl_top}</dl>']

    if case.red_flags:
        flags = "".join(f"<li>{_e(rf)}</li>" for rf in case.red_flags)
        parts.append(f"<p><strong>Red flags:</strong></p><ul>{flags}</ul>")

    resp_text = resp.text if resp and resp.text else "(empty)"
    err = f"\n[error: {resp.error}]" if resp and resp.error else ""
    parts.append(f"<p><strong>Response:</strong></p><pre>{_esc(resp_text + err)}</pre>")

    if score:
        dim_bits = []
        for d in dims:
            v = score.dimensions.get(d)
            dim_bits.append(f"{_esc(d)}={_fmt_num(v, 0) if v is not None else 'n/a'}")
        parts.append(f"<p><strong>Scores:</strong> {' &middot; '.join(dim_bits)}</p>")
        if score.assertions:
            items = []
            for a in score.assertions:
                cls = "pass" if a.passed else "fail"
                detail = f" {a.description or ''} {a.detail or ''}".rstrip()
                items.append(f'<li class="assert {cls}"><code>{_e(a.kind)}</code>{_esc(detail)}</li>')
            parts.append(f"<p><strong>Assertions:</strong></p><ul>{''.join(items)}</ul>")
        kv = []
        if score.failure_reason:
            kv.append(("Failure reason", _e(score.failure_reason)))
        if score.notes:
            kv.append(("Notes", _e(score.notes)))
        if kv:
            parts.append("<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv) + "</dl>")

    parts.append("</div>")
    return f"<details>{summary_line}{''.join(parts)}</details>"


def _per_category_sections(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
) -> str:
    dims = summary.get("dimensions") or []
    resp_by_id = {r.case_id: r for r in responses}
    score_by_id = {s.case_id: s for s in scores}
    cats: dict[str, list[Case]] = {}
    for c in cases:
        cats.setdefault(c.category or "default", []).append(c)

    out = ["<section><h2>Per-category detail</h2>"]
    for cat in sorted(cats):
        out.append(f"<h3>{_e(cat)}</h3>")
        ordered = sorted(cats[cat], key=lambda c: _verdict_rank(score_by_id.get(c.id)))
        for c in ordered:
            out.append(_case_detail(c, resp_by_id.get(c.id), score_by_id.get(c.id), dims))
    out.append("</section>")
    return "".join(out)


def _persona_panel(audit: Optional[dict]) -> str:
    persona = (audit or {}).get("persona") or {}
    reactions = persona.get("reactions") or []
    comparison = persona.get("comparison") or {}
    out = ["<section><h2>Persona panel</h2>"]
    if not reactions and not comparison:
        out.append('<p class="note">No persona reactions available for this run.</p></section>')
        return "".join(out)

    for r in reactions:
        if not isinstance(r, dict):
            continue
        who = r.get("who") or r.get("persona") or r.get("id") or "Persona"
        out.append(f"<h3>{_e(who)}</h3>")
        summ = r.get("summary") or r.get("reaction") or ""
        if summ:
            out.append(f"<p>{_e(summ)}</p>")
        frustrations = r.get("frustrations") or r.get("biggest_frustrations") or []
        if frustrations:
            items = "".join(f"<li>{_e(f)}</li>" for f in frustrations)
            out.append(f"<p><strong>Biggest frustrations:</strong></p><ul>{items}</ul>")

    if comparison:
        out.append("<h3>Rubric vs persona divergence</h3>")
        div = comparison.get("divergence") or comparison.get("summary")
        if div:
            out.append(f"<p>{_e(div)}</p>")
        items = comparison.get("items") or comparison.get("divergences") or []
        if items:
            lis = []
            for it in items:
                if isinstance(it, dict):
                    cat = it.get("category", "")
                    note = it.get("note") or it.get("detail") or ""
                    lis.append(f"<li><strong>{_e(cat)}</strong>: {_e(note)}</li>")
                else:
                    lis.append(f"<li>{_e(it)}</li>")
            out.append(f"<ul>{''.join(lis)}</ul>")
    out.append("</section>")
    return "".join(out)


def _forensic_synthesis(audit: Optional[dict]) -> str:
    forensic = (audit or {}).get("forensic") or {}
    synthesis = forensic.get("synthesis") or {}
    out = ["<section><h2>Forensic synthesis</h2>"]
    if not synthesis and not forensic.get("category_audits"):
        out.append('<p class="note">No forensic synthesis available for this run.</p></section>')
        return "".join(out)

    patterns = synthesis.get("cross_category_patterns") or synthesis.get("patterns") or []
    if patterns:
        out.append("<h3>Cross-category patterns</h3><ul>")
        for p in patterns:
            txt = (p.get("pattern") or p.get("summary") or str(p)) if isinstance(p, dict) else p
            out.append(f"<li>{_e(txt)}</li>")
        out.append("</ul>")

    changes = synthesis.get("prioritized_changes") or synthesis.get("ranked_changes") or []
    if changes:
        out.append("<h3>Prioritized changes</h3><ol>")
        for ch in changes:
            if isinstance(ch, dict):
                title = ch.get("change") or ch.get("title") or ch.get("summary") or str(ch)
                why = ch.get("rationale") or ch.get("why") or ""
                txt = f"<strong>{_e(title)}</strong>" + (f" &mdash; {_e(why)}" if why else "")
            else:
                txt = _e(ch)
            out.append(f"<li>{txt}</li>")
        out.append("</ol>")
    out.append("</section>")
    return "".join(out)


def _ab_section(pairwise: Optional[dict]) -> str:
    if not pairwise:
        return ""
    a = pairwise.get("run_a", "a")
    b = pairwise.get("run_b", "b")
    out = [
        "<section><h2>A/B comparison</h2>",
        f"<p><strong>{_e(a)}</strong> wins: {_e(pairwise.get('wins_a', 0))} &middot; "
        f"<strong>{_e(b)}</strong> wins: {_e(pairwise.get('wins_b', 0))} &middot; "
        f"ties: {_e(pairwise.get('ties', 0))}</p>",
    ]
    by_cat = pairwise.get("by_category") or {}
    if by_cat:
        rows = []
        for cat in sorted(by_cat):
            rec = by_cat[cat] or {}
            rows.append(
                f"<tr><td>{_e(cat)}</td><td>{_e(rec.get('a', 0))}</td>"
                f"<td>{_e(rec.get('b', 0))}</td><td>{_e(rec.get('tie', 0))}</td></tr>"
            )
        out.append(
            f"<table><thead><tr><th>Category</th><th>{_e(a)}</th><th>{_e(b)}</th><th>tie</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    cases = pairwise.get("cases") or []
    if cases:
        rows = []
        for c in cases:
            rows.append(
                f"<tr><td><code>{_e(c.get('case_id', ''))}</code></td><td>{_e(c.get('winner', ''))}</td>"
                f"<td>{_e(_fmt_num(c.get('a_mean')))}</td><td>{_e(_fmt_num(c.get('b_mean')))}</td></tr>"
            )
        out.append(
            f"<table id=\"ab-cases\"><thead><tr><th class=\"sortable\" onclick=\"ppSort(this)\">Case</th>"
            f"<th class=\"sortable\" onclick=\"ppSort(this)\">Winner</th>"
            f"<th class=\"sortable\" onclick=\"ppSort(this)\">{_e(a)} mean</th>"
            f"<th class=\"sortable\" onclick=\"ppSort(this)\">{_e(b)} mean</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    out.append("</section>")
    return "".join(out)


def _cost_latency_footer(summary: dict) -> str:
    cost = summary.get("cost") or {}
    lat = summary.get("latency") or {}
    agreement = summary.get("agreement_mean")
    usd = ("$" + _fmt_num(cost.get("usd"), 4)) if cost.get("usd") is not None else "&mdash;"
    rows = [
        ("Tokens in", f"{cost.get('tokens_in', 0):,}"),
        ("Tokens out", f"{cost.get('tokens_out', 0):,}"),
        ("Cost (USD)", usd),
        ("Latency p50", f"{_fmt_num(lat.get('p50_ms'), 1)} ms"),
        ("Latency p95", f"{_fmt_num(lat.get('p95_ms'), 1)} ms"),
        ("Latency mean", f"{_fmt_num(lat.get('mean_ms'), 1)} ms"),
        ("Assertion pass rate", f"{_fmt_num((summary.get('assertion_pass_rate') or 0) * 100, 1)}%"),
        ("Judge agreement (mean)", _fmt_num(agreement) if agreement is not None else "&mdash;"),
    ]
    dl = "".join(f"<dt>{_e(k)}</dt><dd>{v}</dd>" for k, v in rows)
    return f'<section class="footer"><h2>Cost &amp; latency</h2><dl>{dl}</dl></section>'


def render_html(
    run_meta: RunMeta,
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
    *,
    rubric: Rubric,
    audit: dict | None = None,
    baseline_diff: dict | None = None,
    pairwise: dict | None = None,
    template: str = "default",
    template_dir: str | None = None,
    branding: dict | None = None,
) -> str:
    """Render the full review as a single self-contained HTML document.

    The document is rendered from a Jinja2 template with inline CSS (no external
    assets) and HTML autoescaping. `template` selects a built-in set ('default'
    or 'minimal'); `template_dir`, if given, overrides the built-ins. `branding`
    may supply `title`, `accent` (hex), and `logo`. Calling with only the
    original arguments is fully backward-compatible.
    """
    context = build_context(
        run_meta,
        cases,
        responses,
        scores,
        summary,
        rubric=rubric,
        audit=audit,
        baseline_diff=baseline_diff,
        pairwise=pairwise,
        branding=branding,
    )
    return render_template(
        "report.html.j2",
        context,
        template=template,
        template_dir=template_dir,
    )
