"""Tests for the suggested_fix upgrade to the forensic audit.

Covers the mock (offline, deterministic) path of ``run_forensic`` and the
``CodeIndex.window`` / ``file_window`` surrounding-context helper. All offline:
no LLM calls, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptpolygraph.audit.code_context import CodeIndex, file_window
from promptpolygraph.audit.forensic import run_forensic
from promptpolygraph.models import Case, Dimension, Response, Rubric, Score

SRC = str(Path(__file__).resolve().parent.parent / "src" / "promptpolygraph")


def _rubric() -> Rubric:
    return Rubric(
        name="t",
        dimensions=[
            Dimension(name="Quality", description="overall quality"),
            Dimension(name="Accuracy", description="factual accuracy"),
        ],
        threshold=7.0,
        scale_max=10,
    )


def _fixture() -> tuple[list[Case], list[Response], list[Score], Rubric]:
    cases = [
        Case(prompt="reset my password", category="accuracy"),
        Case(prompt="cancel my plan", category="accuracy"),
        Case(prompt="", category="edge_input"),
    ]
    responses = [Response(case_id=c.id, text="some answer") for c in cases]
    # accuracy is weak (below threshold); edge_input passes.
    scores = [
        Score(case_id=cases[0].id, dimensions={"Quality": 4, "Accuracy": 3}, verdict_pass=False),
        Score(case_id=cases[1].id, dimensions={"Quality": 5, "Accuracy": 4}, verdict_pass=False),
        Score(case_id=cases[2].id, dimensions={"Quality": 9, "Accuracy": 9}, verdict_pass=True),
    ]
    return cases, responses, scores, _rubric()


@pytest.mark.asyncio
async def test_mock_emits_suggested_fix_with_rationale():
    cases, responses, scores, rubric = _fixture()
    result = await run_forensic(cases, responses, scores, rubric, mock=True)

    assert set(result.keys()) == {"category_audits", "synthesis"}
    audits = result["category_audits"]
    assert audits, "expected at least one category audit"

    saw_fix = False
    for ca in audits:
        for lc in ca["leverage_changes"]:
            # additive field present on every leverage change
            assert "suggested_fix" in lc
            fix = lc["suggested_fix"]
            assert isinstance(fix, dict)
            assert fix.get("rationale")  # non-empty rationale
            # mock path is code-free: never fabricate file paths.
            assert fix["file"] is None
            assert fix["diff"] is None
            assert fix["locus"] is None
            saw_fix = True
    assert saw_fix, "no leverage_changes carried a suggested_fix"


@pytest.mark.asyncio
async def test_mock_result_is_json_serializable_and_structure_unchanged():
    cases, responses, scores, rubric = _fixture()
    result = await run_forensic(cases, responses, scores, rubric, mock=True)

    # round-trips cleanly
    blob = json.dumps(result)
    assert json.loads(blob) == result

    # original schema keys still present + unchanged
    for ca in result["category_audits"]:
        assert {"category", "gap_dims", "failure_modes", "leverage_changes",
                "highest_leverage_one_liner"} <= set(ca.keys())
    synth = result["synthesis"]
    assert {"cross_category_patterns", "prioritized_changes",
            "closest_to_pass", "narrative"} <= set(synth.keys())


@pytest.mark.asyncio
async def test_code_path_offline_still_yields_nocode_fix():
    """With code_path set but mock=True (offline), schema includes suggested_fix
    and the deterministic no-code path keeps file=null (no fabricated paths)."""
    cases, responses, scores, rubric = _fixture()
    result = await run_forensic(
        cases, responses, scores, rubric, code_path=SRC, mock=True
    )
    fixes = [
        lc["suggested_fix"]
        for ca in result["category_audits"]
        for lc in ca["leverage_changes"]
    ]
    assert fixes
    for fix in fixes:
        assert fix["file"] is None
        assert fix["rationale"]


def test_file_window_returns_surrounding_context():
    idx = CodeIndex(SRC)
    rels = [r for r, _ in idx._files]
    target = next(r for r in rels if r.endswith("forensic.py"))
    win = file_window(SRC, target, 50, index=idx, before=5, after=5)
    assert win
    # line-numbered ("   50| ...") and centered near requested line
    nums = [
        int(seg.split("|")[0].strip())
        for seg in win.splitlines()
        if "|" in seg and seg.split("|")[0].strip().isdigit()
    ]
    assert nums
    assert min(nums) <= 50 <= max(nums)
    assert max(nums) - min(nums) <= 12  # bounded window (before+after)


def test_file_window_unknown_file_and_no_path_degrade():
    idx = CodeIndex(SRC)
    assert file_window(SRC, "does/not/exist.py", 10, index=idx) == ""
    assert file_window(None, "anything.py", 1) == ""
    assert file_window("/no/such/path/xyz", "anything.py", 1) == ""
