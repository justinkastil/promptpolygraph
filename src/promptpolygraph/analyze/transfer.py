"""Synthetic-to-real transfer validation.

Measures how well the synthetic scores from a stored run predict real-world
outcomes the user observed in production. Given the run's per-case rubric scores
and a user file of real labels/scores (JSON or CSV, keyed by case_id or by
category), it reports rank and linear correlation per category and overall, plus
a distribution-shift statistic, flags categories where synthetic does not track
real, and degrades gracefully when the real data is sparse or absent.

Correlation answers "does a higher synthetic score predict a better real
outcome"; the shift statistic answers "do the two score distributions even live
in the same place" — a high correlation with a large shift still means the
synthetic harness is mis-calibrated against reality.

Pure-Python and deterministic; reuses the helpers in `stats.py`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean as _mean
from typing import Any, Sequence

from . import stats
from ..models import Case, Score

# Below this absolute rank correlation, synthetic does not reliably track real
# outcomes for the category and the verdict should not be trusted as-is.
_LOW_CORR = 0.3
# Categories with fewer paired observations than this carry wide uncertainty;
# their correlation is reported but not used to flag a transfer problem.
_MIN_PAIRS = 5


def case_synthetic_score(score: Score | None) -> float | None:
    """Per-case synthetic scalar: mean of the applicable rubric dimensions.

    Matches the aggregation the report sample and category roll-ups use, so the
    transfer correlation is computed against the same number a reviewer sees.
    Returns None when nothing was graded.
    """
    if score is None:
        return None
    vals = [v for v in score.dimensions.values() if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def load_real_outcomes(path: str | Path) -> dict[str, Any]:
    """Load a user file of real outcomes from JSON or CSV.

    Two keying modes are accepted, distinguished by which column/field is present:

    - per-case: rows keyed by ``case_id`` with a numeric ``score`` (or ``label``,
      coerced: true/false/pass/fail -> 1/0). Paired with synthetic per case.
    - per-category: rows keyed by ``category`` with a numeric ``score``. Used only
      for an aggregate cross-check when no per-case data is available.

    JSON may be a list of row objects or a mapping of id/category -> value/object.
    Returns ``{"by_case": {...}, "by_category": {...}}`` with float values.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.suffix.lower() == ".csv":
        rows = _read_csv(p)
    else:
        rows = _read_json(p)
    by_case: dict[str, float] = {}
    by_category: dict[str, list[float]] = {}
    for row in rows:
        val = _coerce_outcome(row)
        if val is None:
            continue
        cid = row.get("case_id") or row.get("id")
        cat = row.get("category")
        if cid:
            by_case[str(cid)] = val
        elif cat:
            by_category.setdefault(str(cat), []).append(val)
    return {"by_case": by_case, "by_category": by_category}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _read_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # mapping of key -> scalar or object; normalize to row dicts.
        rows: list[dict[str, Any]] = []
        for key, val in data.items():
            if isinstance(val, dict):
                row = dict(val)
                row.setdefault("case_id", key)
            else:
                row = {"case_id": key, "score": val}
            rows.append(row)
        return rows
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


_TRUE = {"1", "true", "yes", "pass", "passed", "good", "y", "t"}
_FALSE = {"0", "false", "no", "fail", "failed", "bad", "n", "f"}


def _coerce_outcome(row: dict[str, Any]) -> float | None:
    """Pull a numeric outcome from a row: ``score`` first, else a coerced ``label``."""
    if "score" in row and row["score"] not in (None, ""):
        try:
            return float(row["score"])
        except (TypeError, ValueError):
            pass
    label = row.get("label")
    if label is None or label == "":
        return None
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return float(label)
    s = str(label).strip().lower()
    if s in _TRUE:
        return 1.0
    if s in _FALSE:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def _correlation_block(syn: Sequence[float], real: Sequence[float]) -> dict:
    """Spearman + Pearson + KS/JS shift for one set of paired observations."""
    n = len(syn)
    block: dict[str, Any] = {
        "n": n,
        "spearman": stats.spearman(syn, real),
        "pearson": stats.pearson(syn, real),
        "ks": stats.ks_two_sample(syn, real),
        "js_divergence": stats.js_divergence(syn, real),
    }
    return block


def transfer_report(
    cases: Sequence[Case],
    scores: Sequence[Score],
    real: dict[str, Any],
    *,
    low_corr: float = _LOW_CORR,
    min_pairs: int = _MIN_PAIRS,
) -> dict:
    """Correlate synthetic per-case scores with real outcomes and report transfer.

    `real` is the output of `load_real_outcomes`. Pairs are formed on shared
    case_ids; categories come from the run's cases. Per category and overall it
    reports Spearman, Pearson, and a distribution-shift stat (KS + JS). Categories
    with enough pairs but weak rank correlation are flagged, and a caveat is
    surfaced. When no per-case overlap exists it falls back to a per-category
    aggregate cross-check, and reports `status="insufficient"` if even that is
    unavailable.
    """
    by_case_score = {s.case_id: s for s in scores}
    cat_of = {c.id: c.category for c in cases}
    real_by_case: dict[str, float] = real.get("by_case", {})

    # Build paired (synthetic, real) observations per category.
    paired: dict[str, dict[str, list[float]]] = {}
    matched = 0
    for cid, real_val in real_by_case.items():
        syn_val = case_synthetic_score(by_case_score.get(cid))
        if syn_val is None or cid not in cat_of:
            continue
        cat = cat_of[cid]
        bucket = paired.setdefault(cat, {"syn": [], "real": []})
        bucket["syn"].append(syn_val)
        bucket["real"].append(real_val)
        matched += 1

    flags: list[str] = []
    caveats: list[str] = []

    if matched == 0:
        return _aggregate_fallback(cases, scores, real, flags, caveats)

    categories: dict[str, dict] = {}
    all_syn: list[float] = []
    all_real: list[float] = []
    for cat in sorted(paired):
        syn = paired[cat]["syn"]
        real_vals = paired[cat]["real"]
        all_syn.extend(syn)
        all_real.extend(real_vals)
        block = _correlation_block(syn, real_vals)
        sp = block["spearman"]
        block["sparse"] = block["n"] < min_pairs
        block["low_correlation"] = (
            sp is not None and not block["sparse"] and abs(sp) < low_corr
        )
        if block["low_correlation"]:
            flags.append(
                f"category '{cat}': rank correlation {sp:+.2f} (|r|<{low_corr:.2f}, "
                f"n={block['n']}) — synthetic scores do not track real outcomes here"
            )
        elif block["sparse"]:
            caveats.append(
                f"category '{cat}': only {block['n']} paired case(s) "
                f"(< {min_pairs}); correlation is low-confidence"
            )
        categories[cat] = block

    overall = _correlation_block(all_syn, all_real)
    overall["categories_flagged"] = sum(
        1 for b in categories.values() if b["low_correlation"]
    )

    if overall["categories_flagged"]:
        caveats.append(
            "synthetic-to-real transfer is weak in "
            f"{overall['categories_flagged']} categor"
            f"{'y' if overall['categories_flagged'] == 1 else 'ies'}; "
            "treat their synthetic verdicts as unvalidated against production"
        )
    if overall.get("spearman") is not None and abs(overall["spearman"]) < low_corr:
        caveats.append(
            f"overall rank correlation {overall['spearman']:+.2f} is weak — the "
            "synthetic harness may not predict real outcomes for this target"
        )

    return {
        "status": "ok",
        "matched_cases": matched,
        "real_cases": len(real_by_case),
        "coverage": round(matched / len(real_by_case), 6) if real_by_case else 0.0,
        "low_corr_threshold": low_corr,
        "min_pairs": min_pairs,
        "overall": overall,
        "categories": categories,
        "flags": flags,
        "caveats": caveats,
    }


def _aggregate_fallback(
    cases: Sequence[Case],
    scores: Sequence[Score],
    real: dict[str, Any],
    flags: list[str],
    caveats: list[str],
) -> dict:
    """Per-category aggregate cross-check when no per-case overlap exists.

    Correlates each category's mean synthetic score against the mean real outcome
    for that category. Needs at least two shared categories to compute anything.
    """
    real_by_cat: dict[str, list[float]] = real.get("by_category", {})
    by_case_score = {s.case_id: s for s in scores}
    syn_by_cat: dict[str, list[float]] = {}
    for c in cases:
        v = case_synthetic_score(by_case_score.get(c.id))
        if v is not None:
            syn_by_cat.setdefault(c.category, []).append(v)

    shared = sorted(set(syn_by_cat) & set(real_by_cat))
    if len(shared) < 2:
        caveats.append(
            "no per-case overlap and too few shared categories for an aggregate "
            "check — supply real outcomes keyed by case_id to validate transfer"
        )
        return {
            "status": "insufficient",
            "matched_cases": 0,
            "real_cases": len(real.get("by_case", {})),
            "shared_categories": shared,
            "overall": None,
            "categories": {},
            "flags": flags,
            "caveats": caveats,
        }

    syn_means = [_mean(syn_by_cat[c]) for c in shared]
    real_means = [_mean(real_by_cat[c]) for c in shared]
    caveats.append(
        "no per-case overlap — transfer measured on per-category means only "
        f"({len(shared)} categories); this is a coarse cross-check"
    )
    return {
        "status": "aggregate",
        "matched_cases": 0,
        "real_cases": len(real.get("by_case", {})),
        "shared_categories": shared,
        "overall": {
            "n": len(shared),
            "spearman": stats.spearman(syn_means, real_means),
            "pearson": stats.pearson(syn_means, real_means),
        },
        "categories": {},
        "flags": flags,
        "caveats": caveats,
    }


# ── report section ─────────────────────────────────────────────────────────

def _fmt(v: float | None, places: int = 2, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+.{places}f}" if signed else f"{v:.{places}f}"


def transfer_section(report: dict) -> list[str]:
    """Markdown lines for a run-report transfer section.

    Mirrors the `list[str]` convention of the other report-section builders.
    Returns an empty list when no report is supplied so callers can splice it in
    unconditionally.
    """
    if not report:
        return []
    out = ["## Synthetic-to-real transfer", ""]
    status = report.get("status")

    if status == "insufficient":
        out.append("_Not enough real-outcome overlap to validate transfer._")
        for c in report.get("caveats", []):
            out.append("")
            out.append(f"> {c}")
        out.append("")
        return out

    overall = report.get("overall") or {}
    if status == "aggregate":
        out.append(
            f"Per-category aggregate cross-check over "
            f"{len(report.get('shared_categories', []))} categories "
            "(no per-case overlap):"
        )
        out.append("")
        out.append(f"- Spearman: {_fmt(overall.get('spearman'), signed=True)}")
        out.append(f"- Pearson: {_fmt(overall.get('pearson'), signed=True)}")
    else:
        out.append(
            f"Paired {report.get('matched_cases', 0)} of "
            f"{report.get('real_cases', 0)} real cases "
            f"(coverage {_fmt(report.get('coverage'))})."
        )
        out.append("")
        out.append("| Category | n | Spearman | Pearson | KS | JS | Flag |")
        out.append("|---|---:|---:|---:|---:|---:|---|")
        cats = report.get("categories", {})
        for cat in sorted(cats):
            b = cats[cat]
            ks = (b.get("ks") or {}).get("statistic")
            flag = "low corr" if b.get("low_correlation") else ("sparse" if b.get("sparse") else "")
            out.append(
                f"| {cat} | {b.get('n', 0)} | {_fmt(b.get('spearman'), signed=True)} "
                f"| {_fmt(b.get('pearson'), signed=True)} | {_fmt(ks)} "
                f"| {_fmt(b.get('js_divergence'))} | {flag} |"
            )
        out.append(
            f"| **overall** | {overall.get('n', 0)} "
            f"| {_fmt(overall.get('spearman'), signed=True)} "
            f"| {_fmt(overall.get('pearson'), signed=True)} "
            f"| {_fmt((overall.get('ks') or {}).get('statistic'))} "
            f"| {_fmt(overall.get('js_divergence'))} | |"
        )

    for c in report.get("caveats", []):
        out.append("")
        out.append(f"> {c}")
    out.append("")
    return out
