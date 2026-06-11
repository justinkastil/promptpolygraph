from __future__ import annotations

import httpx
import pytest

from promptpolygraph import llm
from promptpolygraph.config import Config
from promptpolygraph.llm import OpenAICompatibleClient, make_client, provider_needs_key


def test_make_client_provider_selection():
    a = make_client("claude-x", provider="anthropic")
    assert type(a).__name__ == "AnthropicClient" and a.model == "claude-x"
    o = make_client("llama3.1", provider="ollama")
    assert isinstance(o, OpenAICompatibleClient) and o.model == "llama3.1"
    assert "11434" in o._url  # default Ollama endpoint
    c = make_client("gpt-4o-mini", provider="openai", base_url="https://x.test/v1")
    assert isinstance(c, OpenAICompatibleClient) and c._url == "https://x.test/v1/chat/completions"


def test_provider_needs_key():
    assert provider_needs_key("anthropic") == "ANTHROPIC_API_KEY"
    assert provider_needs_key("ollama") is None          # local -> no key
    assert provider_needs_key("openai") == "OPENAI_API_KEY"
    assert provider_needs_key("openai", "MY_KEY") == "MY_KEY"


def test_mock_detection_is_provider_aware(monkeypatch):
    from promptpolygraph.cli import _is_mock

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # anthropic, no key -> mock
    assert _is_mock(Config()) is True
    # ollama, no key -> NOT mock (runs live against the local server)
    assert _is_mock(Config(llm={"provider": "ollama"})) is False
    # explicit mock always wins
    assert _is_mock(Config(llm={"provider": "ollama"}, mock=True)) is True


async def test_openai_compatible_complete_parses_choices():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "llama3.1" in body and "hello" in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "world"}}]})

    client = OpenAICompatibleClient("llama3.1", base_url="http://localhost:11434/v1")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await client.complete(system="be brief", user="hello")
    assert out == "world"


async def test_openai_compatible_degrades_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = OpenAICompatibleClient("m", base_url="http://x/v1")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await client.complete(system="", user="x") == ""  # never raises into the run
