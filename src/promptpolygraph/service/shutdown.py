"""Process-wide graceful-drain coordination."""
from __future__ import annotations
import threading
import time

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


def summary() -> dict:
    with _condition:
        return {"draining": is_draining(), "running_jobs": _active,
                "elapsed_seconds": max(0.0, time.monotonic() - _started_at)
                if _started_at is not None else 0.0}


def _reset_for_tests() -> None:
    global _active, _started_at
    with _condition:
        _draining.clear()
        _active = 0
        _started_at = None
