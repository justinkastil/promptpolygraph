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


def diff_baseline(summary: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Per-category, per-dimension deltas vs a baseline summary."""
    cur_cats = summary.get("category_scores", {}) or {}
    base_cats = baseline.get("category_scores", {}) or {}
    dimensions = summary.get("dimensions") or baseline.get("dimensions") or []

    by_category: dict[str, dict[str, dict[str, float]]] = {}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []

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
            dim_table[dim] = {
                "current": cur_f,
                "baseline": base_f,
                "delta": delta,
            }
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

    return {
        "by_category": by_category,
        "regressions": regressions,
        "improvements": improvements,
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
