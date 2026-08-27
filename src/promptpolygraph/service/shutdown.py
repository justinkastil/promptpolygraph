"""Process-wide drain state shared by readiness and workers."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_draining = False
_active = 0
_started_at: float | None = None


def begin_drain() -> dict[str, Any]:
    global _draining, _started_at
    with _lock:
        if not _draining:
            _draining = True
            _started_at = time.monotonic()
    return summary()


def is_draining() -> bool:
    with _lock:
        return _draining


def job_started() -> None:
    global _active
    with _lock:
        _active += 1


def job_finished() -> None:
    global _active
    with _lock:
        _active = max(0, _active - 1)


def wait(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout)
    while summary()["active_jobs"] and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    return summary()


def end_drain() -> None:
    """Reset process state after an application lifespan has fully stopped."""
    global _draining, _started_at
    with _lock:
        _draining = False
        _started_at = None


def summary() -> dict[str, Any]:
    with _lock:
        return {
            "draining": _draining,
            "active_jobs": _active,
            "elapsed_seconds": round(time.monotonic() - _started_at, 3) if _started_at else 0.0,
        }
