"""The in-process async runner.

Fans `Case`s out through an `Adapter` under a concurrency cap, with per-case
timeout, retry-with-backoff, optional requests-per-second rate limiting,
response caching, and resume (skip cases already answered in this run). For
network-reachable targets there is no distributed work queue to coordinate:
just an asyncio semaphore in one process.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..adapters.base import Adapter
from ..models import Case, Response
from .store import SQLiteStore, Store, cache_key


@dataclass
class RunnerOptions:
    concurrency: int = 20
    rps: float | None = None
    timeout_s: float = 60.0
    retries: int = 2
    resume: bool = True
    use_cache: bool = True


@dataclass
class _RateLimiter:
    """Simple async token-ish gate: at most one release per `interval`."""

    rps: float | None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _next: float = 0.0

    async def wait(self) -> None:
        if not self.rps or self.rps <= 0:
            return
        interval = 1.0 / self.rps
        async with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next - now)
            self._next = max(now, self._next) + interval
        if sleep_for:
            await asyncio.sleep(sleep_for)


class Runner:
    def __init__(
        self,
        adapter: Adapter,
        store: Store,
        run_id: str,
        options: RunnerOptions | None = None,
        adapter_sig: dict | None = None,
        on_done: Optional[Callable[[Response], None]] = None,
    ):
        self.adapter = adapter
        self.store = store
        self.run_id = run_id
        self.opts = options or RunnerOptions()
        self.adapter_sig = adapter_sig
        self.on_done = on_done
        self._sem = asyncio.Semaphore(self.opts.concurrency)
        self._limiter = _RateLimiter(self.opts.rps)

    async def run(self, cases: list[Case]) -> list[Response]:
        done_ids: set[str] = set()
        if self.opts.resume:
            done_ids = {r.case_id for r in self.store.get_responses(self.run_id) if not r.error}
        pending = [c for c in cases if c.id not in done_ids]
        results = await asyncio.gather(*(self._one(c) for c in pending))
        # include previously-completed responses so callers see the full set
        existing = [r for r in self.store.get_responses(self.run_id) if r.case_id in done_ids]
        return existing + [r for r in results if r is not None]

    async def _one(self, case: Case) -> Response:
        async with self._sem:
            key = cache_key(self.adapter.name, self.adapter_sig, case.prompt)
            if self.opts.use_cache:
                cached = await asyncio.to_thread(self.store.cache_get, key)
                if cached is not None and not cached.error:
                    resp = cached.model_copy(update={"case_id": case.id})
                    await self._persist(resp)
                    return resp

            await self._limiter.wait()
            resp = await self._attempt(case)

            if self.opts.use_cache and not resp.error:
                await asyncio.to_thread(self.store.cache_put, key, resp)
            await self._persist(resp)
            return resp

    async def _attempt(self, case: Case) -> Response:
        last: Response | None = None
        for attempt in range(self.opts.retries + 1):
            try:
                resp = await asyncio.wait_for(
                    self.adapter.query(case), timeout=self.opts.timeout_s
                )
            except asyncio.TimeoutError:
                resp = Response(
                    case_id=case.id,
                    error=f"timeout after {self.opts.timeout_s}s",
                    source=self.adapter.name,
                )
            except Exception as exc:
                resp = Response(
                    case_id=case.id,
                    error=f"{type(exc).__name__}: {exc}",
                    source=self.adapter.name,
                )
            if not resp.error:
                return resp
            last = resp
            if attempt < self.opts.retries:
                await asyncio.sleep(min(2.0 ** attempt, 8.0))
        return last or Response(case_id=case.id, error="unknown failure", source=self.adapter.name)

    async def _persist(self, resp: Response) -> None:
        await asyncio.to_thread(self.store.save_response, self.run_id, resp)
        if self.on_done:
            self.on_done(resp)


async def run_corpus(
    adapter: Adapter,
    store: Store,
    run_id: str,
    cases: list[Case],
    options: RunnerOptions | None = None,
    adapter_sig: dict | None = None,
) -> list[Response]:
    """Convenience wrapper: run a corpus and close the adapter afterward."""
    runner = Runner(adapter, store, run_id, options, adapter_sig)
    try:
        return await runner.run(cases)
    finally:
        await adapter.aclose()
