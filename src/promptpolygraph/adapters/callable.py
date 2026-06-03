"""In-process callable adapter — for tests, library embedding, and offline smoke.

Wrap any function `fn(prompt: str) -> str` (sync or async), or a richer
`fn(case: Case) -> str | dict`. A dict may carry {"text", "tokens_in",
"tokens_out", "model", ...} to populate the Response. This is the adapter the
offline end-to-end smoke uses, so the whole pipeline runs with no network.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable

from ..models import Case, Response
from .base import BaseAdapter

Handler = Callable[..., Any] | Callable[..., Awaitable[Any]]


class CallableAdapter(BaseAdapter):
    name = "callable"

    def __init__(self, name: str | None = None, fn: Handler | None = None, **_: Any):
        super().__init__(name)
        if fn is None:
            raise ValueError("CallableAdapter requires a `fn` callable")
        self._fn = fn
        self._wants_case = "case" in inspect.signature(fn).parameters

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        arg = case if self._wants_case else case.prompt
        try:
            result = self._fn(arg)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # surface target errors as a Response, not a crash
            return Response(
                case_id=case.id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(start),
                source=self.name,
            )
        latency = self._elapsed_ms(start)
        if isinstance(result, dict):
            return Response(
                case_id=case.id,
                text=str(result.get("text", "")),
                latency_ms=result.get("latency_ms", latency),
                tokens_in=result.get("tokens_in"),
                tokens_out=result.get("tokens_out"),
                cost_usd=result.get("cost_usd"),
                model=result.get("model"),
                source=self.name,
                raw=result,
            )
        return Response(
            case_id=case.id,
            text=str(result),
            latency_ms=latency,
            source=self.name,
        )
