from __future__ import annotations

from pathlib import Path

import pytest

from promptpolygraph import analyze as A
from promptpolygraph import audit as AU
from promptpolygraph import persona as P
from promptpolygraph.compare import pairwise
from promptpolygraph.models import RunMeta
from promptpolygraph.report import build_report


def test_persona_library_loads():
    lib = P.load_library()
    assert len(lib) >= 12
    assert all(p.id and p.who for p in lib)
    pool = P.sample_pool(5, seed=1)
    assert len({p.id for p in pool}) == 5


async def test_create_persona_mock():
    p = await P.create_persona(None, "a grumpy retiree who hates phone trees", mock=True)
    assert p.id and p.who


async def test_run_audit_mock(cases, responses):
    rubric = A.default_rubric()
    scores = await A.analyze_run(cases, responses, rubric, mock=True)
    personas = P.sample_pool(3, seed=2)
    sample = [
        {
            "category": c.category,
            "case_id": c.id,
            "prompt": c.prompt,
            "response": r.text,
            "rubric_scores": {k: v for k, v in s.dimensions.items() if v is not None},
            "expected_behavior": c.expected_behavior,
        }
        for c, r, s in zip(cases, responses, scores)
    ]
    audit = await AU.run_audit(cases, responses, scores, rubric, personas, sample, mock=True)
    assert "forensic" in audit and "persona" in audit
    assert audit["forensic"]["category_audits"]
    assert audit["persona"]["reactions"]


def test_pairwise(cases, responses):
    from promptpolygraph.models import Score

    a = [Score(case_id=c.id, dimensions={"Quality": 8}) for c in cases]
    b = [Score(case_id=c.id, dimensions={"Quality": 5}) for c in cases]
    pw = pairwise(cases, a, b)
    assert pw["wins_a"] == len(cases)
    assert pw["wins_b"] == 0


async def test_build_report_offline(cases, responses, tmp_path):
    rubric = A.default_rubric()
    scores = await A.analyze_run(cases, responses, rubric, mock=True)
    summary = A.summarize(cases, responses, scores, rubric)
    meta = RunMeta(name="t", adapter="callable")
    paths = build_report(
        meta, cases, responses, scores, summary,
        rubric=rubric, formats=["md", "html"], out_dir=str(tmp_path),
    )
    assert "md" in paths and "html" in paths
    md = Path(paths["md"]).read_text()
    assert "accuracy" in md
