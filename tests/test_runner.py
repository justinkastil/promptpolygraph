from __future__ import annotations

import asyncio

import pytest

from promptpolygraph.adapters import CallableAdapter
from promptpolygraph.models import Case, RunMeta
from promptpolygraph.runner import Runner
from promptpolygraph.runner.runner import RunnerOptions


def _mk_cases(n: int) -> list[Case]:
    return [Case(prompt=f"q{i}", category=f"c{i % 3}") for i in range(n)]


async def test_runs_all_cases_concurrently(store):
    meta = RunMeta(adapter="callable")
    store.save_run(meta)
    cases = _mk_cases(30)
    adapter = CallableAdapter(fn=lambda p: f"echo:{p}")
    runner = Runner(adapter, store, meta.run_id, RunnerOptions(concurrency=8, use_cache=False))
    resps = await runner.run(cases)
    assert len(resps) == 30
    assert all(r.text.startswith("echo:q") for r in resps)
    assert all(r.latency_ms is not None for r in resps)


async def test_retry_then_success(store):
    meta = RunMeta(adapter="callable")
    store.save_run(meta)
    state = {"n": 0}

    def flaky(prompt: str) -> str:
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("boom")
        return "ok"

    adapter = CallableAdapter(fn=flaky)
    runner = Runner(adapter, store, meta.run_id, RunnerOptions(retries=3, use_cache=False))
    resps = await runner.run([Case(prompt="x")])
    assert resps[0].error is None
    assert resps[0].text == "ok"


async def test_resume_skips_completed(store):
    meta = RunMeta(adapter="callable")
    store.save_run(meta)
    cases = _mk_cases(10)
    calls = {"n": 0}

    def bot(prompt: str) -> str:
        calls["n"] += 1
        return "r"

    adapter = CallableAdapter(fn=bot)
    runner = Runner(adapter, store, meta.run_id, RunnerOptions(resume=True, use_cache=False))
    await runner.run(cases)
    first = calls["n"]
    await runner.run(cases)  # second pass should not re-query
    assert calls["n"] == first == 10


async def test_cache_avoids_requery(store):
    meta_a = RunMeta(adapter="callable")
    meta_b = RunMeta(adapter="callable")
    store.save_run(meta_a)
    store.save_run(meta_b)
    calls = {"n": 0}

    def bot(prompt: str) -> str:
        calls["n"] += 1
        return "r"

    cases = _mk_cases(5)
    a = CallableAdapter(fn=bot)
    await Runner(a, store, meta_a.run_id, RunnerOptions(use_cache=True)).run(cases)
    b = CallableAdapter(fn=bot)
    await Runner(b, store, meta_b.run_id, RunnerOptions(use_cache=True)).run(cases)
    assert calls["n"] == 5  # second run served entirely from cache


async def test_timeout_becomes_error(store):
    meta = RunMeta(adapter="callable")
    store.save_run(meta)

    async def slow(prompt: str) -> str:
        await asyncio.sleep(1.0)
        return "late"

    adapter = CallableAdapter(fn=slow)
    runner = Runner(adapter, store, meta.run_id, RunnerOptions(timeout_s=0.05, retries=0, use_cache=False))
    resps = await runner.run([Case(prompt="x")])
    assert resps[0].error and "timeout" in resps[0].error
