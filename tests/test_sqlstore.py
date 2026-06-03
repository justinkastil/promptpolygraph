"""Tests for the service-layer SqlStore: Store-protocol parity + durable job queue.

Runs entirely offline against a temp sqlite URL. No network, no API key.
"""

from __future__ import annotations

import json

import pytest

from promptpolygraph.models import (
    Case,
    Response,
    RunMeta,
    Score,
)
from promptpolygraph.service.db import SqlStore


@pytest.fixture
def url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'svc.sqlite'}"


@pytest.fixture
def st(url) -> SqlStore:
    s = SqlStore(url)
    yield s
    s.close()


# ─── Store-protocol parity ────────────────────────────────────────────────


def test_save_get_run(st):
    meta = RunMeta(name="r1", adapter="demo", total_cases=3)
    st.save_run(meta)
    got = st.get_run(meta.run_id)
    assert got is not None
    assert got.run_id == meta.run_id
    assert got.name == "r1"
    assert got.adapter == "demo"
    assert got.total_cases == 3
    # missing run -> None
    assert st.get_run("nope") is None
    # upsert (save again updates, does not duplicate)
    meta.completed_cases = 3
    st.save_run(meta)
    assert st.get_run(meta.run_id).completed_cases == 3
    assert len(st.list_runs()) == 1


def test_save_get_cases(st):
    rid = "run-cases"
    items = [
        Case(prompt="hello", category="accuracy"),
        Case(prompt="world", category="safety"),
    ]
    st.save_cases(rid, items)
    got = st.get_cases(rid)
    assert len(got) == 2
    assert {c.prompt for c in got} == {"hello", "world"}
    # re-saving replaces, not appends
    st.save_cases(rid, [Case(prompt="only", category="tone")])
    got2 = st.get_cases(rid)
    assert len(got2) == 1
    assert got2[0].prompt == "only"


def test_save_get_responses(st):
    rid = "run-resp"
    r = Response(case_id="c1", text="answer", latency_ms=42)
    st.save_response(rid, r)
    got = st.get_responses(rid)
    assert len(got) == 1
    assert got[0].case_id == "c1"
    assert got[0].text == "answer"
    # upsert by (run_id, case_id)
    st.save_response(rid, Response(case_id="c1", text="updated"))
    got = st.get_responses(rid)
    assert len(got) == 1
    assert got[0].text == "updated"


def test_save_get_scores(st):
    rid = "run-score"
    sc = Score(case_id="c1", dimensions={"accuracy": 8}, verdict_pass=True)
    st.save_score(rid, sc)
    got = st.get_scores(rid)
    assert len(got) == 1
    assert got[0].dimensions["accuracy"] == 8
    assert got[0].verdict_pass is True
    # upsert
    st.save_score(rid, Score(case_id="c1", dimensions={"accuracy": 3}, verdict_pass=False))
    got = st.get_scores(rid)
    assert len(got) == 1
    assert got[0].verdict_pass is False


def test_cache_put_get(st):
    assert st.cache_get("missing") is None
    st.cache_put("k1", Response(case_id="c1", text="cached"))
    got = st.cache_get("k1")
    assert got is not None
    assert got.text == "cached"
    # overwrite
    st.cache_put("k1", Response(case_id="c1", text="fresh"))
    assert st.cache_get("k1").text == "fresh"


def test_export_jsonl(st, tmp_path):
    rid = "run-export"
    cases = [
        Case(prompt="a", category="accuracy"),
        Case(prompt="b", category="safety"),
    ]
    st.save_cases(rid, cases)
    st.save_response(rid, Response(case_id=cases[0].id, text="ra"))
    st.save_score(rid, Score(case_id=cases[0].id, dimensions={"accuracy": 9}))
    out = tmp_path / "export.jsonl"
    st.export_jsonl(rid, out)
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == len(cases)  # one JSON line per case
    rows = [json.loads(ln) for ln in lines]
    by_prompt = {row["case"]["prompt"]: row for row in rows}
    assert by_prompt["a"]["response"]["text"] == "ra"
    assert by_prompt["a"]["score"]["dimensions"]["accuracy"] == 9
    # case b has no response/score -> nulls
    assert by_prompt["b"]["response"] is None
    assert by_prompt["b"]["score"] is None


# ─── Job queue ────────────────────────────────────────────────────────────


def test_enqueue_returns_ids(st):
    ids = st.enqueue_job({"foo": "bar"})
    assert set(ids) == {"job_id", "run_id"}
    assert ids["job_id"] and ids["run_id"]
    job = st.get_job(ids["job_id"])
    assert job["status"] == "queued"
    assert job["attempts"] == 0
    assert job["run_id"] == ids["run_id"]
    assert json.loads(job["config"]) == {"foo": "bar"}


def test_enqueue_with_explicit_run_id(st):
    ids = st.enqueue_job({"x": 1}, run_id="fixed-run")
    assert ids["run_id"] == "fixed-run"
    assert st.get_job_for_run("fixed-run")["job_id"] == ids["job_id"]


def test_claim_flips_to_running_with_attempts(st):
    ids = st.enqueue_job({"a": 1})
    claimed = st.claim_job()
    assert claimed is not None
    assert claimed["job_id"] == ids["job_id"]
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert claimed["started_at"] is not None
    # draining: nothing left to claim
    assert st.claim_job() is None


def test_claim_highest_priority_first(st):
    low = st.enqueue_job({"n": "low"}, priority=0)
    high = st.enqueue_job({"n": "high"}, priority=10)
    mid = st.enqueue_job({"n": "mid"}, priority=5)
    order = []
    while True:
        j = st.claim_job()
        if not j:
            break
        order.append(j["job_id"])
    assert order == [high["job_id"], mid["job_id"], low["job_id"]]


def test_update_progress(st):
    ids = st.enqueue_job({})
    st.update_job_progress(ids["job_id"], {"stage": "generate", "done": 2})
    job = st.get_job(ids["job_id"])
    assert json.loads(job["progress"]) == {"stage": "generate", "done": 2}


def test_finish_job(st):
    ids = st.enqueue_job({})
    st.claim_job()
    st.finish_job(ids["job_id"], status="done")
    job = st.get_job(ids["job_id"])
    assert job["status"] == "done"
    assert job["finished_at"] is not None
    assert job["error"] is None
    # failed with error
    ids2 = st.enqueue_job({})
    st.claim_job()
    st.finish_job(ids2["job_id"], status="failed", error="boom")
    j2 = st.get_job(ids2["job_id"])
    assert j2["status"] == "failed"
    assert j2["error"] == "boom"


def test_get_job_missing(st):
    assert st.get_job("nope") is None
    assert st.get_job_for_run("nope") is None


def test_list_jobs(st):
    a = st.enqueue_job({})
    b = st.enqueue_job({})
    st.claim_job()  # flips one to running
    all_jobs = st.list_jobs()
    assert {j["job_id"] for j in all_jobs} == {a["job_id"], b["job_id"]}
    queued = st.list_jobs(status="queued")
    assert len(queued) == 1
    running = st.list_jobs(status="running")
    assert len(running) == 1


def test_cancel_only_queued(st):
    ids = st.enqueue_job({})
    assert st.cancel_job(ids["job_id"]) is True
    assert st.get_job(ids["job_id"])["status"] == "canceled"
    # a running job cannot be canceled by cancel_job
    ids2 = st.enqueue_job({})
    st.claim_job()  # -> running
    assert st.cancel_job(ids2["job_id"]) is False
    assert st.get_job(ids2["job_id"])["status"] == "running"
    # canceled jobs are not claimable
    assert st.claim_job() is None


def test_drain_returns_none_when_empty(st):
    assert st.claim_job() is None
