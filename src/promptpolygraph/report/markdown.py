"""Markdown rendering of a polygraph run review.

`render_markdown` produces a single, self-describing review document: a cover
block, a category x dimension score table (with a baseline-delta column when a
baseline diff is supplied), per-category deep dives ordered worst-verdict-first,
a persona panel, a forensic synthesis, an optional A/B section, and a cost &
latency footer. Everything degrades gracefully when optional inputs are missing.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Case, Response, Rubric, RunMeta, Score
from ._env import render_template
from .context import build_context


# ─── Small shared helpers (also reused conceptually by the other renderers) ──


def _fmt_num(v: Any, places: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_delta(v: Any) -> str:
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "+" if f >= 0 else ""
    return f"{sign}{f:.2f}"


def _pass_mark(ok: Any) -> str:
    return "✓" if ok else "✗"


def _verdict_rank(score: Optional[Score]) -> tuple[int, float]:
    """Sort key: failing cases first, then by ascending mean dimension score."""
    if score is None:
        return (0, -1.0)
    failed = 0 if score.verdict_pass is False else (1 if score.verdict_pass else 2)
    vals = [v for v in score.dimensions.values() if v is not None]
    m = sum(vals) / len(vals) if vals else 0.0
    return (failed, m)


def _baseline_delta(baseline_diff: Optional[dict], cat: str, dim: str) -> Optional[float]:
    if not baseline_diff:
        return None
    table = (baseline_diff.get("by_category") or {}).get(cat) or {}
    entry = table.get(dim)
    if not isinstance(entry, dict):
        return None
    return entry.get("delta")


# ─── Section renderers ───────────────────────────────────────────────────────


def _cover(run_meta: RunMeta, summary: dict, cases: list[Case], scores: list[Score]) -> list[str]:
    passing = summary.get("categories_passing", 0)
    total = summary.get("categories_total", 0)
    overall = summary.get("overall_pass", False)
    verdict = "PASS" if overall else "FAIL"
    L = [
        f"# Polygraph Review — {run_meta.name}",
        "",
        f"**Run ID:** `{run_meta.run_id}`  ",
        f"**Adapter:** {run_meta.adapter or '—'}  ",
        f"**Model:** {run_meta.model or '—'}  ",
        f"**Mode:** {run_meta.mode or '—'}  ",
        f"**Created:** {run_meta.created_at or '—'}  ",
        f"**Completed:** {run_meta.completed_at or '—'}  ",
        f"**Cases executed:** {run_meta.completed_cases or len(cases)} / {run_meta.total_cases or len(cases)}  ",
        f"**Cases analyzed:** {len(scores)}  ",
        f"**Threshold:** {_fmt_num(summary.get('threshold'), 1)}  ",
        "",
        f"## Overall verdict: **{verdict}** — {passing}/{total} categories passing",
        "",
    ]
    return L


def _category_table(summary: dict, baseline_diff: Optional[dict]) -> list[str]:
    dims = summary.get("dimensions") or []
    cat_scores = summary.get("category_scores") or {}
    has_base = bool(baseline_diff and baseline_diff.get("by_category"))

    header = ["Category", "Count", *dims, "Pass"]
    if has_base:
        header.append("Δ vs baseline")
    L = ["## Category scores", "", "| " + " | ".join(header) + " |"]
    L.append("| " + " | ".join(["---"] * len(header)) + " |")

    for cat in sorted(cat_scores):
        entry = cat_scores[cat] or {}
        row = [cat, str(entry.get("count", 0))]
        for d in dims:
            row.append(_fmt_num(entry.get(d)))
        row.append(_pass_mark(entry.get("pass")))
        if has_base:
            deltas = []
            for d in dims:
                dv = _baseline_delta(baseline_diff, cat, d)
                if dv is not None:
                    deltas.append(f"{d} {_fmt_delta(dv)}")
            row.append(", ".join(deltas) if deltas else "—")
        L.append("| " + " | ".join(row) + " |")
    L.append("")
    return L


def _case_detail(case: Case, resp: Optional[Response], score: Optional[Score], dims: list[str]) -> list[str]:
    verdict = "PASS" if (score and score.verdict_pass) else "FAIL"
    L = [f"#### Case `{case.id}` — {verdict}", ""]
    L.append(f"**Prompt:** {case.prompt}")
    L.append("")
    if case.expected_behavior:
        L.append(f"**Expected behavior:** {case.expected_behavior}")
        L.append("")
    if case.red_flags:
        L.append("**Red flags:**")
        for rf in case.red_flags:
            L.append(f"- {rf}")
        L.append("")
    L.append("**Response:**")
    L.append("")
    L.append("```")
    L.append((resp.text if resp and resp.text else "(empty)"))
    if resp and resp.error:
        L.append(f"[error: {resp.error}]")
    L.append("```")
    L.append("")
    if score:
        dim_bits = []
        for d in dims:
            dim_bits.append(f"{d}={_fmt_num(score.dimensions.get(d), 0) if score.dimensions.get(d) is not None else 'n/a'}")
        L.append("**Scores:** " + ", ".join(dim_bits))
        L.append("")
        if score.assertions:
            L.append("**Assertions:**")
            for a in score.assertions:
                L.append(f"- {_pass_mark(a.passed)} `{a.kind}` {a.description or ''} {a.detail or ''}".rstrip())
            L.append("")
        if score.failure_reason:
            L.append(f"**Failure reason:** {score.failure_reason}")
            L.append("")
        if score.notes:
            L.append(f"**Notes:** {score.notes}")
            L.append("")
    return L


def _per_category_sections(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
) -> list[str]:
    dims = summary.get("dimensions") or []
    resp_by_id = {r.case_id: r for r in responses}
    score_by_id = {s.case_id: s for s in scores}
    cats: dict[str, list[Case]] = {}
    for c in cases:
        cats.setdefault(c.category or "default", []).append(c)

    L = ["## Per-category detail", ""]
    for cat in sorted(cats):
        L.append(f"### {cat}")
        L.append("")
        ordered = sorted(
            cats[cat],
            key=lambda c: _verdict_rank(score_by_id.get(c.id)),
        )
        for c in ordered:
            L.extend(_case_detail(c, resp_by_id.get(c.id), score_by_id.get(c.id), dims))
    return L


def _persona_panel(audit: Optional[dict]) -> list[str]:
    L = ["## Persona panel", ""]
    persona = (audit or {}).get("persona") or {}
    reactions = persona.get("reactions") or []
    if not reactions and not persona.get("comparison"):
        L.append("_No persona reactions available for this run._")
        L.append("")
        return L
    for r in reactions:
        if not isinstance(r, dict):
            continue
        who = r.get("who") or r.get("persona") or r.get("id") or "Persona"
        L.append(f"### {who}")
        summ = r.get("summary") or r.get("reaction") or ""
        if summ:
            L.append(summ)
            L.append("")
        frustrations = r.get("frustrations") or r.get("biggest_frustrations") or []
        if frustrations:
            L.append("**Biggest frustrations:**")
            for f in frustrations:
                L.append(f"- {f}")
            L.append("")
    comparison = persona.get("comparison") or {}
    if comparison:
        L.append("### Rubric vs persona divergence")
        L.append("")
        div = comparison.get("divergence") or comparison.get("summary")
        if div:
            L.append(str(div))
            L.append("")
        items = comparison.get("items") or comparison.get("divergences") or []
        for it in items:
            if isinstance(it, dict):
                cat = it.get("category", "")
                note = it.get("note") or it.get("detail") or ""
                L.append(f"- **{cat}**: {note}".rstrip())
            else:
                L.append(f"- {it}")
        if items:
            L.append("")
    return L


def _forensic_synthesis(audit: Optional[dict]) -> list[str]:
    L = ["## Forensic synthesis", ""]
    forensic = (audit or {}).get("forensic") or {}
    synthesis = forensic.get("synthesis") or {}
    if not synthesis and not forensic.get("category_audits"):
        L.append("_No forensic synthesis available for this run._")
        L.append("")
        return L

    patterns = synthesis.get("cross_category_patterns") or synthesis.get("patterns") or []
    if patterns:
        L.append("### Cross-category patterns")
        for p in patterns:
            if isinstance(p, dict):
                L.append(f"- {p.get('pattern') or p.get('summary') or p}")
            else:
                L.append(f"- {p}")
        L.append("")

    changes = synthesis.get("prioritized_changes") or synthesis.get("ranked_changes") or []
    if changes:
        L.append("### Prioritized changes")
        for i, ch in enumerate(changes, 1):
            if isinstance(ch, dict):
                title = ch.get("change") or ch.get("title") or ch.get("summary") or str(ch)
                why = ch.get("rationale") or ch.get("why") or ""
                L.append(f"{i}. **{title}**" + (f" — {why}" if why else ""))
            else:
                L.append(f"{i}. {ch}")
        L.append("")
    return L


def _ab_section(pairwise: Optional[dict]) -> list[str]:
    if not pairwise:
        return []
    L = ["## A/B comparison", ""]
    a = pairwise.get("run_a", "a")
    b = pairwise.get("run_b", "b")
    L.append(
        f"**{a}** wins: {pairwise.get('wins_a', 0)} · "
        f"**{b}** wins: {pairwise.get('wins_b', 0)} · "
        f"ties: {pairwise.get('ties', 0)}"
    )
    L.append("")
    by_cat = pairwise.get("by_category") or {}
    if by_cat:
        L.append(f"| Category | {a} | {b} | tie |")
        L.append("| --- | --- | --- | --- |")
        for cat in sorted(by_cat):
            rec = by_cat[cat] or {}
            L.append(f"| {cat} | {rec.get('a', 0)} | {rec.get('b', 0)} | {rec.get('tie', 0)} |")
        L.append("")
    cases = pairwise.get("cases") or []
    if cases:
        L.append(f"| Case | Winner | {a} mean | {b} mean |")
        L.append("| --- | --- | --- | --- |")
        for c in cases:
            L.append(
                f"| `{c.get('case_id', '')}` | {c.get('winner', '')} | "
                f"{_fmt_num(c.get('a_mean'))} | {_fmt_num(c.get('b_mean'))} |"
            )
        L.append("")
    return L


def _cost_latency_footer(summary: dict) -> list[str]:
    cost = summary.get("cost") or {}
    lat = summary.get("latency") or {}
    agreement = summary.get("agreement_mean")
    L = [
        "## Cost & latency",
        "",
        f"- **Tokens in:** {cost.get('tokens_in', 0):,}",
        f"- **Tokens out:** {cost.get('tokens_out', 0):,}",
        f"- **Cost (USD):** {('$' + _fmt_num(cost.get('usd'), 4)) if cost.get('usd') is not None else '—'}",
        f"- **Latency p50:** {_fmt_num(lat.get('p50_ms'), 1)} ms",
        f"- **Latency p95:** {_fmt_num(lat.get('p95_ms'), 1)} ms",
        f"- **Latency mean:** {_fmt_num(lat.get('mean_ms'), 1)} ms",
        f"- **Assertion pass rate:** {_fmt_num((summary.get('assertion_pass_rate') or 0) * 100, 1)}%",
        f"- **Judge agreement (mean):** {_fmt_num(agreement) if agreement is not None else '—'}",
        "",
    ]
    return L


# ─── Public entry ─────────────────────────────────────────────────────────────


def render_markdown(
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
    """Render the full review as a Markdown string via a Jinja2 template.

    `template` selects a built-in set ('default' or 'minimal'); `template_dir`,
    if given, overrides the built-ins. Calling with only the original arguments
    is fully backward-compatible (uses the 'default' set, no branding).
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
        "report.md.j2",
        context,
        template=template,
        template_dir=template_dir,
    )
