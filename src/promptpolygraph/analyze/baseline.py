"""Run-over-run baseline diffing.

Compares a current summary against a stored baseline summary, per category and
per dimension, and flags regressions/improvements past a small dead-band so that
noise does not trip CI.
"""

from __future__ import annotations

from statistics import median
from typing import Any

# Movement smaller than this (in score points) is treated as noise.
DELTA_BAND = 0.5
_DELTA_BAND = DELTA_BAND  # backward-compatible internal alias


def _ci_for(summary: dict[str, Any], cat: str, dim: str) -> dict[str, Any] | None:
    """Pull the per-(category,dimension) CI dict from a summary's confidence
    block, or None when the summary predates the statistical layer."""
    try:
        return summary["confidence"]["by_category"][cat]["dimensions"][dim]
    except (KeyError, TypeError):
        return None


def _se_from_ci(ci: dict[str, Any] | None, confidence: float) -> float | None:
    """Recover a standard error from a (near-)symmetric CI: SE ≈ half-width / z."""
    if not ci or ci.get("ci_lower") is None or ci.get("ci_upper") is None:
        return None
    from .stats import z_for_confidence
    z = z_for_confidence(confidence)
    if z <= 0:
        return None
    return (float(ci["ci_upper"]) - float(ci["ci_lower"])) / (2.0 * z)


def diff_baseline(
    summary: dict[str, Any],
    baseline: dict[str, Any],
    *,
    alpha: float = 0.05,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Per-category, per-dimension deltas vs a baseline summary.

    Reports both a heuristic verdict (movement past `DELTA_BAND`) and, when both
    summaries carry the confidence layer, a *statistical* verdict: a two-sample
    z-test on each delta (SE recovered from the reported CIs) with a
    Benjamini-Hochberg correction across every dimension tested, so a multi-
    dimension sweep does not manufacture false regressions. `significant_*`
    lists hold only BH-significant moves; the heuristic lists are unchanged for
    backward compatibility.
    """
    from .stats import benjamini_hochberg, norm_cdf

    cur_cats = summary.get("category_scores", {}) or {}
    base_cats = baseline.get("category_scores", {}) or {}
    dimensions = summary.get("dimensions") or baseline.get("dimensions") or []

    by_category: dict[str, dict[str, dict[str, float]]] = {}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []  # (cat,dim) deltas eligible for a significance test

    for cat in sorted(set(cur_cats) | set(base_cats)):
        cur_entry = cur_cats.get(cat, {}) or {}
        base_entry = base_cats.get(cat, {}) or {}
        dim_table: dict[str, dict[str, float]] = {}
        for dim in dimensions:
            cur_v = cur_entry.get(dim)
            base_v = base_entry.get(dim)
            if cur_v is None or base_v is None:
                continue
            cur_f = float(cur_v)
            base_f = float(base_v)
            delta = cur_f - base_f
            cell: dict[str, Any] = {"current": cur_f, "baseline": base_f, "delta": delta}

            # Statistical test from the reported CIs, when available on both sides.
            se_cur = _se_from_ci(_ci_for(summary, cat, dim), confidence)
            se_base = _se_from_ci(_ci_for(baseline, cat, dim), confidence)
            if se_cur is not None and se_base is not None:
                se = (se_cur ** 2 + se_base ** 2) ** 0.5
                if se > 0:
                    z = delta / se
                    p = 2 * (1 - norm_cdf(abs(z)))
                else:
                    z, p = 0.0, 1.0
                cell["z"] = round(z, 6)
                cell["p_value"] = round(p, 6)
                cell["se"] = round(se, 6)
                tests.append({"category": cat, "dimension": dim, "delta": delta,
                              "current": cur_f, "baseline": base_f, "p_value": p})

            dim_table[dim] = cell
            if delta < -_DELTA_BAND:
                regressions.append(
                    {"category": cat, "dimension": dim, "delta": delta,
                     "current": cur_f, "baseline": base_f}
                )
            elif delta > _DELTA_BAND:
                improvements.append(
                    {"category": cat, "dimension": dim, "delta": delta,
                     "current": cur_f, "baseline": base_f}
                )
        if dim_table:
            by_category[cat] = dim_table

    # Multiple-comparison correction across all eligible deltas.
    significant_regressions: list[dict[str, Any]] = []
    significant_improvements: list[dict[str, Any]] = []
    significance = {"method": "two-sample z from CI + Benjamini-Hochberg",
                    "alpha": alpha, "n_tests": len(tests), "available": bool(tests)}
    if tests:
        bh = benjamini_hochberg([t["p_value"] for t in tests], alpha=alpha)
        for t, q, rej in zip(tests, bh["qvalues"], bh["rejected"]):
            t["q_value"] = q
            t["significant"] = bool(rej)
            if rej and t["delta"] < 0:
                significant_regressions.append(t)
            elif rej and t["delta"] > 0:
                significant_improvements.append(t)
        significance["n_significant"] = bh["n_significant"]
        significance["tests"] = tests

    return {
        "by_category": by_category,
        "regressions": regressions,
        "improvements": improvements,
        "significant_regressions": significant_regressions,
        "significant_improvements": significant_improvements,
        "significance": significance,
    }


def rolling_baseline_summary(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a window of run summaries into one baseline summary.

    For each category/dimension the baseline value is the median of that
    dimension's per-run means across the window (None values ignored). The
    result is summary-shaped — `category_scores[cat][dim]` and `dimensions` —
    so it can be passed straight into `diff_baseline(current, rolling)` to flag
    rolling-window regressions. An empty window yields an empty baseline.
    """
    dimensions: list[str] = []
    for summ in summaries:
        for d in summ.get("dimensions") or []:
            if d not in dimensions:
                dimensions.append(d)

    # Collect every category seen, preserving a stable sorted order.
    cats: set[str] = set()
    for summ in summaries:
        cats |= set((summ.get("category_scores") or {}).keys())

    category_scores: dict[str, dict[str, Any]] = {}
    for cat in sorted(cats):
        entry: dict[str, Any] = {}
        counts: list[int] = []
        for dim in dimensions:
            vals: list[float] = []
            for summ in summaries:
                cat_entry = (summ.get("category_scores") or {}).get(cat) or {}
                v = cat_entry.get(dim)
                if v is not None:
                    vals.append(float(v))
            entry[dim] = float(median(vals)) if vals else None
        for summ in summaries:
            cat_entry = (summ.get("category_scores") or {}).get(cat) or {}
            if cat_entry.get("count") is not None:
                counts.append(int(cat_entry["count"]))
        entry["count"] = max(counts) if counts else 0
        category_scores[cat] = entry

    return {
        "dimensions": dimensions,
        "category_scores": category_scores,
        "window": len(summaries),
    }
