"""Pass/fail gating and run-level summarization.

`case_pass` is the per-case verdict. `summarize` rolls per-case Scores up into a
category x dimension table plus cost/latency/agreement aggregates, in a fixed
shape the CLI and CI consume. `ci_exit_code` turns the summary into a shell code.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from ..models import Case, Response, Rubric, Score


def case_pass(score: Score, rubric: Rubric) -> bool:
    """True iff every non-None dimension >= threshold AND assertions not False."""
    if score.assertions_passed is False:
        return False
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


def summarize(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    rubric: Rubric,
) -> dict[str, Any]:
    """Roll Scores up into the canonical summary dict."""
    dim_names = rubric.dimension_names()
    case_by_id = {c.id: c for c in cases}
    score_by_id = {s.case_id: s for s in scores}

    # Group scores by category.
    cats: dict[str, list[Score]] = {}
    for s in scores:
        c = case_by_id.get(s.case_id)
        cat = c.category if c is not None else "default"
        cats.setdefault(cat, []).append(s)

    category_scores: dict[str, dict[str, Any]] = {}
    categories_passing = 0
    for cat, cat_scores in cats.items():
        entry: dict[str, Any] = {"count": len(cat_scores)}
        cat_pass = True
        for dim in dim_names:
            vals = [
                s.dimensions.get(dim)
                for s in cat_scores
                if s.dimensions.get(dim) is not None
            ]
            if vals:
                m = float(mean(vals))
                entry[dim] = m
                if m < rubric.threshold:
                    cat_pass = False
            else:
                entry[dim] = None
        entry["pass"] = cat_pass
        category_scores[cat] = entry
        if cat_pass:
            categories_passing += 1

    categories_total = len(category_scores)
    overall_pass = categories_total > 0 and categories_passing == categories_total

    # Assertion pass rate over cases that declared assertions.
    asserted = [
        s for s in scores if s.assertions_passed is not None
    ]
    if asserted:
        assertion_pass_rate = sum(
            1 for s in asserted if s.assertions_passed
        ) / len(asserted)
    else:
        assertion_pass_rate = 1.0

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

    # touch score_by_id so it is part of the contract surface
    _ = score_by_id

    return {
        "threshold": float(rubric.threshold),
        "dimensions": list(dim_names),
        "category_scores": category_scores,
        "overall_pass": overall_pass,
        "categories_passing": categories_passing,
        "categories_total": categories_total,
        "assertion_pass_rate": float(assertion_pass_rate),
        "cost": {"tokens_in": int(tokens_in), "tokens_out": int(tokens_out), "usd": usd},
        "latency": latency,
        "agreement_mean": agreement_mean,
    }


def ci_exit_code(summary: dict[str, Any]) -> int:
    """0 if the run passes the gate, else 1."""
    return 0 if summary.get("overall_pass") else 1
