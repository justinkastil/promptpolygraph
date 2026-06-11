"""N-run comparison matrix: comparability, category/dimension trends, per-case
movement, and regression/improvement classification across many scored runs.

Where `pairwise` answers "which of two runs won, case by case", this module
answers the historical question: given a chronological sequence of runs of the
same dataset, how did each category/dimension move, which individual cases
regressed or improved, and (vs a chosen baseline) what crossed the dead-band?

Everything here is deterministic and JSON-serializable. Run summaries are read
from each run's `summary.json` on disk (written by the pipeline); when a summary
file is missing the summary is recomputed from the store via `analyze.summarize`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..analyze.baseline import DELTA_BAND
from ..models import RunMeta
from .pairwise import pairwise

# A regression past this many points (beyond the dead-band) is a hard fail
# rather than a warning.
_FAIL_BAND = 1.0


# ─── comparability ──────────────────────────────────────────────────────────


def comparability(meta_a: RunMeta, meta_b: RunMeta) -> str:
    """How comparable two runs are.

    'identical'     same corpus AND same rubric (scores directly comparable)
    'same_dataset'  same corpus, different rubric (prompts match, grading differs)
    'disjoint'      different corpus (not meaningfully comparable)
    """
    same_corpus = (
        meta_a.corpus_fingerprint is not None
        and meta_a.corpus_fingerprint == meta_b.corpus_fingerprint
    )
    if not same_corpus:
        return "disjoint"
    same_rubric = (
        meta_a.rubric_fingerprint is not None
        and meta_a.rubric_fingerprint == meta_b.rubric_fingerprint
    )
    return "identical" if same_rubric else "same_dataset"


def _group_comparability(metas: list[RunMeta]) -> str:
    """Weakest pairwise comparability across the whole group (vs the first)."""
    if len(metas) < 2:
        return "identical"
    levels = {"identical": 2, "same_dataset": 1, "disjoint": 0}
    worst = "identical"
    base = metas[0]
    for other in metas[1:]:
        c = comparability(base, other)
        if levels[c] < levels[worst]:
            worst = c
    return worst


# ─── summary loading ─────────────────────────────────────────────────────────


def _load_summary(store, run_id: str, out_dir: str | Path) -> dict[str, Any]:
    """Read a run's summary.json; recompute via analyze.summarize if absent."""
    path = Path(out_dir).expanduser() / run_id / "summary.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            pass
    # Fallback: recompute. Needs cases/responses/scores + a rubric.
    from ..analyze import default_rubric, summarize

    cases = store.get_cases(run_id)
    responses = store.get_responses(run_id)
    scores = store.get_scores(run_id)
    return summarize(cases, responses, scores, default_rubric())


def _cat_dim_mean(summary: dict[str, Any], cat: str, dim: str) -> Optional[float]:
    entry = (summary.get("category_scores") or {}).get(cat) or {}
    v = entry.get(dim)
    return float(v) if v is not None else None


# ─── least-squares slope ──────────────────────────────────────────────────────


def _slope(series: list[tuple[Any, Optional[float]]]) -> Optional[float]:
    """Least-squares slope of the (index, value) points, ignoring None values.

    The x-axis is the chronological run index (0, 1, 2, ...) so the slope is in
    score-points-per-run. Returns None when fewer than two real points exist.
    """
    pts = [(i, v) for i, (_, v) in enumerate(series) if v is not None]
    n = len(pts)
    if n < 2:
        return None
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom


# ─── category trends ──────────────────────────────────────────────────────────


def build_category_trends(
    summaries: list[tuple[str, dict[str, Any]]],
    dimensions: list[str],
) -> list[dict[str, Any]]:
    """Per-category, per-dimension series + slope + latest-delta across runs.

    `summaries` is an ordered list of (run_id, summary) in chronological order.
    """
    # Union of categories, stable sorted.
    cats: list[str] = []
    for _, summ in summaries:
        for cat in (summ.get("category_scores") or {}):
            if cat not in cats:
                cats.append(cat)
    cats.sort()

    trends: list[dict[str, Any]] = []
    for cat in cats:
        dim_blocks: list[dict[str, Any]] = []
        for dim in dimensions:
            series = [(rid, _cat_dim_mean(summ, cat, dim)) for rid, summ in summaries]
            real = [v for _, v in series if v is not None]
            latest_delta = None
            if len(real) >= 2:
                latest_delta = real[-1] - real[-2]
            dim_blocks.append(
                {
                    "dimension": dim,
                    "series": [[rid, v] for rid, v in series],
                    "slope": _slope(series),
                    "latest_delta": latest_delta,
                }
            )
        pass_series = []
        for rid, summ in summaries:
            entry = (summ.get("category_scores") or {}).get(cat) or {}
            pass_series.append([rid, bool(entry.get("pass")) if "pass" in entry else None])
        trends.append(
            {
                "category": cat,
                "dimensions": dim_blocks,
                "pass_series": pass_series,
            }
        )
    return trends


# ─── per-case movement ─────────────────────────────────────────────────────────


def _case_mean_from_score(score) -> Optional[float]:
    """Mean of non-None dimension values for one Score (mirrors pairwise)."""
    if score is None:
        return None
    vals = [v for v in score.dimensions.values() if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_case_movements(
    store,
    run_ids: list[str],
) -> list[dict[str, Any]]:
    """Per-case mean score across runs + first→last movement classification.

    `moved` is one of: 'up'/'down' (delta beyond the dead-band), 'flat' (within
    band), 'new' (only present in the latest run), 'dropped' (absent from the
    latest run but present earlier).
    """
    # Build per-run case-id -> mean, and a canonical case-id -> category map.
    per_run_means: dict[str, dict[str, Optional[float]]] = {}
    category_of: dict[str, str] = {}
    seen_order: list[str] = []

    for rid in run_ids:
        scores = {s.case_id: s for s in store.get_scores(rid)}
        cases = store.get_cases(rid)
        means: dict[str, Optional[float]] = {}
        for c in cases:
            if c.id not in category_of:
                category_of[c.id] = c.category or "default"
            if c.id not in seen_order:
                seen_order.append(c.id)
            means[c.id] = _case_mean_from_score(scores.get(c.id))
        per_run_means[rid] = means

    last_run = run_ids[-1] if run_ids else None
    movements: list[dict[str, Any]] = []
    for cid in seen_order:
        means = {rid: per_run_means[rid].get(cid) for rid in run_ids}
        present = [(rid, means[rid]) for rid in run_ids if means[rid] is not None]
        in_last = last_run is not None and means.get(last_run) is not None
        in_first_seen = present and present[0][0] != last_run

        delta_first_last: Optional[float] = None
        moved: str
        if not present:
            moved = "dropped"
        elif len(present) == 1:
            # Only graded in a single run.
            moved = "new" if (in_last and not in_first_seen) else "flat"
        else:
            first_v = present[0][1]
            last_v = present[-1][1]
            delta_first_last = last_v - first_v
            if not in_last:
                moved = "dropped"
            elif delta_first_last > DELTA_BAND:
                moved = "up"
            elif delta_first_last < -DELTA_BAND:
                moved = "down"
            else:
                moved = "flat"

        movements.append(
            {
                "case_id": cid,
                "category": category_of.get(cid, "default"),
                "means": means,
                "delta_first_last": delta_first_last,
                "moved": moved,
            }
        )
    return movements


# ─── regression / improvement classification ──────────────────────────────────


def _classify_deltas(
    current: dict[str, Any],
    baseline: dict[str, Any],
    dimensions: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-category/dimension regressions + improvements vs a baseline summary."""
    cur_cats = current.get("category_scores") or {}
    base_cats = baseline.get("category_scores") or {}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    for cat in sorted(set(cur_cats) | set(base_cats)):
        for dim in dimensions:
            cur_v = _cat_dim_mean(current, cat, dim)
            base_v = _cat_dim_mean(baseline, cat, dim)
            if cur_v is None or base_v is None:
                continue
            delta = cur_v - base_v
            if delta < -DELTA_BAND:
                regressions.append(
                    {
                        "category": cat,
                        "dimension": dim,
                        "delta": delta,
                        "current": cur_v,
                        "baseline": base_v,
                        "severity": "fail" if delta <= -_FAIL_BAND else "warn",
                    }
                )
            elif delta > DELTA_BAND:
                improvements.append(
                    {
                        "category": cat,
                        "dimension": dim,
                        "delta": delta,
                        "current": cur_v,
                        "baseline": base_v,
                        "severity": "fail" if delta >= _FAIL_BAND else "warn",
                    }
                )
    return regressions, improvements


# ─── top-level entry point ─────────────────────────────────────────────────────


def compare_runs(
    store,
    run_ids: list[str],
    out_dir: str | Path,
    *,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable ComparisonReport across N runs.

    Runs are ordered chronologically (by their stored `created_at`). The
    baseline defaults to the earliest run; deltas/regressions are computed for
    the latest run against that baseline. For exactly two runs the `overall`
    block also carries the deterministic pairwise win/loss/tie record.
    """
    metas: list[RunMeta] = []
    for rid in run_ids:
        m = store.get_run(rid)
        if m is None:
            raise ValueError(f"unknown run id: {rid}")
        metas.append(m)

    # Chronological order.
    order = sorted(range(len(metas)), key=lambda i: metas[i].created_at or "")
    metas = [metas[i] for i in order]
    ordered_ids = [m.run_id for m in metas]

    comp = _group_comparability(metas)
    project = metas[0].project if metas else "default"

    summaries = [(m.run_id, _load_summary(store, m.run_id, out_dir)) for m in metas]
    summ_by_id = {rid: s for rid, s in summaries}

    # Union of dimensions across all summaries (stable).
    dimensions: list[str] = []
    for _, summ in summaries:
        for d in summ.get("dimensions") or []:
            if d not in dimensions:
                dimensions.append(d)

    category_trends = build_category_trends(summaries, dimensions)
    case_movements = build_case_movements(store, ordered_ids)

    baseline_id = baseline_run_id or (ordered_ids[0] if ordered_ids else None)
    latest_id = ordered_ids[-1] if ordered_ids else None

    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    if (
        baseline_id is not None
        and latest_id is not None
        and baseline_id != latest_id
        and comp == "identical"
    ):
        regressions, improvements = _classify_deltas(
            summ_by_id.get(latest_id, {}),
            summ_by_id.get(baseline_id, {}),
            dimensions,
        )

    overall = _build_overall(store, metas, summ_by_id, ordered_ids)

    return {
        "project": project,
        "run_ids": ordered_ids,
        "comparability": comp,
        "baseline_run_id": baseline_id,
        "category_trends": category_trends,
        "case_movements": case_movements,
        "regressions": regressions,
        "improvements": improvements,
        "overall": overall,
    }


def _build_overall(
    store,
    metas: list[RunMeta],
    summ_by_id: dict[str, dict[str, Any]],
    ordered_ids: list[str],
) -> dict[str, Any]:
    """Per-run pass counts; for exactly two runs, add pairwise win/loss/tie."""
    per_run = []
    for rid in ordered_ids:
        summ = summ_by_id.get(rid, {})
        per_run.append(
            {
                "run_id": rid,
                "overall_pass": summ.get("overall_pass"),
                "categories_passing": summ.get("categories_passing"),
                "categories_total": summ.get("categories_total"),
            }
        )
    overall: dict[str, Any] = {"per_run": per_run}

    if len(ordered_ids) == 2:
        run_a, run_b = ordered_ids[0], ordered_ids[1]
        cases = store.get_cases(run_a) or store.get_cases(run_b)
        pw = pairwise(
            cases,
            store.get_scores(run_a),
            store.get_scores(run_b),
            run_a=run_a,
            run_b=run_b,
        )
        overall["wins_a"] = pw["wins_a"]
        overall["wins_b"] = pw["wins_b"]
        overall["ties"] = pw["ties"]
        overall["by_category"] = pw["by_category"]
    return overall
