"""GitHub Actions annotations + PR-comment markdown from a summary/baseline."""

from __future__ import annotations

from promptpolygraph.ci import github


def _summary(*, overall_pass, cat_pass, band_overall="pass", bands=None):
    return {
        "threshold": 7.0,
        "dimensions": ["quality"],
        "overall_pass": overall_pass,
        "categories_passing": sum(1 for v in cat_pass.values() if v),
        "categories_total": len(cat_pass),
        "category_scores": {c: {"quality": 8.0 if p else 4.0, "pass": p, "count": 40}
                            for c, p in cat_pass.items()},
        "confidence": {"assertion_pass_rate": {"value": 0.9, "ci_lower": 0.8,
                                               "ci_upper": 0.95, "n": 40},
                       "warnings": []},
        "gate_band": {"overall": band_overall, "by_category": bands or {}},
    }


def test_annotations_failing_gate():
    s = _summary(overall_pass=False, cat_pass={"a": True, "b": False})
    lines = github.annotations(s)
    assert any(l.startswith("::error") and "b" in l for l in lines)


def test_annotations_inconclusive_band_is_warning():
    s = _summary(overall_pass=True, cat_pass={"a": True},
                 band_overall="inconclusive", bands={"a": "inconclusive"})
    lines = github.annotations(s)
    assert any(l.startswith("::warning") and "inconclusive" in l.lower() for l in lines)


def test_annotations_significant_regression_is_error():
    s = _summary(overall_pass=True, cat_pass={"a": True})
    diff = {
        "regressions": [{"category": "a", "dimension": "quality", "delta": -1.5,
                         "current": 6.5, "baseline": 8.0}],
        "improvements": [],
        "significant_regressions": [{"category": "a", "dimension": "quality", "delta": -1.5,
                                     "current": 6.5, "baseline": 8.0, "q_value": 0.01}],
        "significance": {"available": True},
    }
    lines = github.annotations(s, diff)
    assert any(l.startswith("::error") and "regression" in l.lower() for l in lines)


def test_pr_comment_markdown_contents():
    s = _summary(overall_pass=True, cat_pass={"a": True, "b": True})
    diff = {
        "regressions": [{"category": "b", "dimension": "quality", "delta": -0.8,
                         "current": 7.2, "baseline": 8.0}],
        "improvements": [],
        "significant_regressions": [],
        "significance": {"available": True},
    }
    md = github.pr_comment_markdown(s, diff, run_id="abc123")
    assert "PASS" in md
    assert "abc123" in md
    assert "Change vs baseline" in md
    assert "Assertion pass rate" in md
    assert "| Category |" in md  # score table


def test_pr_comment_significance_unavailable_note():
    s = _summary(overall_pass=True, cat_pass={"a": True})
    diff = {"regressions": [], "improvements": [], "significant_regressions": [],
            "significance": {"available": False}}
    md = github.pr_comment_markdown(s, diff)
    assert "significance unavailable" in md.lower()


def test_write_step_summary_off_when_no_env(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert github.write_step_summary("hello") is False


def test_write_step_summary_appends(tmp_path, monkeypatch):
    f = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
    assert github.write_step_summary("hello") is True
    assert "hello" in f.read_text()
