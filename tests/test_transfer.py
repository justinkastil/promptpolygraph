"""Tests for synthetic-to-real transfer validation (analyze/transfer.py)."""

from __future__ import annotations

import json

import pytest

from promptpolygraph.analyze import stats, transfer
from promptpolygraph.models import Case, Score


# ── correlation primitives ───────────────────────────────────────────────────

def test_pearson_perfect_positive_and_negative():
    assert stats.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert stats.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_undefined_on_constant_or_short():
    assert stats.pearson([1, 1, 1], [1, 2, 3]) is None
    assert stats.pearson([1.0], [2.0]) is None


def test_spearman_monotonic_nonlinear_is_one():
    # Spearman captures monotonic-but-nonlinear where Pearson would not be 1.0.
    x = [1, 2, 3, 4, 5]
    y = [1, 4, 9, 16, 25]
    assert stats.spearman(x, y) == pytest.approx(1.0)
    assert stats.pearson(x, y) < 1.0


def test_spearman_handles_ties():
    # ties share the average rank; perfectly concordant after ranking.
    assert stats.spearman([1, 1, 2, 3], [5, 5, 6, 7]) == pytest.approx(1.0)


def test_spearman_no_correlation_near_zero():
    x = [1, 2, 3, 4, 5, 6]
    y = [3, 1, 4, 1, 5, 2]
    r = stats.spearman(x, y)
    assert r is not None and abs(r) < 0.6


def test_ks_identical_samples_zero():
    res = stats.ks_two_sample([1, 2, 3, 4], [1, 2, 3, 4])
    assert res["statistic"] == 0.0


def test_ks_disjoint_samples_one():
    res = stats.ks_two_sample([0, 0, 0], [9, 9, 9])
    assert res["statistic"] == pytest.approx(1.0)


def test_ks_empty_side():
    res = stats.ks_two_sample([], [1, 2])
    assert res["statistic"] is None


def test_js_divergence_identical_zero_and_bounds():
    assert stats.js_divergence([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)
    far = stats.js_divergence([0, 0, 0], [10, 10, 10], lo=0, hi=10)
    assert 0.0 <= far <= 1.0 and far == pytest.approx(1.0)


def test_js_divergence_empty_none():
    assert stats.js_divergence([], [1]) is None


# ── outcome loading ───────────────────────────────────────────────────────────

def _case(cid: str, cat: str) -> Case:
    return Case(id=cid, prompt="p", category=cat)


def _score(cid: str, val: int) -> Score:
    return Score(case_id=cid, dimensions={"quality": val, "safety": val})


def test_load_real_outcomes_csv_per_case(tmp_path):
    p = tmp_path / "real.csv"
    p.write_text("case_id,score\nc1,8\nc2,4\n", encoding="utf-8")
    real = transfer.load_real_outcomes(p)
    assert real["by_case"] == {"c1": 8.0, "c2": 4.0}


def test_load_real_outcomes_label_coercion(tmp_path):
    p = tmp_path / "real.csv"
    p.write_text("case_id,label\nc1,pass\nc2,fail\nc3,true\n", encoding="utf-8")
    real = transfer.load_real_outcomes(p)
    assert real["by_case"] == {"c1": 1.0, "c2": 0.0, "c3": 1.0}


def test_load_real_outcomes_json_mapping(tmp_path):
    p = tmp_path / "real.json"
    p.write_text(json.dumps({"c1": 7, "c2": {"score": 3}}), encoding="utf-8")
    real = transfer.load_real_outcomes(p)
    assert real["by_case"] == {"c1": 7.0, "c2": 3.0}


def test_load_real_outcomes_per_category(tmp_path):
    p = tmp_path / "real.json"
    p.write_text(json.dumps([{"category": "a", "score": 5},
                             {"category": "a", "score": 7}]), encoding="utf-8")
    real = transfer.load_real_outcomes(p)
    assert real["by_category"] == {"a": [5.0, 7.0]}


def test_load_real_outcomes_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        transfer.load_real_outcomes(tmp_path / "nope.csv")


# ── transfer report ───────────────────────────────────────────────────────────

def test_transfer_perfect_correlation_no_flags():
    cases = [_case(f"c{i}", "alpha") for i in range(6)]
    scores = [_score(f"c{i}", i + 2) for i in range(6)]  # synthetic = i+2
    real = {"by_case": {f"c{i}": (i + 2) * 10.0 for i in range(6)}, "by_category": {}}
    rep = transfer.transfer_report(cases, scores, real)
    assert rep["status"] == "ok"
    assert rep["matched_cases"] == 6
    assert rep["overall"]["spearman"] == pytest.approx(1.0)
    assert rep["categories"]["alpha"]["low_correlation"] is False
    assert rep["flags"] == []


def test_transfer_negative_correlation_flagged():
    cases = [_case(f"c{i}", "beta") for i in range(6)]
    scores = [_score(f"c{i}", i + 2) for i in range(6)]
    # real outcome moves opposite to synthetic: strong negative rank correlation.
    real = {"by_case": {f"c{i}": float(10 - i) for i in range(6)}, "by_category": {}}
    rep = transfer.transfer_report(cases, scores, real)
    # negative but |r| high -> not flagged as low, correlation is real (just inverse).
    assert rep["overall"]["spearman"] == pytest.approx(-1.0)
    assert rep["categories"]["beta"]["low_correlation"] is False


def test_transfer_low_correlation_flagged_and_caveat():
    cases = [_case(f"c{i}", "gamma") for i in range(6)]
    scores = [_score(f"c{i}", i + 2) for i in range(6)]
    # real outcome unrelated to synthetic score.
    real = {"by_case": {"c0": 5.0, "c1": 1.0, "c2": 6.0, "c3": 2.0,
                        "c4": 4.0, "c5": 3.0}, "by_category": {}}
    rep = transfer.transfer_report(cases, scores, real, low_corr=0.5)
    assert rep["categories"]["gamma"]["low_correlation"] is True
    assert any("gamma" in f for f in rep["flags"])
    assert rep["caveats"]


def test_transfer_sparse_category_not_flagged_but_caveated():
    cases = [_case(f"c{i}", "delta") for i in range(3)]
    scores = [_score(f"c{i}", i + 2) for i in range(3)]
    real = {"by_case": {"c0": 9.0, "c1": 1.0, "c2": 5.0}, "by_category": {}}
    rep = transfer.transfer_report(cases, scores, real, min_pairs=5)
    b = rep["categories"]["delta"]
    assert b["sparse"] is True
    assert b["low_correlation"] is False  # too few pairs to flag
    assert any("delta" in c for c in rep["caveats"])


def test_transfer_empty_real_is_insufficient():
    cases = [_case("c0", "alpha")]
    scores = [_score("c0", 5)]
    rep = transfer.transfer_report(cases, scores, {"by_case": {}, "by_category": {}})
    assert rep["status"] == "insufficient"
    assert rep["overall"] is None
    assert rep["caveats"]


def test_transfer_aggregate_fallback_when_no_case_overlap():
    cases = [_case("a1", "a"), _case("a2", "a"), _case("b1", "b"), _case("b2", "b")]
    scores = [_score("a1", 8), _score("a2", 8), _score("b1", 2), _score("b2", 2)]
    # real keyed by category, no case_id overlap.
    real = {"by_case": {}, "by_category": {"a": [9.0, 9.0], "b": [1.0, 1.0]}}
    rep = transfer.transfer_report(cases, scores, real)
    assert rep["status"] == "aggregate"
    assert rep["overall"]["spearman"] == pytest.approx(1.0)
    assert rep["shared_categories"] == ["a", "b"]


def test_case_synthetic_score_ignores_none_dims():
    s = Score(case_id="x", dimensions={"a": 8, "b": None})
    assert transfer.case_synthetic_score(s) == 8.0
    assert transfer.case_synthetic_score(Score(case_id="y", dimensions={})) is None
    assert transfer.case_synthetic_score(None) is None


# ── report section ────────────────────────────────────────────────────────────

def test_transfer_section_empty_for_no_report():
    assert transfer.transfer_section({}) == []


def test_transfer_section_renders_table():
    cases = [_case(f"c{i}", "alpha") for i in range(6)]
    scores = [_score(f"c{i}", i + 2) for i in range(6)]
    real = {"by_case": {f"c{i}": (i + 2) * 10.0 for i in range(6)}, "by_category": {}}
    rep = transfer.transfer_report(cases, scores, real)
    lines = transfer.transfer_section(rep)
    text = "\n".join(lines)
    assert "## Synthetic-to-real transfer" in text
    assert "| Category |" in text
    assert "alpha" in text
    assert "overall" in text


def test_transfer_section_insufficient_message():
    rep = {"status": "insufficient", "caveats": ["no overlap"], "overall": None,
           "categories": {}, "flags": []}
    text = "\n".join(transfer.transfer_section(rep))
    assert "Not enough real-outcome overlap" in text
