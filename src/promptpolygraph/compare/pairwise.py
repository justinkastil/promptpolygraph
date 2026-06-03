"""Deterministic pairwise A/B comparison between two scored runs.

The comparison is intentionally simple and fully deterministic: for each case we
reduce its `Score` to the arithmetic mean of its non-None dimension values, then
declare a per-case winner (or tie, within `epsilon`). Wins are aggregated overall
and per category. The function tolerates a case appearing in only one side (or
neither) by treating a missing/empty score as "no signal" on that side.
"""

from __future__ import annotations

from typing import Optional

from ..models import Case, Score


def _case_mean(score: Optional[Score]) -> Optional[float]:
    """Mean of the non-None dimension values for one case, or None."""
    if score is None:
        return None
    vals = [v for v in score.dimensions.values() if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _winner(
    a_mean: Optional[float],
    b_mean: Optional[float],
    epsilon: float,
) -> str:
    """Return 'a', 'b', or 'tie' for one case."""
    if a_mean is None and b_mean is None:
        return "tie"
    if a_mean is None:
        return "b"
    if b_mean is None:
        return "a"
    if abs(a_mean - b_mean) <= epsilon:
        return "tie"
    return "a" if a_mean > b_mean else "b"


def pairwise(
    cases: list[Case],
    scores_a: list[Score],
    scores_b: list[Score],
    *,
    epsilon: float = 0.25,
    run_a: str = "a",
    run_b: str = "b",
) -> dict:
    """Deterministic per-case A/B comparison.

    For each case, the winner is the side with the higher mean of non-None
    dimension scores; differences within `epsilon` are ties. Aggregates the
    record overall and per category, and returns one row per case.

    Robust to a case being absent from either score list.
    """
    a_by_id = {s.case_id: s for s in scores_a}
    b_by_id = {s.case_id: s for s in scores_b}

    wins_a = 0
    wins_b = 0
    ties = 0
    by_category: dict[str, dict[str, int]] = {}
    case_rows: list[dict] = []

    for case in cases:
        a_mean = _case_mean(a_by_id.get(case.id))
        b_mean = _case_mean(b_by_id.get(case.id))
        win = _winner(a_mean, b_mean, epsilon)

        if win == "a":
            wins_a += 1
        elif win == "b":
            wins_b += 1
        else:
            ties += 1

        cat = case.category or "default"
        bucket = by_category.setdefault(cat, {"a": 0, "b": 0, "tie": 0})
        bucket[win] += 1

        case_rows.append(
            {
                "case_id": case.id,
                "winner": win,
                "a_mean": a_mean,
                "b_mean": b_mean,
            }
        )

    return {
        "run_a": run_a,
        "run_b": run_b,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "by_category": by_category,
        "cases": case_rows,
    }
