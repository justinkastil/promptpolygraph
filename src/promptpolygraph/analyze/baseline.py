"""Run-over-run baseline diffing.

Compares a current summary against a stored baseline summary, per category and
per dimension, and flags regressions/improvements past a small dead-band so that
noise does not trip CI.
"""

from __future__ import annotations

from typing import Any

# Movement smaller than this (in score points) is treated as noise.
_DELTA_BAND = 0.5


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
