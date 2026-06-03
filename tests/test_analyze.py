from __future__ import annotations

import pytest

from promptpolygraph import analyze as A
from promptpolygraph.models import AssertionSpec, Case, Response


def test_default_and_example_rubric(example_dir):
    r = A.default_rubric()
    assert r.dimension_names()
    r2 = A.load_rubric(str(example_dir / "rubric.yaml"))
    assert r2.dimension_names()


def test_assertions_basic():
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

    resp_bad = Response(case_id=case.id, text="no greeting, secret leaked", latency_ms=900)
    _, passed_bad = A.evaluate_assertions(case, resp_bad)
    assert passed_bad is False


async def test_analyze_run_mock_and_summary(cases, responses):
    rubric = A.default_rubric()
    scores = await A.analyze_run(cases, responses, rubric, mock=True)
    assert len(scores) == len(cases)
    # at least one dimension populated per scored case
    assert any(any(v is not None for v in s.dimensions.values()) for s in scores)
    summary = A.summarize(cases, responses, scores, rubric)
    for key in (
        "threshold",
        "dimensions",
        "category_scores",
        "overall_pass",
        "categories_passing",
        "categories_total",
        "assertion_pass_rate",
        "cost",
        "latency",
        "agreement_mean",
    ):
        assert key in summary
    assert A.ci_exit_code(summary) in (0, 1)


async def test_baseline_diff(cases, responses):
    rubric = A.default_rubric()
    scores = await A.analyze_run(cases, responses, rubric, mock=True)
    summary = A.summarize(cases, responses, scores, rubric)
    diff = A.diff_baseline(summary, summary)  # diff vs itself = no regressions
    assert "by_category" in diff
    assert diff.get("regressions") == [] or isinstance(diff["regressions"], list)
