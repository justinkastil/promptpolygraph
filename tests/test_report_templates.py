from __future__ import annotations

import asyncio

from promptpolygraph import analyze as A
from promptpolygraph.models import RunMeta
from promptpolygraph.report import render_html, render_markdown


def _fixture():
    from promptpolygraph.models import Case, Response

    cases = [
        Case(prompt="q1", category="accuracy"),
        Case(prompt="q2", category="tone"),
    ]
    responses = [Response(case_id=c.id, text=f"answer to {c.prompt}", latency_ms=100) for c in cases]
    rubric = A.default_rubric()
    scores = asyncio.run(A.analyze_run(cases, responses, rubric, mock=True))
    summary = A.summarize(cases, responses, scores, rubric)
    meta = RunMeta(name="t", adapter="demo")
    return meta, cases, responses, scores, summary, rubric


def test_default_template_renders():
    meta, cases, responses, scores, summary, rubric = _fixture()
    html = render_html(meta, cases, responses, scores, summary, rubric=rubric)
    assert "<html" in html.lower()
    md = render_markdown(meta, cases, responses, scores, summary, rubric=rubric)
    assert "accuracy" in md


def test_minimal_template_is_compact():
    meta, cases, responses, scores, summary, rubric = _fixture()
    full = render_html(meta, cases, responses, scores, summary, rubric=rubric, template="default")
    minimal = render_html(meta, cases, responses, scores, summary, rubric=rubric, template="minimal")
    assert len(minimal) < len(full)
    assert "<html" in minimal.lower()


def test_branding_applies():
    meta, cases, responses, scores, summary, rubric = _fixture()
    html = render_html(meta, cases, responses, scores, summary, rubric=rubric,
                       branding={"title": "Acme Eval", "accent": "#0aabbc"})
    assert "Acme Eval" in html and "#0aabbc" in html


def test_template_dir_override(tmp_path):
    meta, cases, responses, scores, summary, rubric = _fixture()
    (tmp_path / "report.html.j2").write_text("CUSTOM {{ cover.run_id }}")
    html = render_html(meta, cases, responses, scores, summary, rubric=rubric,
                       template_dir=str(tmp_path))
    assert html.startswith("CUSTOM ") and meta.run_id in html
