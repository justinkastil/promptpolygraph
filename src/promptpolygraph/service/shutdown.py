"""Process-wide graceful-drain coordination."""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

_Job = TypeVar("_Job")

_draining = threading.Event()
_condition = threading.Condition()
_active = 0
_started_at: float | None = None


def begin_drain() -> None:
    global _started_at
    with _condition:
        if not _draining.is_set():
            _started_at = time.monotonic()
        _draining.set()
        _condition.notify_all()


def is_draining() -> bool:
    return _draining.is_set()


def job_started() -> None:
    global _active
    with _condition:
        _active += 1


def claim_unless_draining(claim: Callable[[], _Job | None]) -> _Job | None:
    """Atomically gate claiming against drain start and register claimed work."""
    global _active
    with _condition:
        if _draining.is_set():
            return None
        job = claim()
        if job is not None:
            _active += 1
        return job


def job_finished() -> None:
    global _active
    with _condition:
        _active = max(0, _active - 1)
        _condition.notify_all()


def wait(timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    with _condition:
        while _active:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _condition.wait(remaining)
        return True


def summary() -> dict[str, float | int | bool]:
    with _condition:
        elapsed = max(0.0, time.monotonic() - _started_at) if _started_at is not None else 0.0
        return {"draining": is_draining(), "running_jobs": _active, "elapsed_seconds": elapsed}


def _reset_for_tests() -> None:
    global _active, _started_at
    with _condition:
        _draining.clear()
        _active = 0
        _started_at = None
