"""Adapters that wrap a pipeline built with a third-party orchestration
framework, so an existing chain / query engine / program can be evaluated
without rewriting it as a plain callable.

Three thin wrappers are shipped:

  LangChainAdapter   wraps a Runnable/Chain, calling `.ainvoke` (or `.invoke`)
  LlamaIndexAdapter  wraps a query engine, calling `.aquery` (or `.query`)
  DSPyAdapter        wraps a compiled program callable, calling it directly

Each takes a live, already-constructed framework object via the `target`
option and turns the case prompt into one invocation. The framework itself is
imported lazily and only to confirm the optional extra is installed; the object
is used by duck typing, so a fake exposing the same surface works in tests and
no framework is required at import time. Install with::

    pip install 'promptpolygraph[frameworks]'

These wrappers do not configure prompts, retrievers, or tools: that is the
pipeline's job. They normalize whatever the pipeline returns into response text.
"""

from __future__ import annotations

import inspect
import time
from typing import Any

from ..models import Case, Response
from .base import BaseAdapter


def _require(module: str, extra: str = "frameworks") -> None:
    """Confirm an optional framework is importable, raising a directed install
    hint otherwise. The imported module is discarded: adapters use the passed
    object by duck typing, so this is only a presence check."""
    import importlib

    try:
        importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(
            f"{module!r} is not installed. Install the optional extra: "
            f"pip install 'promptpolygraph[{extra}]'"
        ) from exc


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _coerce_text(result: Any) -> str:
    """Reduce a framework's return value to response text.

    Frameworks return heterogeneous shapes: a bare string, a message object
    with `.content`, a LlamaIndex response with `.response`, or a dict keyed by
    a common output field. Prefer the most specific attribute, then fall back to
    str()."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    # LangChain chat messages expose `.content`; LlamaIndex responses `.response`.
    for attr in ("content", "response"):
        val = getattr(result, attr, None)
        if isinstance(val, str):
            return val
    if isinstance(result, dict):
        for key in ("output", "result", "text", "answer", "response", "output_text"):
            val = result.get(key)
            if isinstance(val, str):
                return val
    return str(result)


class _FrameworkAdapter(BaseAdapter):
    """Shared scaffolding: hold a target object and call a preferred async
    method, falling back to a sync method, then normalize the result.

    Subclasses set `_module` (the extra-gating import) and the async/sync method
    names to probe. The target is supplied via the `target` (or `chain` /
    `engine` / `program`) option as a live object.
    """

    _module: str = ""
    _async_method: str = ""
    _sync_method: str = ""

    def __init__(self, name: str | None = None, *, target: Any = None, **_: Any):
        super().__init__(name)
        if target is None:
            raise ValueError(f"{type(self).__name__} requires a `target` object")
        _require(self._module)
        self._target = target

    def _resolve_call(self) -> tuple[Any, bool]:
        """Return the bound method to invoke and whether it is the async variant.
        Prefer the async method when present so an async pipeline is not run on a
        blocking call."""
        fn = getattr(self._target, self._async_method, None)
        if callable(fn):
            return fn, True
        fn = getattr(self._target, self._sync_method, None)
        if callable(fn):
            return fn, False
        raise AttributeError(
            f"target has neither {self._async_method!r} nor {self._sync_method!r}"
        )

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        try:
            fn, is_async = self._resolve_call()
            result = fn(case.prompt)
            if is_async:
                result = await result
            else:
                # A sync method may still hand back an awaitable; tolerate it.
                result = await _maybe_await(result)
            text = _coerce_text(result)
        except Exception as exc:  # surface target errors as a Response, not a crash
            return Response(
                case_id=case.id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(start),
                source=self.name,
            )
        return Response(
            case_id=case.id,
            text=text,
            latency_ms=self._elapsed_ms(start),
            source=self.name,
        )


class LangChainAdapter(_FrameworkAdapter):
    """Wrap a LangChain Runnable/Chain. Calls `ainvoke`, else `invoke`."""

    name = "langchain"
    _module = "langchain_core"
    _async_method = "ainvoke"
    _sync_method = "invoke"

    def __init__(self, name: str | None = None, *, target: Any = None, chain: Any = None, **kw: Any):
        super().__init__(name, target=target if target is not None else chain, **kw)


class LlamaIndexAdapter(_FrameworkAdapter):
    """Wrap a LlamaIndex query engine. Calls `aquery`, else `query`."""

    name = "llamaindex"
    _module = "llama_index.core"
    _async_method = "aquery"
    _sync_method = "query"

    def __init__(self, name: str | None = None, *, target: Any = None, engine: Any = None, **kw: Any):
        super().__init__(name, target=target if target is not None else engine, **kw)


class DSPyAdapter(BaseAdapter):
    """Wrap a DSPy program. A compiled program is itself callable
    (`program(question=...)`), so this calls the object directly rather than a
    named method. The result is typically a Prediction; its first string-valued
    field is used, else str().
    """

    name = "dspy"

    def __init__(
        self,
        name: str | None = None,
        *,
        target: Any = None,
        program: Any = None,
        input_field: str = "question",
        **_: Any,
    ):
        super().__init__(name)
        prog = target if target is not None else program
        if prog is None:
            raise ValueError("DSPyAdapter requires a `target` program callable")
        if not callable(prog):
            raise TypeError("DSPyAdapter `target` must be callable")
        _require("dspy")
        self._program = prog
        self._input_field = input_field

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        try:
            result = self._program(**{self._input_field: case.prompt})
            result = await _maybe_await(result)
            text = self._coerce_prediction(result)
        except Exception as exc:
            return Response(
                case_id=case.id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(start),
                source=self.name,
            )
        return Response(
            case_id=case.id,
            text=text,
            latency_ms=self._elapsed_ms(start),
            source=self.name,
        )

    @staticmethod
    def _coerce_prediction(result: Any) -> str:
        """Extract text from a DSPy Prediction. Common output fields are tried
        first; a Prediction without one falls back to str()."""
        if isinstance(result, str):
            return result
        for attr in ("answer", "output", "response", "text"):
            val = getattr(result, attr, None)
            if isinstance(val, str):
                return val
        return _coerce_text(result)
