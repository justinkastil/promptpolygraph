"""Confidence intervals + band-aware gate wired through the real pipeline."""

from __future__ import annotations

import asyncio

from promptpolygraph.analyze.gate import summarize
from promptpolygraph.config import AnalyzeConfig, Config
from promptpolygraph.models import Case, Response, Rubric, Dimension, Score
from promptpolygraph.redteam.orchestrator import run_redteam
from promptpolygraph.redteam.profiles import get_profile
from promptpolygraph.redteam.report import render_md, render_json
from promptpolygraph.adapters.demo import DemoAdapter


def _rubric():
    return Rubric(dimensions=[Dimension(name="quality"), Dimension(name="safety")], threshold=7.0)


def _mk(cases_scores):
    cases, scores, responses = [], [], []
    for i, (cat, q, s) in enumerate(cases_scores):
        c = Case(id=f"c{i}", prompt="p", category=cat)
        cases.append(c)
        responses.append(Response(case_id=c.id, text="r", latency_ms=10))
        scores.append(Score(case_id=c.id, dimensions={"quality": q, "safety": s},
                            assertions_passed=True))
    return cases, responses, scores


def test_summary_carries_confidence_and_band_blocks():
    cases, responses, scores = _mk([("a", 8, 9), ("a", 9, 8), ("b", 8, 9)])
    summ = summarize(cases, responses, scores, _rubric())
    assert "confidence" in summ and "gate_band" in summ
    assert summ["confidence"]["level"] == 0.95
    # assertion pass rate CI present with n
    apr = summ["confidence"]["assertion_pass_rate"]
    assert apr["n"] == 3 and apr["method"] == "wilson"
    # each category has per-dimension CIs bracketing the mean
    a_ci = summ["confidence"]["by_category"]["a"]["dimensions"]["quality"]
    assert a_ci["ci_lower"] <= a_ci["value"] <= a_ci["ci_upper"]
    # small-N warning fires (3 < 30 default)
    assert any("cases" in w for w in summ["confidence"]["warnings"])
    assert summ["gate_band"]["overall"] in {"pass", "fail", "inconclusive"}


def test_respect_ci_does_not_fail_on_straddling_band():
    # Scores straddle the 7.0 threshold -> point gate fails, band is inconclusive.
    cases, responses, scores = _mk([("a", 6, 8), ("a", 8, 6), ("a", 7, 7), ("a", 6, 8)])
    rubric = _rubric()

    strict_cfg = Config(analyze=AnalyzeConfig(respect_ci=False))
    strict = summarize(cases, responses, scores, rubric, config=strict_cfg)
    assert strict["overall_pass"] is False  # strict point gate fails

    ci_cfg = Config(analyze=AnalyzeConfig(respect_ci=True))
    band = summarize(cases, responses, scores, rubric, config=ci_cfg)
    # with respect_ci, an inconclusive band does not turn the build red
    assert band["gate_band"]["overall"] in {"inconclusive", "pass"}
    assert band["overall_pass"] is True


def test_redteam_asr_carries_confidence_interval():
    report = asyncio.run(run_redteam(DemoAdapter(), get_profile("quick"), mock=True))
    assert "asr_ci" in report.stats
    ci = report.stats["asr_ci"]
    assert ci["n"] == report.stats["attacks"]
    assert 0.0 <= ci["ci_lower"] <= ci["ci_upper"] <= 1.0
    # the markdown report surfaces the Wilson CI line
    md = render_md(report)
    assert "ASR 95% CI" in md
    # json carries the machine-readable band
    j = render_json(report)
    assert j["asr_ci"]["method"] == "wilson"
