"""Tests for the history / comparison / trend / regression engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptpolygraph.analyze import (
    diff_baseline,
    rolling_baseline_summary,
    summarize,
)
from promptpolygraph.analyze.rubric import default_rubric
from promptpolygraph.cli import main
from promptpolygraph.compare import comparability, compare_runs, pairwise, trend
from promptpolygraph.models import Case, Score
from promptpolygraph.runner import SQLiteStore

CONFIG = "examples/support_bot/config.yaml"


def _do_run(out_dir: Path) -> str:
    """Run `polygraph all --mock` into out_dir; return the new run id."""
    store_path = out_dir / "polygraph.sqlite"
    before = set()
    if store_path.exists():
        before = {m.run_id for m in SQLiteStore(store_path).list_runs()}
    rc = main(["all", "--config", CONFIG, "--mock", "--out-dir", str(out_dir), "--format", "md"])
    assert rc in (0, 1)  # gate verdict either way is fine
    after = SQLiteStore(store_path).list_runs()
    new = [m.run_id for m in after if m.run_id not in before]
    assert new, "expected a new run id"
    return new[0]


@pytest.fixture
def two_runs(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    r1 = _do_run(out)
    r2 = _do_run(out)
    store = SQLiteStore(out / "polygraph.sqlite")
    return store, out, [r1, r2]


# ─── comparability ─────────────────────────────────────────────────────────


def test_comparability_identical_for_same_corpus_same_rubric(two_runs):
    store, _out, (r1, r2) = two_runs
    m1, m2 = store.get_run(r1), store.get_run(r2)
    assert m1.corpus_fingerprint == m2.corpus_fingerprint
    assert m1.rubric_fingerprint is not None
    assert m1.rubric_fingerprint == m2.rubric_fingerprint
    assert comparability(m1, m2) == "identical"


def test_comparability_same_dataset_when_rubric_differs(two_runs):
    store, _out, (r1, r2) = two_runs
    m1, m2 = store.get_run(r1), store.get_run(r2)
    m2 = m2.model_copy(update={"rubric_fingerprint": "deadbeefdeadbeef"})
    assert comparability(m1, m2) == "same_dataset"


def test_comparability_disjoint_when_corpus_differs(two_runs):
    store, _out, (r1, r2) = two_runs
    m1, m2 = store.get_run(r1), store.get_run(r2)
    m2 = m2.model_copy(update={"corpus_fingerprint": "0000111122223333"})
    assert comparability(m1, m2) == "disjoint"


# ─── compare_runs report shape ──────────────────────────────────────────────


def test_compare_runs_full_report_shape(two_runs):
    store, out, run_ids = two_runs
    report = compare_runs(store, run_ids, out)

    # Top-level keys.
    for key in (
        "project", "run_ids", "comparability", "baseline_run_id",
        "category_trends", "case_movements", "regressions", "improvements", "overall",
    ):
        assert key in report, f"missing {key}"

    assert report["comparability"] == "identical"
    assert sorted(report["run_ids"]) == sorted(run_ids)

    # category_trends shape.
    assert report["category_trends"]
    ct = report["category_trends"][0]
    assert {"category", "dimensions", "pass_series"} <= set(ct)
    dim = ct["dimensions"][0]
    assert {"dimension", "series", "slope", "latest_delta"} <= set(dim)
    assert all(len(point) == 2 for point in dim["series"])

    # case_movements shape.
    assert report["case_movements"]
    cm = report["case_movements"][0]
    assert {"case_id", "category", "means", "delta_first_last", "moved"} <= set(cm)

    # 2-run overall carries pairwise wins.
    ov = report["overall"]
    assert {"wins_a", "wins_b", "ties", "by_category", "per_run"} <= set(ov)

    # Fully JSON-serializable.
    json.dumps(report)


def test_identical_runs_are_flat_no_regressions(two_runs):
    store, out, run_ids = two_runs
    report = compare_runs(store, run_ids, out)
    # Deterministic demo adapter => identical scores => nothing crosses the band.
    assert report["regressions"] == []
    assert report["improvements"] == []
    for cm in report["case_movements"]:
        assert cm["moved"] in ("flat", "new")
    # pairwise should be all ties.
    assert report["overall"]["wins_a"] == 0
    assert report["overall"]["wins_b"] == 0


# ─── trend ──────────────────────────────────────────────────────────────────


def test_trend_returns_series_with_slope(two_runs):
    store, out, _run_ids = two_runs
    blocks = trend(store, out_dir=out, window=30)
    assert blocks
    blk = blocks[0]
    assert "category" in blk and "dimensions" in blk
    dim = blk["dimensions"][0]
    assert "series" in dim and len(dim["series"]) >= 2
    # Two real points => a slope is computed (0.0 for identical runs, not None).
    assert dim["slope"] is not None


def test_trend_robust_to_single_run(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _do_run(out)
    store = SQLiteStore(out / "polygraph.sqlite")
    blocks = trend(store, out_dir=out, window=30)
    assert blocks  # one run still yields category blocks
    for blk in blocks:
        for dim in blk["dimensions"]:
            assert len(dim["series"]) == 1
            assert dim["slope"] is None  # <2 points => no slope


def test_trend_empty_when_no_runs(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    store = SQLiteStore(out / "polygraph.sqlite")
    assert trend(store, out_dir=out) == []


# ─── rolling baseline ───────────────────────────────────────────────────────


def test_rolling_baseline_summary_and_diff():
    summaries = [
        {
            "dimensions": ["accuracy", "tone"],
            "category_scores": {
                "support": {"count": 3, "accuracy": 8.0, "tone": 7.0},
            },
        },
        {
            "dimensions": ["accuracy", "tone"],
            "category_scores": {
                "support": {"count": 3, "accuracy": 9.0, "tone": 7.0},
            },
        },
        {
            "dimensions": ["accuracy", "tone"],
            "category_scores": {
                "support": {"count": 3, "accuracy": 7.0, "tone": 7.0},
            },
        },
    ]
    base = rolling_baseline_summary(summaries)
    # median of [8,9,7] = 8.0
    assert base["category_scores"]["support"]["accuracy"] == 8.0
    assert base["category_scores"]["support"]["tone"] == 7.0
    assert base["window"] == 3

    current = {
        "dimensions": ["accuracy", "tone"],
        "category_scores": {"support": {"count": 3, "accuracy": 6.0, "tone": 7.0}},
    }
    diff = diff_baseline(current, base)
    regs = [r for r in diff["regressions"] if r["dimension"] == "accuracy"]
    assert regs and regs[0]["delta"] == pytest.approx(-2.0)


def test_rolling_baseline_empty_window():
    base = rolling_baseline_summary([])
    assert base["category_scores"] == {}
    assert base["window"] == 0


# ─── regressions classification via compare_runs ────────────────────────────


def test_compare_runs_detects_regression_against_baseline(tmp_path):
    """Hand-build two runs where the second drops on one dimension."""
    out = tmp_path / "out"
    out.mkdir()
    store = SQLiteStore(out / "polygraph.sqlite")
    rubric = default_rubric()
    dims = rubric.dimension_names()
    cases = [Case(id="c1", prompt="p1", category="support")]
    store.save_cases("runA", cases)
    store.save_cases("runB", cases)

    # runA: all dims = 9; runB: first dim = 6 (a 3-point regression).
    store.save_score("runA", Score(case_id="c1", dimensions={d: 9 for d in dims}))
    store.save_score("runB", Score(case_id="c1", dimensions={**{d: 9 for d in dims}, dims[0]: 6}))

    from promptpolygraph.models import RunMeta

    fp, rf = "corpusfp00000000", "rubricfp00000000"
    store.save_run(RunMeta(run_id="runA", created_at="2026-01-01T00:00:00+00:00",
                           corpus_fingerprint=fp, rubric_fingerprint=rf, project="p"))
    store.save_run(RunMeta(run_id="runB", created_at="2026-01-02T00:00:00+00:00",
                           corpus_fingerprint=fp, rubric_fingerprint=rf, project="p"))

    # Write summaries to disk so compare_runs reads them.
    for rid, s in (("runA", 9.0), ("runB", 6.0)):
        (out / rid).mkdir(parents=True, exist_ok=True)
        scores = store.get_scores(rid)
        summ = summarize(store.get_cases(rid), [], scores, rubric)
        (out / rid / "summary.json").write_text(json.dumps(summ))

    report = compare_runs(store, ["runB", "runA"], out)  # order shuffled on purpose
    assert report["run_ids"] == ["runA", "runB"]  # chronological
    assert report["baseline_run_id"] == "runA"
    regs = report["regressions"]
    assert any(r["dimension"] == dims[0] and r["severity"] == "fail" for r in regs)
    # case moved down.
    cm = report["case_movements"][0]
    assert cm["moved"] == "down"


# ─── pairwise still works ───────────────────────────────────────────────────


def test_pairwise_still_works():
    cases = [Case(id="x", prompt="p", category="c")]
    a = [Score(case_id="x", dimensions={"d": 9})]
    b = [Score(case_id="x", dimensions={"d": 5})]
    pw = pairwise(cases, a, b)
    assert pw["wins_a"] == 1 and pw["wins_b"] == 0 and pw["ties"] == 0


# ─── CLI smoke ──────────────────────────────────────────────────────────────


def test_cli_compare_runs_and_trend_and_regressions(two_runs):
    store, out, run_ids = two_runs
    # N-run compare.
    rc = main(["compare", "--out-dir", str(out), "--runs", ",".join(run_ids)])
    assert rc == 0
    latest = sorted(run_ids, key=lambda r: store.get_run(r).created_at)[-1]
    matches = list((out / latest).glob("comparison_*.json"))
    assert matches, "comparison report not written"

    # Back-compat A/B compare.
    rc = main(["compare", "--out-dir", str(out), "--run-a", run_ids[0], "--run-b", run_ids[1]])
    assert rc == 0

    # trend.
    rc = main(["trend", "--out-dir", str(out)])
    assert rc == 0 and (out / "trend.json").exists()

    # regressions vs an explicit baseline.
    rc = main(["regressions", "--out-dir", str(out), "--run", run_ids[1], "--against", run_ids[0]])
    assert rc == 0

    # regressions vs a rolling window.
    rc = main(["regressions", "--out-dir", str(out), "--run", run_ids[1], "--against", "rolling:5"])
    assert rc == 0
