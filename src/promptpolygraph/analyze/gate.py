"""Pass/fail gating and run-level summarization.

`case_pass` is the per-case verdict. `summarize` rolls per-case Scores up into a
category x dimension table plus cost/latency/agreement aggregates, in a fixed
shape the CLI and CI consume. `ci_exit_code` turns the summary into a shell code.

v0.3 (additive): a `weighted` gate mode (weighted mean of applicable dims vs the
rubric threshold using config dimension weights), named + derived metrics in the
summary (`metrics`), an `assertion_score_mean`, and gate participation for any
derived metric carrying a `threshold`. The default `strict` gate is unchanged
and reproduces the prior pass/fail exactly.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from ..models import Case, Response, Rubric, Score
from .assertions import safe_eval


def case_pass(
    score: Score,
    rubric: Rubric,
    *,
    gate_mode: str = "strict",
    dimension_weights: dict[str, float] | None = None,
) -> bool:
    """Per-case verdict.

    `strict` (default, unchanged): assertions not False AND every non-None
    dimension >= threshold. `weighted`: assertions not False AND the
    weight-weighted mean of non-None dimensions >= threshold.
    """
    if score.assertions_passed is False:
        return False

    if gate_mode == "weighted":
        weights = dimension_weights or {}
        num = 0.0
        den = 0.0
        for name, value in score.dimensions.items():
            if value is None:
                continue
            w = float(weights.get(name, 1.0))
            num += w * float(value)
            den += w
        if den == 0.0:
            return True
        return (num / den) >= rubric.threshold

    # strict
    for value in score.dimensions.values():
        if value is None:
            continue
        if value < rubric.threshold:
            return False
    return True


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def _aggregate(vals: list[float], how: str) -> float | None:
    if not vals:
        return None
    if how == "min":
        return float(min(vals))
    if how == "max":
        return float(max(vals))
    if how == "p50":
        return _percentile(sorted(vals), 50)
    if how == "p95":
        return _percentile(sorted(vals), 95)
    if how == "rate":
        # fraction of values that are "truthy" (>= 0.5 on a [0,1] scale).
        return float(sum(1 for v in vals if v >= 0.5) / len(vals))
    return float(mean(vals))  # default: mean


def summarize(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    rubric: Rubric,
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    """Roll Scores up into the canonical summary dict.

    Keeps every original key. Adds `metrics` (named + derived) and
    `assertion_score_mean`. `config` is read best-effort for metric specs,
    dimension weights, and gate mode; absent config preserves prior behavior.
    """
    dim_names = rubric.dimension_names()
    case_by_id = {c.id: c for c in cases}
    score_by_id = {s.case_id: s for s in scores}

    gate_mode = "strict"
    dim_weights: dict[str, float] = {}
    confidence = 0.95
    respect_ci = False
    min_sample_warn = 30
    if config is not None:
        analyze_cfg = getattr(config, "analyze", None)
        if analyze_cfg is not None:
            gate_mode = getattr(analyze_cfg, "gate_mode", "strict") or "strict"
            dim_weights = dict(getattr(analyze_cfg, "dimension_weights", {}) or {})
            confidence = float(getattr(analyze_cfg, "confidence", 0.95) or 0.95)
            respect_ci = bool(getattr(analyze_cfg, "respect_ci", False))
            min_sample_warn = int(getattr(analyze_cfg, "min_sample_warn", 30) or 30)

    # Group scores by category.
    cats: dict[str, list[Score]] = {}
    for s in scores:
        c = case_by_id.get(s.case_id)
        cat = c.category if c is not None else "default"
        cats.setdefault(cat, []).append(s)

    from .stats import bootstrap_ci, gate_band_decision

    category_scores: dict[str, dict[str, Any]] = {}
    categories_passing = 0
    # Additive confidence layer: per-(category,dimension) bootstrap CIs + a
    # band-aware verdict. Existing keys are untouched so prior consumers/tests
    # keep working; the CI data lives under new keys.
    conf_by_category: dict[str, dict[str, Any]] = {}
    band_by_category: dict[str, str] = {}
    sample_warnings: list[str] = []
    for cat, cat_scores in cats.items():
        entry: dict[str, Any] = {"count": len(cat_scores)}
        cat_dim_means: dict[str, float] = {}
        cat_dim_ci: dict[str, Any] = {}
        for dim in dim_names:
            vals = [
                s.dimensions.get(dim)
                for s in cat_scores
                if s.dimensions.get(dim) is not None
            ]
            if vals:
                m = float(mean(vals))
                entry[dim] = m
                cat_dim_means[dim] = m
                cat_dim_ci[dim] = bootstrap_ci(vals, confidence=confidence)
            else:
                entry[dim] = None
        if gate_mode == "weighted":
            num = sum(float(dim_weights.get(d, 1.0)) * v for d, v in cat_dim_means.items())
            den = sum(float(dim_weights.get(d, 1.0)) for d in cat_dim_means)
            cat_pass = (num / den) >= rubric.threshold if den > 0 else True
        else:
            cat_pass = all(m >= rubric.threshold for m in cat_dim_means.values())
        entry["pass"] = cat_pass
        category_scores[cat] = entry
        if cat_pass:
            categories_passing += 1

        # Band verdict for the category: fail only if some dimension's whole CI
        # is below threshold; inconclusive if any dimension's CI straddles it.
        verdicts = [
            gate_band_decision(ci.get("ci_lower"), ci.get("ci_upper"), rubric.threshold, direction="above")
            for ci in cat_dim_ci.values()
        ]
        if "fail" in verdicts:
            band_by_category[cat] = "fail"
        elif "inconclusive" in verdicts:
            band_by_category[cat] = "inconclusive"
        elif verdicts:
            band_by_category[cat] = "pass"
        else:
            band_by_category[cat] = "inconclusive"
        conf_by_category[cat] = {"dimensions": cat_dim_ci}
        if len(cat_scores) < min_sample_warn:
            sample_warnings.append(
                f"category '{cat}' graded on {len(cat_scores)} cases (< {min_sample_warn}); "
                "interpret its scores with caution"
            )

    categories_total = len(category_scores)
    overall_pass = categories_total > 0 and categories_passing == categories_total

    # Assertion pass rate over cases that declared assertions.
    asserted = [s for s in scores if s.assertions_passed is not None]
    if asserted:
        from .stats import proportion_ci
        _passed = sum(1 for s in asserted if s.assertions_passed)
        assertion_pass_rate = _passed / len(asserted)
        assertion_pass_rate_ci = proportion_ci(_passed, len(asserted), confidence)
    else:
        assertion_pass_rate = 1.0
        assertion_pass_rate_ci = {"value": 1.0, "ci_lower": 1.0, "ci_upper": 1.0,
                                  "n": 0, "method": "wilson", "confidence": confidence}

    # Assertion score (continuous, weighted) aggregate over scored cases.
    ascores = [s.assertion_score for s in scores if s.assertion_score is not None]
    assertion_score_mean = float(mean(ascores)) if ascores else 0.0

    # Cost.
    tokens_in = sum(r.tokens_in or 0 for r in responses)
    tokens_out = sum(r.tokens_out or 0 for r in responses)
    costs = [r.cost_usd for r in responses if r.cost_usd is not None]
    usd = float(sum(costs)) if costs else None

    # Latency.
    lats = sorted(float(r.latency_ms) for r in responses if r.latency_ms is not None)
    if lats:
        latency = {
            "p50_ms": _percentile(lats, 50),
            "p95_ms": _percentile(lats, 95),
            "mean_ms": float(mean(lats)),
        }
    else:
        latency = {"p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0}

    # Agreement (only meaningful for ensembles).
    agreements = [s.agreement for s in scores if s.agreement is not None]
    agreement_mean = float(mean(agreements)) if agreements else None

    # ─── Named + derived metrics ─────────────────────────────────────────
    metric_specs = list(getattr(config, "metrics", []) or []) if config is not None else []
    metrics = _build_metrics(metric_specs, scores, category_scores, rubric)

    # Any metric carrying a threshold participates in the gate.
    for spec in metric_specs:
        thr = getattr(spec, "threshold", None)
        if thr is None:
            continue
        mv = metrics.get(spec.name)
        if mv is None or mv < thr:
            overall_pass = False

    # touch score_by_id so it is part of the contract surface
    _ = score_by_id

    # Band-aware overall verdict. "fail" if any category's CI is wholly below
    # threshold; "inconclusive" if any straddles it; else "pass".
    band_vals = list(band_by_category.values())
    if "fail" in band_vals:
        overall_band = "fail"
    elif "inconclusive" in band_vals:
        overall_band = "inconclusive"
    elif band_vals:
        overall_band = "pass"
    else:
        overall_band = "inconclusive"

    # `respect_ci`: don't fail CI on a difference that sits inside the noise band.
    # The build only goes red when the evidence is strong enough (a wholly-below
    # CI), preserving the strict point gate when respect_ci is off (the default).
    if respect_ci:
        overall_pass = overall_band != "fail"

    return {
        "threshold": float(rubric.threshold),
        "dimensions": list(dim_names),
        "category_scores": category_scores,
        "overall_pass": overall_pass,
        "categories_passing": categories_passing,
        "categories_total": categories_total,
        "assertion_pass_rate": float(assertion_pass_rate),
        "assertion_score_mean": assertion_score_mean,
        "metrics": metrics,
        "cost": {"tokens_in": int(tokens_in), "tokens_out": int(tokens_out), "usd": usd},
        "latency": latency,
        "agreement_mean": agreement_mean,
        # ── statistical-rigor layer (additive) ──────────────────────────────
        "confidence": {
            "level": confidence,
            "respect_ci": respect_ci,
            "assertion_pass_rate": assertion_pass_rate_ci,
            "by_category": conf_by_category,
            "warnings": sample_warnings,
        },
        "gate_band": {
            "overall": overall_band,
            "by_category": band_by_category,
        },
    }


def _build_metrics(
    metric_specs: list[Any],
    scores: list[Score],
    category_scores: dict[str, dict[str, Any]],
    rubric: Rubric,
) -> dict[str, float | None]:
    """Aggregate plain named metrics from per-case Score.metrics, then evaluate
    derived (formula) metrics over the resolved metric + dimension-mean table."""
    # Plain named metrics: aggregate per-case values across the run.
    per_metric: dict[str, list[float]] = {}
    for s in scores:
        for name, val in (s.metrics or {}).items():
            if val is not None:
                per_metric.setdefault(name, []).append(float(val))

    out: dict[str, float | None] = {}
    # Resolved name table for formula evaluation = run-mean dimension values +
    # any plain metrics, so a formula like "2*p*r/(p+r)" can reference them.
    names: dict[str, Any] = {}
    for dim in rubric.dimension_names():
        vals = [
            e.get(dim)
            for e in category_scores.values()
            if e.get(dim) is not None
        ]
        if vals:
            names[dim] = float(mean(vals))

    # First pass: plain (no-formula) metrics.
    plain_specs = [m for m in metric_specs if not getattr(m, "formula", None)]
    for spec in plain_specs:
        nm = spec.name
        agg = getattr(spec, "aggregate", "mean") or "mean"
        out[nm] = _aggregate(per_metric.get(nm, []), agg)
        if out[nm] is not None:
            names[nm] = out[nm]

    # Any metric tags present in scores but not declared as specs are still
    # surfaced (mean), so derived formulas can reference them.
    for nm, vals in per_metric.items():
        if nm not in out:
            out[nm] = _aggregate(vals, "mean")
            if out[nm] is not None:
                names[nm] = out[nm]

    # Second pass: derived (formula) metrics, with a couple of rounds so a
    # formula may reference an earlier-defined derived metric.
    derived = [m for m in metric_specs if getattr(m, "formula", None)]
    for _ in range(max(1, len(derived))):
        progressed = False
        for spec in derived:
            if spec.name in out and out[spec.name] is not None:
                continue
            try:
                val = safe_eval(str(spec.formula), dict(names))
                out[spec.name] = float(val)
                names[spec.name] = out[spec.name]
                progressed = True
            except Exception:  # noqa: BLE001 - unresolved/invalid formula -> None
                out.setdefault(spec.name, None)
        if not progressed:
            break

    return out


def ci_exit_code(summary: dict[str, Any]) -> int:
    """0 if the run passes the gate, else 1."""
    if not summary.get("overall_pass"):
        return 1
    return 0
