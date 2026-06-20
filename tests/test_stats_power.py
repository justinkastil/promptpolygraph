"""Sample-size / power planning + variance decomposition (ICC)."""

from __future__ import annotations

from promptpolygraph.analyze import stats


def test_sample_size_for_proportion_reference():
    # ±5% at 95% on p=0.5 -> 384.16 -> 385 (textbook)
    assert stats.sample_size_for_proportion(0.05) == 385
    # tighter margin needs more; a planning p far from 0.5 needs fewer
    assert stats.sample_size_for_proportion(0.01) > stats.sample_size_for_proportion(0.05)
    assert stats.sample_size_for_proportion(0.05, p=0.1) < 385


def test_min_n_for_proportion_diff_monotonic():
    big = stats.min_n_for_proportion_diff(0.10, 0.12)   # small effect -> large n
    small = stats.min_n_for_proportion_diff(0.10, 0.40)  # big effect -> small n
    assert big > small > 0
    assert stats.min_n_for_proportion_diff(0.2, 0.2) == 0  # no effect


def test_power_increases_with_n():
    p_lo = stats.power_for_proportion_diff(0.10, 0.20, 50, 50)
    p_hi = stats.power_for_proportion_diff(0.10, 0.20, 500, 500)
    assert 0.0 <= p_lo < p_hi <= 1.0
    # at the planned n, power should be near the 0.8 target
    n = stats.min_n_for_proportion_diff(0.10, 0.20, power=0.8)
    assert stats.power_for_proportion_diff(0.10, 0.20, n, n) >= 0.78


def test_variance_components_icc():
    # judges agree perfectly -> ICC 1.0
    agree = stats.variance_components([[8, 8], [3, 3], [6, 6], [9, 9]])
    assert agree["icc"] == 1.0 and agree["interpretation"] == "excellent"
    # judges disagree wildly -> low/negative ICC
    noisy = stats.variance_components([[8, 2], [3, 7], [6, 1], [9, 4]])
    assert noisy["icc"] < 0.5 and noisy["interpretation"] == "poor"
    # degenerate inputs
    assert stats.variance_components([[8, 8]])["icc"] is None         # <2 items
    assert stats.variance_components([[8], [3]])["icc"] is None       # <2 raters


def test_cli_power(capsys):
    from promptpolygraph.cli import main
    assert main(["power", "--margin", "0.05"]) == 0
    assert "385" in capsys.readouterr().out
    assert main(["power", "--from", "0.1", "--to", "0.2"]) == 0
    assert "per run" in capsys.readouterr().out
    assert main(["power", "--from", "0.1", "--to", "0.2", "--n", "500"]) == 0
    assert "power to detect" in capsys.readouterr().out
    assert main(["power"]) == 1  # usage


def test_reliability_in_summary_with_ensemble():
    from promptpolygraph.analyze.gate import summarize
    from promptpolygraph.models import Case, Dimension, Response, Rubric, Score

    rubric = Rubric(dimensions=[Dimension(name="quality")], threshold=7.0)
    cases, responses, scores = [], [], []
    # 4 cases, 2 judges each, judges agree closely -> high ICC
    pairs = [(9, 9), (3, 4), (7, 6), (10, 9)]
    for i, (a, b) in enumerate(pairs):
        c = Case(id=f"c{i}", prompt="p", category="x")
        cases.append(c)
        responses.append(Response(case_id=c.id, text="r"))
        scores.append(Score(case_id=c.id, dimensions={"quality": round((a + b) / 2)},
                            judges=[{"quality": a}, {"quality": b}]))
    summ = summarize(cases, responses, scores, rubric)
    rel = summ["confidence"]["reliability"]
    assert "quality" in rel and rel["quality"]["n_raters"] == 2
    assert rel["quality"]["icc"] is not None
