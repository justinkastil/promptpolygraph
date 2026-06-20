from __future__ import annotations

import sys
import types

import pytest

from promptpolygraph import llm
from promptpolygraph.llm import LiteLLMClient, make_client, provider_needs_key


class _FakeLiteLLM(types.ModuleType):
    """Stand-in for the litellm module. Records the last acompletion kwargs and
    returns a canned OpenAI-shaped response so no network is touched."""

    def __init__(self) -> None:
        super().__init__("litellm")
        self.last_kwargs: dict | None = None

    async def acompletion(self, **kwargs):
        self.last_kwargs = kwargs
        return {"choices": [{"message": {"content": "ok"}}]}


@pytest.fixture
def fake_litellm(monkeypatch):
    fake = _FakeLiteLLM()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def test_litellm_provider_builds_client(fake_litellm):
    c = make_client("bedrock/some-model", provider="litellm")
    assert isinstance(c, LiteLLMClient)
    assert c.model == "bedrock/some-model"  # passed through verbatim


def test_named_aliases_prepend_prefix(fake_litellm):
    assert make_client("gemini-1.5-pro", provider="gemini").model == "gemini/gemini-1.5-pro"
    assert make_client("command-r", provider="cohere").model == "cohere/command-r"
    assert make_client("gpt-4o", provider="vertex_ai").model == "vertex_ai/gpt-4o"
    assert make_client("gpt-4o", provider="vertex").model == "vertex_ai/gpt-4o"
    assert make_client("dep", provider="azure").model == "azure/dep"
    assert make_client("m", provider="bedrock").model == "bedrock/m"


def test_alias_does_not_double_prefix(fake_litellm):
    # A model string that already carries a provider prefix is left alone.
    assert make_client("vertex_ai/gemini-1.5-pro", provider="vertex").model == "vertex_ai/gemini-1.5-pro"


async def test_litellm_complete_builds_request(fake_litellm):
    c = make_client("gemini/gemini-1.5-pro", provider="litellm")
    out = await c.complete(system="be brief", user="hello", max_tokens=64, temperature=0.0)
    assert out == "ok"
    kw = fake_litellm.last_kwargs
    assert kw["model"] == "gemini/gemini-1.5-pro"
    assert kw["max_tokens"] == 64
    assert kw["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]


async def test_litellm_complete_degrades_on_error(fake_litellm, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(fake_litellm, "acompletion", boom)
    c = make_client("gemini/x", provider="litellm")
    assert await c.complete(system="", user="x") == ""  # never raises into the run


def test_litellm_missing_dependency_errors_clearly(monkeypatch):
    # Simulate [litellm] not installed: importing litellm fails.
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(ImportError, match=r"litellm"):
        make_client("bedrock/m", provider="bedrock")


def test_unknown_provider_still_errors_clearly():
    with pytest.raises(ValueError, match="unknown llm provider"):
        make_client("m", provider="definitely-not-real")


def test_provider_needs_key_for_litellm():
    # LiteLLM clouds authenticate via their own env vars, not a single named key.
    assert provider_needs_key("litellm") is None
    assert provider_needs_key("bedrock") is None
    assert provider_needs_key("gemini") is None
    # An explicit override is still honored.
    assert provider_needs_key("vertex_ai", "MY_KEY") == "MY_KEY"


def test_discovery_surfaces_litellm_providers(monkeypatch):
    from promptpolygraph import discovery

    monkeypatch.setattr(discovery, "_litellm_installed", lambda: True)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    provs = discovery.discover_providers(probe_local=False)
    ids = {p["id"] for p in provs}
    assert {"bedrock", "vertex_ai", "azure", "gemini", "cohere"} <= ids
    gemini = next(p for p in provs if p["id"] == "gemini")
    assert gemini["available"] is True  # litellm installed + credential present
