"""Adapters — the single integration point per system under test.

An adapter takes a `Case` and returns a `Response`. Ship three: `HTTPAdapter`
(any REST endpoint), `LLMAdapter` (OpenAI / Anthropic / OpenAI-compatible chat),
and `CallableAdapter` (an in-process Python callable, used for tests and
library embedding). Custom targets implement the same `query` coroutine.
"""

from __future__ import annotations

from typing import Any

from ..config import AdapterConfig
from .agentic import AgentAdapter, make_agent_adapter
from .base import Adapter, BaseAdapter
from .callable import CallableAdapter
from .demo import DemoAdapter
from .frameworks import DSPyAdapter, LangChainAdapter, LlamaIndexAdapter
from .http import HTTPAdapter
from .llm import LLMAdapter
from .rag import RagAdapter, make_rag_adapter

__all__ = [
    "Adapter",
    "AgentAdapter",
    "BaseAdapter",
    "CallableAdapter",
    "DemoAdapter",
    "DSPyAdapter",
    "HTTPAdapter",
    "LangChainAdapter",
    "LlamaIndexAdapter",
    "LLMAdapter",
    "RagAdapter",
    "build_adapter",
]


def _resolve_callable(ref: str) -> Any:
    """Import a callable from a 'module:function' (or 'module.function') string,
    so a custom in-process adapter can be configured from a config file / the UI
    without code changes. The function may take `case` or a plain prompt str."""
    import importlib

    mod_name, _, attr = ref.replace(":", ".").rpartition(".")
    if not mod_name:
        raise ValueError(f"callable adapter ref must be 'module:function', got {ref!r}")
    return getattr(importlib.import_module(mod_name), attr)


def _plugin_adapters() -> dict[str, Any]:
    """Adapter types contributed by installed third-party plugins.

    Built-in types take precedence (resolved before this is consulted), so a
    plugin cannot shadow `http`/`llm`/`demo`/`callable`.
    """
    from ..plugins import GROUP_ADAPTERS, load_plugins

    return load_plugins(GROUP_ADAPTERS)


def build_adapter(cfg: AdapterConfig, **extra: Any) -> Adapter:
    """Construct an adapter from config. `extra` lets callers inject a callable.

    Resolution order: built-in types first, then any adapter type registered by
    an installed plugin under the `promptpolygraph.adapters` entry-point group.
    A plugin entry point loads to a factory/class called `(name=..., **options)`.
    """
    options = {**cfg.options, **extra}
    kind = cfg.type.lower()
    if kind == "http":
        return HTTPAdapter(name=cfg.name or "http", **options)
    if kind == "llm":
        return LLMAdapter(name=cfg.name or "llm", **options)
    if kind == "demo":
        return DemoAdapter(name=cfg.name or "demo", **options)
    if kind == "callable":
        # Accept a live `fn`, or an import string under fn/import/target/ref.
        fn = options.pop("fn", None)
        ref = options.pop("import", None) or options.pop("target", None) or options.pop("ref", None)
        if fn is None and isinstance(ref, str) and ref.strip():
            fn = _resolve_callable(ref.strip())
        return CallableAdapter(name=cfg.name or "callable", fn=fn, **options)
    if kind == "langchain":
        return LangChainAdapter(name=cfg.name or "langchain", **options)
    if kind == "llamaindex":
        return LlamaIndexAdapter(name=cfg.name or "llamaindex", **options)
    if kind == "dspy":
        return DSPyAdapter(name=cfg.name or "dspy", **options)
    if kind == "agent":
        # A live agent callable under fn/import/target/ref, else a mock tool agent.
        fn = options.pop("fn", None)
        ref = options.pop("import", None) or options.pop("target", None) or options.pop("ref", None)
        if fn is None and isinstance(ref, str) and ref.strip():
            fn = _resolve_callable(ref.strip())
        return make_agent_adapter(cfg.name or "agent", fn=fn, **options)
    if kind == "rag":
        # A live retrieve-then-generate callable, else a mock RAG target.
        fn = options.pop("fn", None)
        ref = options.pop("import", None) or options.pop("target", None) or options.pop("ref", None)
        if fn is None and isinstance(ref, str) and ref.strip():
            fn = _resolve_callable(ref.strip())
        return make_rag_adapter(cfg.name or "rag", fn=fn, **options)
    factory = _plugin_adapters().get(kind)
    if factory is not None:
        return factory(name=cfg.name or kind, **options)
    raise ValueError(f"unknown adapter type: {cfg.type!r}")
