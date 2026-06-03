"""Adapter protocol + a small base class with timing helpers."""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from ..models import Case, Response


@runtime_checkable
class Adapter(Protocol):
    name: str

    async def query(self, case: Case) -> Response:
        """Send the case prompt to the target and return a Response."""
        ...

    async def aclose(self) -> None:
        ...


class BaseAdapter:
    """Common scaffolding: name, no-op close, and a timed-response helper."""

    name: str = "adapter"

    def __init__(self, name: str | None = None):
        if name:
            self.name = name

    async def query(self, case: Case) -> Response:  # pragma: no cover - abstract
        raise NotImplementedError

    async def aclose(self) -> None:
        return None

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.perf_counter() - start) * 1000)
