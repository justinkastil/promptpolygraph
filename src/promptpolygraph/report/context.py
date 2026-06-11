"""Build a clean, template-ready context dict from raw run artifacts.

`build_context` flattens the run metadata, summary, cases/responses/scores, the
audit (forensic + persona), an optional baseline diff, an optional pairwise A/B
comparison, and branding into a single nested dict whose shape is stable and
trivially consumable by a Jinja2 template. Every optional input degrades
gracefully: missing audit/baseline/pairwise simply yield empty/None entries, and
all-None inputs never raise.

The HTML/Markdown renderers call this and then render a template; the docx/pdf
renderers stay programmatic and do not use this module.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Case, Response, RunMeta, Score
from . import charts as _charts

DEFAULT_ACCENT = "#4f46e5"


# ─── Small value helpers ─────────────────────────────────────────────────────


def _num(v: Any, places: int = 2) -> Optional[str]:
    """Format a number to a fixed number of places, or None if not numeric."""
    if v is None:
        return None
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return str(v)


def _delta(v: Any) -> Optional[str]:
    """Signed delta string (e.g. '+0.50', '-1.20'), or None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "+" if f >= 0 else ""
    return f"{sign}{f:.2f}"


def _verdict_rank(score: Optional[Score]) -> tuple[int, float]:
    """Sort key: failing cases first, then by ascending mean dimension score."""
    if score is None:
        return (0, -1.0)
    failed = 0 if score.verdict_pass is False else (1 if score.verdict_pass else 2)
    vals = [v for v in score.dimensions.values() if v is not None]
    m = sum(vals) / len(vals) if vals else 0.0
    return (failed, m)


def _baseline_deltas(baseline_diff: Optional[dict], cat: str, dims: list[str]) -> list[dict]:
    """Per-dimension delta entries for one category, only where a delta exists."""
    out: list[dict] = []
    if not baseline_diff:
        return out
    table = (baseline_diff.get("by_category") or {}).get(cat) or {}
    for d in dims:
        entry = table.get(d)
        if isinstance(entry, dict) and entry.get("delta") is not None:
            out.append({"dimension": d, "delta": _delta(entry.get("delta")), "raw": entry.get("delta")})
    return out


# ─── Section builders ────────────────────────────────────────────────────────


def _build_cover(run_meta: RunMeta, summary: dict, cases: list[Case], scores: list[Score]) -> dict:
    passing = summary.get("categories_passing", 0)
    total = summary.get("categories_total", 0)
    overall = bool(summary.get("overall_pass", False))
    return {
        "run_id": run_meta.run_id,
        "name": run_meta.name,
        "adapter": run_meta.adapter or None,
        "model": run_meta.model or None,
        "mode": run_meta.mode or None,
        "created_at": run_meta.created_at or None,
        "completed_at": run_meta.completed_at or None,
        "cases_executed": run_meta.completed_cases or len(cases),
        "cases_total": run_meta.total_cases or len(cases),
        "cases_analyzed": len(scores),
        "threshold": _num(summary.get("threshold"), 1),
        "overall_pass": overall,
        "verdict": "PASS" if overall else "FAIL",
        "categories_passing": passing,
        "categories_total": total,
    }


def _build_categories(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
    baseline_diff: Optional[dict],
) -> list[dict]:
    dims = summary.get("dimensions") or []
    cat_scores = summary.get("category_scores") or {}
    resp_by_id = {r.case_id: r for r in responses}
    score_by_id = {s.case_id: s for s in scores}

    cases_by_cat: dict[str, list[Case]] = {}
    for c in cases:
        cases_by_cat.setdefault(c.category or "default", []).append(c)

    # Union of categories seen in the summary and in the actual cases.
    all_cats = sorted(set(cat_scores) | set(cases_by_cat))

    out: list[dict] = []
    for cat in all_cats:
        entry = cat_scores.get(cat) or {}
        dim_scores = [{"dimension": d, "value": _num(entry.get(d))} for d in dims]
        deltas = _baseline_deltas(baseline_diff, cat, dims)

        ordered = sorted(
            cases_by_cat.get(cat, []),
            key=lambda c: _verdict_rank(score_by_id.get(c.id)),
        )
        case_views = [
            _build_case(c, resp_by_id.get(c.id), score_by_id.get(c.id), dims)
            for c in ordered
        ]

        out.append(
            {
                "name": cat,
                "count": entry.get("count", len(cases_by_cat.get(cat, []))),
                "pass": bool(entry.get("pass")),
                "dim_scores": dim_scores,
                "deltas": deltas,
                "cases": case_views,
            }
        )
    return out


def _build_case(case: Case, resp: Optional[Response], score: Optional[Score], dims: list[str]) -> dict:
    ok = bool(score and score.verdict_pass)
    resp_text = (resp.text if resp and resp.text else "") or "(empty)"
    resp_error = resp.error if resp and resp.error else None

    dim_scores = []
    assertions = []
    failure_reason = None
    notes = None
    if score is not None:
        for d in dims:
            v = score.dimensions.get(d)
            dim_scores.append({"dimension": d, "value": (str(v) if v is not None else None)})
        for a in score.assertions or []:
            assertions.append(
                {
                    "kind": a.kind,
                    "passed": bool(a.passed),
                    "description": a.description or "",
                    "detail": a.detail or "",
                }
            )
        failure_reason = score.failure_reason or None
        notes = score.notes or None

    return {
        "id": case.id,
        "verdict": "PASS" if ok else "FAIL",
        "pass": ok,
        "prompt": case.prompt,
        "category": case.category,
        "subcategory": case.subcategory,
        "expected_behavior": case.expected_behavior,
        "expected_shape": case.expected_shape,
        "red_flags": list(case.red_flags or []),
        "tags": list(case.tags or []),
        "response": resp_text,
        "response_error": resp_error,
        "latency_ms": (resp.latency_ms if resp else None),
        "model": (resp.model if resp else None),
        "dim_scores": dim_scores,
        "assertions": assertions,
        "failure_reason": failure_reason,
        "notes": notes,
    }


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort numeric coercion; None when not numeric."""
    if v is None or isinstance(v, bool):
        return float(v) if isinstance(v, bool) else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_return(v: Any) -> Optional[bool]:
    """Interpret a would_return value (bool, number, or yes/no string) as truthy."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v) > 0
    s = str(v).strip().lower()
    if s in ("yes", "true", "y", "1", "would return", "return"):
        return True
    if s in ("no", "false", "n", "0", "would not return"):
        return False
    return None


def _avg(vals: list[float]) -> Optional[str]:
    return _num(sum(vals) / len(vals)) if vals else None


def _build_personas(audit: Optional[dict]) -> list[dict]:
    persona = (audit or {}).get("persona") or {}
    reactions = persona.get("reactions") or []
    out: list[dict] = []
    for r in reactions:
        if not isinstance(r, dict):
            continue
        per_case = []
        trust_vals: list[float] = []
        useful_vals: list[float] = []
        clarity_vals: list[float] = []
        return_flags: list[bool] = []
        verdict_counts: dict[str, int] = {}
        for cr in r.get("reactions") or []:
            if not isinstance(cr, dict):
                continue
            per_case.append(
                {
                    "case_id": cr.get("case_id"),
                    "category": cr.get("category"),
                    "trust": cr.get("trust"),
                    "usefulness": cr.get("usefulness"),
                    "clarity": cr.get("clarity"),
                    "would_return": cr.get("would_return"),
                    "gut_reaction": cr.get("gut_reaction"),
                    "verdict": cr.get("verdict"),
                }
            )
            for key, bucket in (("trust", trust_vals), ("usefulness", useful_vals), ("clarity", clarity_vals)):
                fv = _coerce_float(cr.get(key))
                if fv is not None:
                    bucket.append(fv)
            rb = _coerce_return(cr.get("would_return"))
            if rb is not None:
                return_flags.append(rb)
            v = cr.get("verdict")
            if v not in (None, ""):
                verdict_counts[str(v)] = verdict_counts.get(str(v), 0) + 1

        return_rate = (
            _num(100.0 * sum(1 for b in return_flags if b) / len(return_flags), 0)
            if return_flags
            else None
        )
        out.append(
            {
                "persona": r.get("persona") or r.get("who") or r.get("id") or "Persona",
                "summary": r.get("persona_summary") or r.get("summary") or "",
                "biggest_frustrations": list(r.get("biggest_frustrations") or r.get("frustrations") or []),
                "what_would_win_me": list(r.get("what_would_win_me") or [])
                if isinstance(r.get("what_would_win_me"), list)
                else (r.get("what_would_win_me") or ""),
                "avg_trust": _avg(trust_vals),
                "avg_usefulness": _avg(useful_vals),
                "avg_clarity": _avg(clarity_vals),
                "would_return_rate": return_rate,
                "verdict_counts": verdict_counts,
                "reactions": per_case,
            }
        )
    return out


def _build_persona_comparison(audit: Optional[dict]) -> Optional[dict]:
    persona = (audit or {}).get("persona") or {}
    comparison = persona.get("comparison") or {}
    if not comparison:
        return None
    divergences = comparison.get("divergences") or comparison.get("divergence")
    divergence_count = len(divergences) if isinstance(divergences, (list, tuple)) else None
    blind_spots = comparison.get("human_value_blindspots") or comparison.get("blind_spots") or []
    if not isinstance(blind_spots, (list, tuple)):
        blind_spots = [blind_spots] if blind_spots else []
    return {
        "divergences": divergences,
        "divergence_count": divergence_count,
        "rubric_fidelity_verdict": comparison.get("rubric_fidelity_verdict"),
        "chasing_tail_risks": comparison.get("chasing_tail_risks"),
        "human_value_blindspots": comparison.get("human_value_blindspots"),
        "blind_spots": list(blind_spots),
        "reconciled_priorities": comparison.get("reconciled_priorities"),
        "final_path": comparison.get("final_path"),
    }


def _build_forensic(audit: Optional[dict]) -> Optional[dict]:
    forensic = (audit or {}).get("forensic") or {}
    synthesis = forensic.get("synthesis") or {}
    category_audits = forensic.get("category_audits") or []
    if not synthesis and not category_audits:
        return None

    patterns = []
    for p in synthesis.get("cross_category_patterns") or synthesis.get("patterns") or []:
        if isinstance(p, dict):
            patterns.append(
                {
                    "pattern": p.get("pattern") or p.get("summary") or "",
                    "affected_categories": list(p.get("affected_categories") or []),
                    "shared_root_cause": p.get("shared_root_cause"),
                    "code_locus": p.get("code_locus"),
                }
            )
        else:
            patterns.append({"pattern": str(p), "affected_categories": [], "shared_root_cause": None, "code_locus": None})

    changes = []
    raw_changes = synthesis.get("prioritized_changes") or synthesis.get("ranked_changes") or []
    for i, ch in enumerate(raw_changes, 1):
        if isinstance(ch, dict):
            changes.append(
                {
                    "rank": ch.get("rank", i),
                    "change": ch.get("change") or ch.get("title") or ch.get("summary") or "",
                    "unlocks_categories": list(ch.get("unlocks_categories") or []),
                    "est_after": ch.get("est_after"),
                    "effort": ch.get("effort"),
                    "confidence": ch.get("confidence"),
                    "rationale": ch.get("rationale") or ch.get("why") or "",
                }
            )
        else:
            changes.append(
                {
                    "rank": i,
                    "change": str(ch),
                    "unlocks_categories": [],
                    "est_after": None,
                    "effort": None,
                    "confidence": None,
                    "rationale": "",
                }
            )

    closest = []
    for cp in synthesis.get("closest_to_pass") or []:
        closest.append(cp if isinstance(cp, str) else (cp.get("category") if isinstance(cp, dict) else str(cp)))

    cat_audits = []
    for ca in category_audits:
        if not isinstance(ca, dict):
            continue
        cat_audits.append(
            {
                "category": ca.get("category"),
                "gap_dims": list(ca.get("gap_dims") or []),
                "highest_leverage_one_liner": ca.get("highest_leverage_one_liner"),
                "failure_modes": [
                    {
                        "dimension": fm.get("dimension"),
                        "pattern": fm.get("pattern"),
                        "example_case_ids": list(fm.get("example_case_ids") or []),
                        "rubric_criterion_missed": fm.get("rubric_criterion_missed"),
                        "code_locus": fm.get("code_locus"),
                        "frequency": fm.get("frequency"),
                    }
                    for fm in (ca.get("failure_modes") or [])
                    if isinstance(fm, dict)
                ],
                "leverage_changes": [
                    {
                        "change": lc.get("change"),
                        "target_dimension": lc.get("target_dimension"),
                        "code_locus": lc.get("code_locus"),
                        "est_impact": lc.get("est_impact"),
                        "effort": lc.get("effort"),
                        "confidence": lc.get("confidence"),
                        "suggested_fix": (
                            {
                                "file": (lc.get("suggested_fix") or {}).get("file"),
                                "locus": (lc.get("suggested_fix") or {}).get("locus"),
                                "rationale": (lc.get("suggested_fix") or {}).get("rationale"),
                                "diff": (lc.get("suggested_fix") or {}).get("diff"),
                            }
                            if isinstance(lc.get("suggested_fix"), dict)
                            else None
                        ),
                    }
                    for lc in (ca.get("leverage_changes") or [])
                    if isinstance(lc, dict)
                ],
            }
        )

    return {
        "patterns": patterns,
        "prioritized_changes": changes,
        "closest_to_pass": closest,
        "narrative": synthesis.get("narrative"),
        "category_audits": cat_audits,
    }


def _build_pairwise(pairwise: Optional[dict]) -> Optional[dict]:
    if not pairwise:
        return None
    a = pairwise.get("run_a", "a")
    b = pairwise.get("run_b", "b")
    by_cat = []
    for cat in sorted(pairwise.get("by_category") or {}):
        rec = (pairwise.get("by_category") or {}).get(cat) or {}
        by_cat.append({"category": cat, "a": rec.get("a", 0), "b": rec.get("b", 0), "tie": rec.get("tie", 0)})
    cases = []
    for c in pairwise.get("cases") or []:
        cases.append(
            {
                "case_id": c.get("case_id", ""),
                "winner": c.get("winner", ""),
                "a_mean": _num(c.get("a_mean")),
                "b_mean": _num(c.get("b_mean")),
            }
        )
    return {
        "run_a": a,
        "run_b": b,
        "wins_a": pairwise.get("wins_a", 0),
        "wins_b": pairwise.get("wins_b", 0),
        "ties": pairwise.get("ties", 0),
        "by_category": by_cat,
        "cases": cases,
    }


def _build_trend_series(summary: dict, baseline_diff: Optional[dict]) -> list[dict]:
    """Per-dimension [baseline, current] series when a baseline diff is present.

    The baseline diff carries, per category/dimension, the prior ("base") and
    current ("value") means; we average across categories to a per-dimension
    pair so the report can show movement at a glance. Returns [] when no
    baseline data exists so the template simply omits the trend chart.
    """
    if not baseline_diff or not baseline_diff.get("by_category"):
        return []
    dims = list(summary.get("dimensions") or [])
    by_cat = baseline_diff.get("by_category") or {}
    out: list[dict] = []
    for d in dims:
        base_vals: list[float] = []
        cur_vals: list[float] = []
        for tab in by_cat.values():
            if not isinstance(tab, dict):
                continue
            ent = tab.get(d)
            if not isinstance(ent, dict):
                continue
            for key, bucket in (("base", base_vals), ("baseline", base_vals),
                                ("value", cur_vals), ("current", cur_vals)):
                v = ent.get(key)
                try:
                    if v is not None:
                        bucket.append(float(v))
                except (TypeError, ValueError):
                    pass
        base_mean = sum(base_vals) / len(base_vals) if base_vals else None
        cur_mean = sum(cur_vals) / len(cur_vals) if cur_vals else None
        if base_mean is not None or cur_mean is not None:
            out.append({"label": d, "points": [base_mean, cur_mean]})
    return out


def _build_charts(
    summary: dict,
    audit: Optional[dict],
    branding: dict,
    baseline_diff: Optional[dict],
) -> dict:
    """Precompute inline-SVG chart strings for the template to embed verbatim.

    Each value is a complete ``<svg>`` string (or None when the underlying data
    is absent, so the template can skip the block). Branding accent tints the
    chart chrome. Never raises: a chart failure degrades to None.
    """
    accent = branding.get("accent") or DEFAULT_ACCENT

    def _safe(fn: Any) -> Optional[str]:
        try:
            svg = fn()
            return svg if svg and svg.lstrip().startswith("<svg") else None
        except Exception:
            return None

    series = _build_trend_series(summary, baseline_diff)
    threshold = None
    try:
        threshold = float(summary.get("threshold")) if summary.get("threshold") is not None else None
    except (TypeError, ValueError):
        threshold = None

    return {
        "heatmap": _safe(lambda: _charts.score_heatmap(summary, accent=accent)),
        "dimension_bars": _safe(lambda: _charts.dimension_bars(summary, accent=accent)),
        "persona_radar": _safe(lambda: _charts.persona_radar(audit or {}, accent=accent)),
        "trend": (
            _safe(lambda: _charts.trend_line(series, accent=accent, threshold=threshold))
            if series else None
        ),
    }


def _build_branding(branding: Optional[dict], run_meta: RunMeta) -> dict:
    branding = branding or {}
    title = branding.get("title") or f"Polygraph Review — {run_meta.name}"
    accent = branding.get("accent") or DEFAULT_ACCENT
    logo = branding.get("logo")
    return {"title": title, "accent": accent, "logo": logo}


# ─── Public entry ─────────────────────────────────────────────────────────────


def build_context(
    run_meta: RunMeta,
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
    *,
    rubric: Any,
    audit: dict | None = None,
    baseline_diff: dict | None = None,
    pairwise: dict | None = None,
    branding: dict | None = None,
) -> dict:
    """Produce a stable, template-ready context dict from raw run artifacts.

    All optional inputs (`audit`, `baseline_diff`, `pairwise`, `branding`) may be
    None and the result still renders. `rubric` is accepted for signature
    symmetry; its content is already folded into `summary`.
    """
    _ = rubric
    summary = summary or {}
    cost = summary.get("cost") or {}
    lat = summary.get("latency") or {}
    branding_block = _build_branding(branding, run_meta)

    return {
        "cover": _build_cover(run_meta, summary, cases, scores),
        "charts": _build_charts(summary, audit, branding_block, baseline_diff),
        "dimensions": list(summary.get("dimensions") or []),
        "has_baseline": bool(baseline_diff and baseline_diff.get("by_category")),
        "categories": _build_categories(cases, responses, scores, summary, baseline_diff),
        "personas": _build_personas(audit),
        "persona_comparison": _build_persona_comparison(audit),
        "forensic": _build_forensic(audit),
        "pairwise": _build_pairwise(pairwise),
        "cost": {
            "tokens_in": cost.get("tokens_in", 0),
            "tokens_out": cost.get("tokens_out", 0),
            "usd": _num(cost.get("usd"), 4) if cost.get("usd") is not None else None,
        },
        "latency": {
            "p50_ms": _num(lat.get("p50_ms"), 1),
            "p95_ms": _num(lat.get("p95_ms"), 1),
            "mean_ms": _num(lat.get("mean_ms"), 1),
        },
        "assertion_pass_rate": _num((summary.get("assertion_pass_rate") or 0) * 100, 1),
        "agreement": _num(summary.get("agreement_mean")) if summary.get("agreement_mean") is not None else None,
        "branding": branding_block,
    }
