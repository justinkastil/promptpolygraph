"""Judge metadata pinning + judge-drift canary (issue #38).

Covers: judge_meta is recorded on a real pipeline run; the canary set passes
under a correct judge and detects a flipped (wrong) judge; compare/trend surface
a caveat when two runs were graded by different judges.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from promptpolygraph.analyze import default_rubric, judge_identity, summarize
from promptpolygraph.calibrate import judge_canary, load_canary
from promptpolygraph.cli import main
from promptpolygraph.compare import compare_runs, trend_judge_drift
from promptpolygraph.models import (
    Case,
    RunMeta,
    Score,
    judge_meta_differs,
    system_prompt_hash,
)
from promptpolygraph.runner import SQLiteStore

CONFIG = "examples/support_bot/config.yaml"


# ─── (1) judge_meta recorded ──────────────────────────────────────────────────


def test_judge_meta_default_empty_and_additive():
    # Old records (no judge_meta) validate to an empty dict, not an error.
    m = RunMeta(run_id="r0")
    assert m.judge_meta == {}


def test_judge_identity_has_prompt_hash_without_config():
    ident = judge_identity(default_rubric(), None, mock=True)
    assert ident["system_prompt_hash"] is not None
    assert ident["mock"] is True
    # Same rubric -> stable hash.
    assert ident["system_prompt_hash"] == judge_identity(default_rubric())["system_prompt_hash"]


def test_run_records_judge_meta(tmp_path):
    out = tmp_path / "out"
    # `all` exits with the CI gate code (1 when the mock SUT fails the gate); the
    # run itself still completes and is persisted, which is what we assert here.
    main(["all", "--config", CONFIG, "--mock", "--out-dir", str(out), "--format", "md"])
    store = SQLiteStore(out / "polygraph.sqlite")
    meta = store.list_runs()[0]
    jm = meta.judge_meta
    assert jm  # populated, not empty
    assert "system_prompt_hash" in jm and jm["system_prompt_hash"]
    assert "provider" in jm and "model" in jm and "temperature" in jm


# ─── (2) canary detects a wrong judge ─────────────────────────────────────────


def test_canary_passes_under_correct_judge():
    report = asyncio.run(judge_canary(mock=True))
    assert report["n"] >= 8
    assert report["pass_rate"] == 1.0
    assert report["drift"] is False
    assert report["flags"] == []


def test_canary_content_is_benign():
    # Guard the constraint: no health/company/IP/competitor terms in the set.
    blob = json.dumps(load_canary()).lower()
    for term in ("patient", "clinical", "diagnos", "blockhaven", "haven", "patent"):
        assert term not in blob


def test_canary_detects_flipped_judge(monkeypatch):
    # Monkeypatch the breach judge to flip every verdict; the canary must flag drift.
    import promptpolygraph.calibrate as cal
    from promptpolygraph.redteam.judge import breach_judge as real_judge

    async def flipped(client, attempt, **kw):
        v = await real_judge(client, attempt, **kw)
        v.breached = not v.breached
        return v

    monkeypatch.setattr(cal, "breach_judge", flipped, raising=False)
    # The function imports breach_judge lazily inside its body; patch that path too.
    monkeypatch.setattr("promptpolygraph.redteam.judge.breach_judge", flipped, raising=False)

    report = asyncio.run(judge_canary(mock=True))
    assert report["drift"] is True
    assert report["pass_rate"] < 1.0
    assert report["flags"]
    assert report["misses"]


# ─── (3) compare/trend warn on judge_meta difference ──────────────────────────


def test_judge_meta_differs_helper():
    a = {"model": "m1", "provider": "p", "temperature": 0.0, "system_prompt_hash": "h"}
    b = dict(a)
    assert judge_meta_differs(a, b) is False
    assert judge_meta_differs({}, {}) is False  # pre-v1.1 runs don't false-flag
    assert judge_meta_differs(a, {**b, "model": "m2"}) is True
    assert judge_meta_differs(a, {**b, "system_prompt_hash": "h2"}) is True


def _build_two_runs(out: Path, jm_a: dict, jm_b: dict):
    store = SQLiteStore(out / "polygraph.sqlite")
    rubric = default_rubric()
    dims = rubric.dimension_names()
    cases = [Case(id="c1", prompt="p1", category="support")]
    store.save_cases("runA", cases)
    store.save_cases("runB", cases)
    store.save_score("runA", Score(case_id="c1", dimensions={d: 9 for d in dims}))
    store.save_score("runB", Score(case_id="c1", dimensions={d: 9 for d in dims}))

    fp, rf = "corpusfp00000000", "rubricfp00000000"
    store.save_run(RunMeta(run_id="runA", created_at="2026-01-01T00:00:00+00:00",
                           corpus_fingerprint=fp, rubric_fingerprint=rf, project="p",
                           judge_meta=jm_a))
    store.save_run(RunMeta(run_id="runB", created_at="2026-01-02T00:00:00+00:00",
                           corpus_fingerprint=fp, rubric_fingerprint=rf, project="p",
                           judge_meta=jm_b))
    for rid in ("runA", "runB"):
        (out / rid).mkdir(parents=True, exist_ok=True)
        summ = summarize(store.get_cases(rid), [], store.get_scores(rid), rubric)
        (out / rid / "summary.json").write_text(json.dumps(summ))
    return store


def test_compare_flags_judge_drift(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    jm_a = {"model": "m1", "provider": "p", "temperature": 0.0,
            "system_prompt_hash": system_prompt_hash("rubric prompt one")}
    jm_b = {"model": "m2", "provider": "p", "temperature": 0.0,
            "system_prompt_hash": system_prompt_hash("rubric prompt one")}
    store = _build_two_runs(out, jm_a, jm_b)

    report = compare_runs(store, ["runA", "runB"], out)
    jd = report["judge_drift"]
    assert jd["differs"] is True
    assert jd["caveat"]


def test_compare_no_drift_when_same_judge(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    jm = {"model": "m1", "provider": "p", "temperature": 0.0,
          "system_prompt_hash": system_prompt_hash("rubric prompt one")}
    store = _build_two_runs(out, jm, dict(jm))

    report = compare_runs(store, ["runA", "runB"], out)
    assert report["judge_drift"]["differs"] is False
    assert report["judge_drift"]["caveat"] is None


def test_trend_judge_drift(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    jm_a = {"model": "m1", "provider": "p", "temperature": 0.0, "system_prompt_hash": "h"}
    jm_b = {"model": "m2", "provider": "p", "temperature": 0.0, "system_prompt_hash": "h"}
    store = _build_two_runs(out, jm_a, jm_b)

    drift = trend_judge_drift(store, project="p", window=30)
    assert drift["differs"] is True
    assert drift["caveat"]
