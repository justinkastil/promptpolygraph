"""Rubric-vs-persona discordance scatter."""

from __future__ import annotations

from promptpolygraph.models import Score
from promptpolygraph.report import charts


def _audit(case_vals):
    """case_vals: {case_id: persona_mean}. One persona, trust=usefulness=clarity=mean."""
    return {"persona": {"reactions": [{"persona": "P", "reactions": [
        {"case_id": cid, "trust": v, "usefulness": v, "clarity": v}
        for cid, v in case_vals.items()]}]}}


def test_discordance_points_intersection_only():
    scores = [Score(case_id="a", dimensions={"q": 9}),
              Score(case_id="b", dimensions={"q": 8}),
              Score(case_id="c", dimensions={"q": 7})]  # 'c' has no persona reaction
    audit = _audit({"a": 3.0, "b": 8.0})
    pts = charts._discordance_points(scores, audit, 10.0)
    ids = {p["case_id"] for p in pts}
    assert ids == {"a", "b"}  # only cases scored on both axes
    a = next(p for p in pts if p["case_id"] == "a")
    assert a["rubric"] == 9.0 and a["persona"] == 3.0


def test_discordance_scatter_flags_off_diagonal():
    # 'a' = high rubric (9) but low persona (3) -> discordant (red)
    scores = [Score(case_id="a", dimensions={"q": 9}),
              Score(case_id="b", dimensions={"q": 9})]
    audit = _audit({"a": 3.0, "b": 9.0})
    svg = charts.discordance_scatter(scores, audit, threshold=7.0)
    assert svg.lstrip().startswith("<svg")
    assert "discordant (1)" in svg  # exactly one off-diagonal case
    assert "2 cases" in svg
    assert charts._RED in svg and charts._GREEN in svg


def test_discordance_scatter_empty_when_no_overlap():
    svg = charts.discordance_scatter([], {}, threshold=7.0)
    assert "No rubric/persona overlap" in svg


def test_discordance_wired_into_report_context():
    from promptpolygraph.report.context import build_context
    from promptpolygraph.models import Case, Response, RunMeta, Rubric, Dimension
    cases = [Case(id="a", prompt="p", category="x")]
    responses = [Response(case_id="a", text="r")]
    scores = [Score(case_id="a", dimensions={"q": 9}, verdict_pass=True)]
    summary = {"threshold": 7.0, "dimensions": ["q"],
               "category_scores": {"x": {"q": 9.0, "pass": True, "count": 1}}}
    audit = _audit({"a": 2.0})
    ctx = build_context(RunMeta(name="t"), cases, responses, scores, summary,
                        rubric=Rubric(dimensions=[Dimension(name="q")]), audit=audit)
    assert ctx["charts"]["discordance"] is not None
    assert "discordant (1)" in ctx["charts"]["discordance"]
