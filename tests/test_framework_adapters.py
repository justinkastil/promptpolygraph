"""Framework-adapter tests.

The real frameworks are not installed. To exercise the wrappers, a stub module
is registered under the import name each adapter gates on, then a fake pipeline
object (matching the framework's call surface by duck typing) is wrapped. The
missing-extra path is verified by removing those modules so the import fails.
"""

from __future__ import annotations

import sys
import types

import pytest

from promptpolygraph.adapters import (
    DSPyAdapter,
    LangChainAdapter,
    LlamaIndexAdapter,
    build_adapter,
)
from promptpolygraph.config import AdapterConfig
from promptpolygraph.models import Case


def _case(prompt: str = "ping") -> Case:
    return Case(id="c1", prompt=prompt)


@pytest.fixture
def stub_modules(monkeypatch):
    """Register stub modules so each adapter's presence check passes without the
    real framework. Submodule names (e.g. llama_index.core) need their parent
    registered too."""
    for name in ("langchain_core", "llama_index", "llama_index.core", "dspy"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    return monkeypatch


# ─── LangChain ──────────────────────────────────────────────────────────────


class _FakeRunnableSync:
    def invoke(self, prompt):
        return f"sync:{prompt}"


class _FakeRunnableAsync:
    async def ainvoke(self, prompt):
        # A LangChain chat step typically yields a message with `.content`.
        return types.SimpleNamespace(content=f"async:{prompt}")


async def test_langchain_sync_invoke(stub_modules):
    adapter = LangChainAdapter(target=_FakeRunnableSync())
    resp = await adapter.query(_case("hello"))
    assert resp.error is None
    assert resp.text == "sync:hello"
    assert resp.source == "langchain"


async def test_langchain_prefers_async_and_extracts_content(stub_modules):
    adapter = LangChainAdapter(target=_FakeRunnableAsync())
    resp = await adapter.query(_case("hi"))
    assert resp.text == "async:hi"


async def test_langchain_via_chain_kwarg(stub_modules):
    adapter = LangChainAdapter(chain=_FakeRunnableSync())
    resp = await adapter.query(_case("x"))
    assert resp.text == "sync:x"


# ─── LlamaIndex ─────────────────────────────────────────────────────────────


class _FakeQueryEngineSync:
    def query(self, prompt):
        # LlamaIndex responses expose `.response`.
        return types.SimpleNamespace(response=f"answer:{prompt}")


class _FakeQueryEngineAsync:
    async def aquery(self, prompt):
        return types.SimpleNamespace(response=f"a-answer:{prompt}")


async def test_llamaindex_sync_query(stub_modules):
    adapter = LlamaIndexAdapter(target=_FakeQueryEngineSync())
    resp = await adapter.query(_case("q"))
    assert resp.text == "answer:q"
    assert resp.source == "llamaindex"


async def test_llamaindex_prefers_async(stub_modules):
    adapter = LlamaIndexAdapter(engine=_FakeQueryEngineAsync())
    resp = await adapter.query(_case("q2"))
    assert resp.text == "a-answer:q2"


# ─── DSPy ───────────────────────────────────────────────────────────────────


class _FakeProgram:
    def __call__(self, question):
        return types.SimpleNamespace(answer=f"pred:{question}")


async def test_dspy_program_callable(stub_modules):
    adapter = DSPyAdapter(target=_FakeProgram())
    resp = await adapter.query(_case("why"))
    assert resp.text == "pred:why"
    assert resp.source == "dspy"


async def test_dspy_custom_input_field(stub_modules):
    captured = {}

    def prog(prompt):
        captured["prompt"] = prompt
        return "ok"

    adapter = DSPyAdapter(program=prog, input_field="prompt")
    resp = await adapter.query(_case("payload"))
    assert captured["prompt"] == "payload"
    assert resp.text == "ok"


# ─── Error surfacing ────────────────────────────────────────────────────────


async def test_target_exception_becomes_response_error(stub_modules):
    class _Boom:
        def invoke(self, prompt):
            raise RuntimeError("downstream failed")

    adapter = LangChainAdapter(target=_Boom())
    resp = await adapter.query(_case())
    assert resp.text == ""
    assert resp.error is not None
    assert "downstream failed" in resp.error


# ─── Missing extra ──────────────────────────────────────────────────────────


def test_langchain_missing_framework_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "langchain_core", None)  # force ImportError
    with pytest.raises(ImportError) as exc:
        LangChainAdapter(target=_FakeRunnableSync())
    assert "frameworks" in str(exc.value)


def test_llamaindex_missing_framework_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_index.core", None)
    with pytest.raises(ImportError) as exc:
        LlamaIndexAdapter(target=_FakeQueryEngineSync())
    assert "frameworks" in str(exc.value)


def test_dspy_missing_framework_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "dspy", None)
    with pytest.raises(ImportError) as exc:
        DSPyAdapter(target=_FakeProgram())
    assert "frameworks" in str(exc.value)


# ─── Construction guards ────────────────────────────────────────────────────


def test_langchain_requires_target(stub_modules):
    with pytest.raises(ValueError):
        LangChainAdapter()


def test_dspy_requires_callable(stub_modules):
    with pytest.raises(TypeError):
        DSPyAdapter(target=object())


# ─── build_adapter wiring ───────────────────────────────────────────────────


async def test_build_adapter_resolves_framework_types(stub_modules):
    cfg = AdapterConfig(type="langchain", name="lc")
    adapter = build_adapter(cfg, target=_FakeRunnableSync())
    resp = await adapter.query(_case("built"))
    assert resp.text == "sync:built"
    assert adapter.name == "lc"
