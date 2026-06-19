"""Statistical-rigor module: intervals, significance tests, FDR, gate band.

Values are checked against textbook/reference results so the numerics are
trustworthy — the whole point of the module is defensibility.
"""

from __future__ import annotations

import math

from promptpolygraph.analyze import stats


def test_norm_ppf_known_quantiles():
    assert abs(stats.norm_ppf(0.975) - 1.959964) < 1e-4
    assert abs(stats.norm_ppf(0.95) - 1.644854) < 1e-4
    assert abs(stats.norm_ppf(0.5)) < 1e-9
    assert abs(stats.z_for_confidence(0.95) - 1.959964) < 1e-4
    assert abs(stats.z_for_confidence(0.99) - 2.575829) < 1e-4


def test_norm_cdf_roundtrips_ppf():
    for p in (0.05, 0.2, 0.5, 0.8, 0.975):
        assert abs(stats.norm_cdf(stats.norm_ppf(p)) - p) < 1e-6


def test_wilson_interval_extremes_and_midpoint():
    # 0/10 — interval pinned at 0 on the low side, ~0.278 high (reference).
    lo, hi = stats.wilson_interval(0, 10)
    assert lo == 0.0
    assert abs(hi - 0.2775) < 1e-3
    # 5/10 — symmetric reference interval ~ (0.2366, 0.7634).
    lo, hi = stats.wilson_interval(5, 10)
    assert abs(lo - 0.2366) < 1e-3
    assert abs(hi - 0.7634) < 1e-3
    # always inside [0,1]
    lo, hi = stats.wilson_interval(10, 10)
    assert 0.0 <= lo <= hi <= 1.0


def test_proportion_ci_shape():
    ci = stats.proportion_ci(3, 50)
    assert ci["value"] == 0.06 and ci["n"] == 50 and ci["method"] == "wilson"
    assert 0.0 <= ci["ci_lower"] < ci["value"] < ci["ci_upper"] <= 1.0


def test_proportion_ci_zero_n():
    ci = stats.proportion_ci(0, 0)
    assert ci["value"] == 0.0 and ci["ci_lower"] == 0.0 and ci["ci_upper"] == 0.0


def test_bootstrap_ci_deterministic_and_bracketing():
    vals = [5, 6, 7, 8, 9, 6, 7, 8, 7, 6]
    a = stats.bootstrap_ci(vals, seed=42)
    b = stats.bootstrap_ci(vals, seed=42)
    assert a == b  # deterministic under a fixed seed
    assert a["ci_lower"] <= a["value"] <= a["ci_upper"]
    assert a["n"] == 10


def test_bootstrap_ci_small_n():
    assert stats.bootstrap_ci([])["value"] is None
    one = stats.bootstrap_ci([4.0])
    assert one["value"] == 4.0 and one["ci_lower"] == 4.0 and one["ci_upper"] == 4.0


def test_mean_ci_matches_known_t_interval():
    # sample 2,4,4,4,5,5,7,9 : mean=5, *sample* sd=sqrt(32/7)=2.1381, n=8,
    # t_.975,7=2.3646 -> half = 2.3646 * 2.1381/sqrt(8) = 1.7875 -> (3.2125, 6.7875)
    ci = stats.mean_ci([2, 4, 4, 4, 5, 5, 7, 9])
    assert abs(ci["value"] - 5.0) < 1e-9
    assert abs(ci["ci_lower"] - 3.2125) < 1e-2
    assert abs(ci["ci_upper"] - 6.7875) < 1e-2


def test_two_proportion_ztest_significant_and_not():
    # 10/100 vs 30/100 — clearly different
    r = stats.two_proportion_ztest(10, 100, 30, 100)
    assert r["delta"] == 0.2 and r["p_value"] < 0.001
    # 50/100 vs 52/100 — not different
    r2 = stats.two_proportion_ztest(50, 100, 52, 100)
    assert r2["p_value"] > 0.5


def test_welch_ttest_detects_difference():
    a = [5, 5, 6, 5, 5, 6, 5, 5]
    b = [8, 9, 8, 9, 8, 9, 8, 9]
    r = stats.welch_ttest(a, b)
    assert r["delta"] > 0 and r["p_value"] < 0.001
    # identical samples -> not significant
    same = stats.welch_ttest([5, 6, 7], [5, 6, 7])
    assert same["p_value"] > 0.9


def test_welch_t_two_sided_p_reference():
    # t=2.0, df=10 -> two-sided p ~= 0.0734 (textbook)
    p = stats._t_two_sided_p(2.0, 10)
    assert abs(p - 0.0734) < 5e-3


def test_mcnemar_exact():
    # discordant b=1, c=9 -> two-sided exact p = 2 * sum_{i<=1} C(10,i)/2^10
    r = stats.mcnemar_test(1, 9)
    expected = min(1.0, 2 * (math.comb(10, 0) + math.comb(10, 1)) / 2 ** 10)
    assert abs(r["p_value"] - expected) < 1e-5  # function rounds to 6dp
    # balanced -> not significant
    assert stats.mcnemar_test(5, 5)["p_value"] == 1.0
    assert stats.mcnemar_test(0, 0)["p_value"] == 1.0


def test_benjamini_hochberg_controls_fdr():
    pvals = [0.001, 0.008, 0.039, 0.041, 0.9]
    out = stats.benjamini_hochberg(pvals, alpha=0.05)
    # the first two are clearly significant; the last is not.
    assert out["rejected"][0] and out["rejected"][1]
    assert not out["rejected"][-1]
    # q-values are monotone non-decreasing in p-order and >= raw p.
    assert all(q >= p - 1e-9 for q, p in zip(out["qvalues"], pvals))
    assert out["n_significant"] == sum(out["rejected"])


def test_benjamini_hochberg_empty():
    out = stats.benjamini_hochberg([])
    assert out["rejected"] == [] and out["n_significant"] == 0


def test_gate_band_decision_above():
    # whole band above threshold -> pass
    assert stats.gate_band_decision(7.5, 8.5, 7.0, direction="above") == "pass"
    # whole band below -> fail
    assert stats.gate_band_decision(5.0, 6.5, 7.0, direction="above") == "fail"
    # threshold inside band -> inconclusive (do not fail CI on noise)
    assert stats.gate_band_decision(6.5, 7.5, 7.0, direction="above") == "inconclusive"


def test_gate_band_decision_below():
    # ASR should stay below a ceiling: whole band under ceiling -> pass
    assert stats.gate_band_decision(0.02, 0.08, 0.10, direction="below") == "pass"
    # whole band over ceiling -> fail
    assert stats.gate_band_decision(0.15, 0.30, 0.10, direction="below") == "fail"
    # straddles -> inconclusive
    assert stats.gate_band_decision(0.05, 0.20, 0.10, direction="below") == "inconclusive"


def test_gate_band_decision_missing_band():
    assert stats.gate_band_decision(None, None, 7.0) == "inconclusive"
