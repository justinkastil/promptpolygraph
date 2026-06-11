"""Tests for the v0.3 scoring-power upgrade: weighted/threshold/negate/metric
assertions, new assertion kinds, semantic similarity, the custom-code sandbox,
named/derived metrics in the summary, weighted gating, and cost population."""

from __future__ import annotations

import asyncio

import pytest

from promptpolygraph import analyze as A
from promptpolygraph.adapters import HTTPAdapter
from promptpolygraph.adapters.demo import DemoAdapter
from promptpolygraph.adapters.llm import compute_cost
from promptpolygraph.analyze.assertions import SandboxError, safe_eval, score_assertions
from promptpolygraph.analyze.embedders import MockEmbedder, cosine
from promptpolygraph.config import (
    AnalyzeConfig,
    AssertionSpecModel,
    Config,
    EmbeddersConfig,
    MetricSpec,
    ScorersConfig,
)
from promptpolygraph.models import AssertionSpec, Case, Response, Rubric


def _run(coro):
    return asyncio.run(coro)


# ─── Weighted / threshold / negate ──────────────────────────────────────────


def test_weighted_assertion_score():
    case = Case(
        prompt="x",
        assertions=[
            AssertionSpec(kind="contains", value="hello", weight=3.0),
            AssertionSpec(kind="contains", value="zzz", weight=1.0),
        ],
    )
    resp = Response(case_id=case.id, text="hello world")
    results, all_passed, ascore = _run(score_assertions(case, resp))
    assert results[0].passed is True and results[0].value == 1.0
    assert results[1].passed is False and results[1].value == 0.0
    assert all_passed is False
    # (3*1.0 + 1*0.0) / (3+1) = 0.75
    assert ascore == pytest.approx(0.75)


def test_negate_flips_pass_and_value():
    case = Case(prompt="x", assertions=[AssertionSpec(kind="contains", value="secret", negate=True)])
    clean = Response(case_id=case.id, text="all good")
    leaked = Response(case_id=case.id, text="the secret is out")
    r_clean, _, _ = _run(score_assertions(case, clean))
    r_leak, _, _ = _run(score_assertions(case, leaked))
    assert r_clean[0].passed is True and r_clean[0].value == 1.0
    assert r_leak[0].passed is False and r_leak[0].value == 0.0


def test_threshold_gates_on_continuous_value():
    case = Case(
        prompt="x",
        assertions=[
            AssertionSpec(kind="contains_all", value=["a", "b", "c", "d"], threshold=0.75)
        ],
    )
    resp = Response(case_id=case.id, text="a b c only")  # 3/4 = 0.75
    r, passed, _ = _run(score_assertions(case, resp))
    assert r[0].value == pytest.approx(0.75)
    assert r[0].passed is True
    resp2 = Response(case_id=case.id, text="a b only")  # 2/4 = 0.5
    r2, passed2, _ = _run(score_assertions(case, resp2))
    assert r2[0].passed is False


# ─── New kinds ──────────────────────────────────────────────────────────────


def test_new_kinds():
    case = Case(
        prompt="x",
        assertions=[
            AssertionSpec(kind="icontains", value="HELLO"),
            AssertionSpec(kind="contains_any", value=["nope", "world"]),
            AssertionSpec(kind="starts_with", value="hello"),
            AssertionSpec(kind="is_refusal"),
            AssertionSpec(kind="levenshtein", value="hello world", threshold=0.9),
            AssertionSpec(kind="cost_under", value=0.01),
        ],
    )
    resp = Response(case_id=case.id, text="hello world", cost_usd=0.001)
    results, _, _ = _run(score_assertions(case, resp))
    by_kind = {r.kind: r for r in results}
    assert by_kind["icontains"].passed is True
    assert by_kind["contains_any"].passed is True
    assert by_kind["starts_with"].passed is True
    assert by_kind["is_refusal"].passed is False  # not a refusal
    assert by_kind["levenshtein"].passed is True and by_kind["levenshtein"].value == 1.0
    assert by_kind["cost_under"].passed is True


def test_is_refusal_detects_refusal():
    case = Case(prompt="x", assertions=[AssertionSpec(kind="is_refusal")])
    resp = Response(case_id=case.id, text="I can't help with that request.")
    r, _, _ = _run(score_assertions(case, resp))
    assert r[0].passed is True


def test_cost_under_no_cost_fails():
    case = Case(prompt="x", assertions=[AssertionSpec(kind="cost_under", value=0.01)])
    resp = Response(case_id=case.id, text="hi")  # no cost recorded
    r, _, _ = _run(score_assertions(case, resp))
    assert r[0].passed is False


# ─── Semantic similarity (offline) ──────────────────────────────────────────


def test_cosine_and_mock_embedder_offline():
    emb = MockEmbedder()
    vecs = _run(emb.embed(["the cat sat on the mat", "the cat sat on the mat"]))
    assert cosine(vecs[0], vecs[1]) == pytest.approx(1.0)
    # deterministic / reproducible
    vecs2 = _run(emb.embed(["the cat sat on the mat"]))
    assert vecs2[0] == vecs[0]


def test_similar_assertion_thresholds():
    emb = MockEmbedder()
    case = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="similar", value="reset your password", threshold=0.6)],
    )
    close = Response(case_id=case.id, text="to reset your password open settings")
    r_close, _, _ = _run(score_assertions(case, close, embedder=emb))
    assert r_close[0].value is not None and r_close[0].value > 0.0
    far = Response(case_id=case.id, text="the weather today is sunny and warm outside")
    r_far, _, _ = _run(score_assertions(case, far, embedder=emb))
    # the related text should score higher similarity than the unrelated one
    assert r_close[0].value > r_far[0].value


# ─── Custom-code sandbox ────────────────────────────────────────────────────


def test_python_disabled_refuses():
    case = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="python", options={"expr": "len(output) > 0"})],
    )
    resp = Response(case_id=case.id, text="anything")
    r, _, _ = _run(score_assertions(case, resp, sandbox="disabled"))
    assert r[0].passed is False
    assert "disabled" in r[0].detail


def test_python_expr_evaluates_safely():
    case = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="python", options={"expr": "output.count('x') < 3"})],
    )
    ok = Response(case_id=case.id, text="x x")  # 2 < 3
    bad = Response(case_id=case.id, text="x x x x")  # 4 < 3 is False
    r_ok, _, _ = _run(score_assertions(case, ok, sandbox="expr"))
    r_bad, _, _ = _run(score_assertions(case, bad, sandbox="expr"))
    assert r_ok[0].passed is True
    assert r_bad[0].passed is False


def test_expr_cannot_import_or_dunder():
    for expr in ("__import__('os').system('echo hi')", "output.__class__"):
        with pytest.raises(SandboxError):
            safe_eval(expr, {"output": "abc"})


def test_python_expr_import_yields_failed_result_not_raise():
    case = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="python", options={"expr": "__import__('os')"})],
    )
    resp = Response(case_id=case.id, text="hi")
    r, _, _ = _run(score_assertions(case, resp, sandbox="expr"))
    assert r[0].passed is False
    assert "sandbox rejected" in r[0].detail


def test_callable_kind():
    case = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="callable", options={"ref": "math:isnan"})],
    )
    # math.isnan(resp) would fail (resp is not a float) -> caught -> failed result
    resp = Response(case_id=case.id, text="hi")
    r, _, _ = _run(score_assertions(case, resp, sandbox="expr"))
    assert r[0].passed is False  # gracefully handled, no raise


# ─── Backward-compatibility of evaluate_assertions ──────────────────────────


def test_evaluate_assertions_back_compat():
    case = Case(
        prompt="x",
        assertions=[
            AssertionSpec(kind="contains", value="hello"),
            AssertionSpec(kind="not_contains", value="secret"),
            AssertionSpec(kind="max_latency_ms", value=500),
        ],
    )
    resp = Response(case_id=case.id, text="well hello there", latency_ms=120)
    results, passed = A.evaluate_assertions(case, resp)
    assert passed is True
    assert len(results) == 3


# ─── Summary: new keys + strict reproduction + weighted + derived metric ─────


def _fixture():
    cases = [
        Case(prompt="a", category="accuracy"),
        Case(prompt="b", category="safety", red_flags=["insult"]),
    ]
    responses = [
        Response(case_id=cases[0].id, text="a fairly long and helpful answer here for grading", latency_ms=100),
        Response(case_id=cases[1].id, text="a fairly long and helpful answer here for grading", latency_ms=90),
    ]
    return cases, responses


def test_summarize_has_all_original_keys_plus_new():
    cases, responses = _fixture()
    rubric = A.default_rubric()
    scores = _run(A.analyze_run(cases, responses, rubric, mock=True))
    summary = A.summarize(cases, responses, scores, rubric)
    for key in (
        "threshold", "dimensions", "category_scores", "overall_pass",
        "categories_passing", "categories_total", "assertion_pass_rate",
        "cost", "latency", "agreement_mean",
    ):
        assert key in summary
    assert "metrics" in summary
    assert "assertion_score_mean" in summary
    assert isinstance(summary["assertion_score_mean"], float)


def test_strict_gate_reproduces_prior_verdict():
    """A known fixture: with no config the gate is strict and matches the
    original case_pass rule exactly."""
    rubric = Rubric(
        name="t",
        dimensions=A.default_rubric().dimensions,
        threshold=7.0,
        scale_max=10,
    )
    cases, responses = _fixture()
    # default (no config) path
    scores_default = _run(A.analyze_run(cases, responses, rubric, mock=True))
    # strict via config path
    cfg = Config(analyze=AnalyzeConfig(gate_mode="strict"))
    scores_strict = _run(A.analyze_run(cases, responses, rubric, mock=True, config=cfg))
    assert [s.verdict_pass for s in scores_default] == [s.verdict_pass for s in scores_strict]
    s_default = A.summarize(cases, responses, scores_default, rubric)
    s_cfg = A.summarize(cases, responses, scores_strict, rubric, config=cfg)
    assert s_default["overall_pass"] == s_cfg["overall_pass"]
    assert s_default["category_scores"].keys() == s_cfg["category_scores"].keys()
    for cat in s_default["category_scores"]:
        assert s_default["category_scores"][cat]["pass"] == s_cfg["category_scores"][cat]["pass"]


def test_weighted_gate_mode_runs():
    rubric = A.default_rubric()
    cases, responses = _fixture()
    weights = {d: 1.0 for d in rubric.dimension_names()}
    cfg = Config(analyze=AnalyzeConfig(gate_mode="weighted", dimension_weights=weights))
    scores = _run(A.analyze_run(cases, responses, rubric, mock=True, config=cfg))
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    assert "overall_pass" in summary
    assert all(s.verdict_pass in (True, False) for s in scores)


def test_derived_f1_metric_computes():
    cfg = Config(
        scorers=ScorersConfig(
            shared=[
                AssertionSpecModel(kind="contains", value="answer", metric="precision"),
                AssertionSpecModel(kind="contains", value="helpful", metric="recall"),
            ]
        ),
        metrics=[
            MetricSpec(name="precision"),
            MetricSpec(name="recall"),
            MetricSpec(name="f1", formula="2*precision*recall/(precision+recall+1e-9)"),
        ],
    )
    cases, responses = _fixture()
    rubric = A.default_rubric()
    scores = _run(A.analyze_run(cases, responses, rubric, mock=True, config=cfg))
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    m = summary["metrics"]
    assert "precision" in m and "recall" in m and "f1" in m
    # both shared assertions pass (text contains "answer" and "helpful") -> p=r=1 -> f1≈1
    assert m["precision"] == pytest.approx(1.0)
    assert m["recall"] == pytest.approx(1.0)
    assert m["f1"] == pytest.approx(1.0, abs=1e-3)


def test_metric_threshold_participates_in_gate():
    cfg = Config(
        scorers=ScorersConfig(
            shared=[AssertionSpecModel(kind="contains", value="WILL_NOT_MATCH", metric="precision")]
        ),
        metrics=[MetricSpec(name="precision", threshold=0.5)],
    )
    cases, responses = _fixture()
    rubric = A.default_rubric()
    scores = _run(A.analyze_run(cases, responses, rubric, mock=True, config=cfg))
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    assert summary["metrics"]["precision"] == pytest.approx(0.0)
    assert summary["overall_pass"] is False  # metric below threshold fails the gate
    assert A.ci_exit_code(summary) == 1


def test_embedder_config_threads_similar():
    cfg = Config(
        embedders=EmbeddersConfig(provider="mock"),
        scorers=ScorersConfig(
            shared=[AssertionSpecModel(kind="similar", value="helpful answer", metric="sim")]
        ),
        metrics=[MetricSpec(name="sim")],
    )
    cases, responses = _fixture()
    rubric = A.default_rubric()
    scores = _run(A.analyze_run(cases, responses, rubric, mock=True, config=cfg))
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    assert summary["metrics"]["sim"] is not None


# ─── Cost population in adapters ────────────────────────────────────────────


def test_demo_adapter_populates_cost():
    a = DemoAdapter()
    case = Case(prompt="how do I reset my password")
    resp = _run(a.query(case))
    assert resp.cost_usd is not None
    assert resp.cost_usd >= 0.0


def test_llm_compute_cost_from_price_table():
    c = compute_cost("claude-opus-4-8", tokens_in=1000, tokens_out=1000)
    # opus table: 0.015 in + 0.075 out per 1k
    assert c == pytest.approx(0.09)
    # override beats the table
    c2 = compute_cost("unknown-model", 1000, 1000, price_in=0.001, price_out=0.002)
    assert c2 == pytest.approx(0.003)
    # truly unknown + no override -> None
    assert compute_cost("unknown-model", 1000, 1000) is None


def test_http_adapter_cost_path_option():
    a = HTTPAdapter(url="https://x.test/chat", cost_path="usage.cost")
    assert a._cost_path == "usage.cost"
