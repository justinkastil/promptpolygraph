"""LLM client abstraction used by the analyzer, audit engine, and generator.

A single tiny async interface (`LLMClient.complete`) decouples every consumer
from the Anthropic SDK. `AnthropicClient` is the real backend; `ScriptedClient`
returns queued strings for tests. Offline/mock behavior lives in each consumer
(deterministic heuristics), not here — so the client stays a thin transport.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable

DEFAULT_MODEL = os.environ.get("POLYGRAPH_MODEL", "claude-opus-4-8")

# Models that removed the sampling parameters (temperature/top_p/top_k):
# sending any of them returns a 400. Covers Opus 4.8/4.7 and Fable 5 / Mythos 5.
# Opus 4.6 / Sonnet 4.6 / Haiku 4.5 still accept temperature.
_NO_SAMPLING_PARAMS = ("opus-4-8", "opus-4-7", "fable-5", "mythos-5")


def _accepts_sampling_params(model: str) -> bool:
    m = (model or "").lower()
    return not any(tag in m for tag in _NO_SAMPLING_PARAMS)


@runtime_checkable
class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        ...


class AnthropicClient:
    """Async Anthropic-backed client with defensive content extraction."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic  # imported lazily so the package imports without a key

        self.model = model or DEFAULT_MODEL
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Only pass temperature to models that still accept sampling params;
        # Opus 4.8/4.7 and Fable 5 reject it with a 400.
        if _accepts_sampling_params(self.model):
            kwargs["temperature"] = temperature
        msg = await self._client.messages.create(**kwargs)
        # The Messages API can return an empty content array or non-text blocks
        # in rare cases; never index [0] blindly.
        if not msg.content:
            return ""
        for block in msg.content:
            text = getattr(block, "text", None)
            if text is not None:
                return text
        return ""


class OpenAICompatibleClient:
    """Chat client for any OpenAI-compatible endpoint — OpenAI, Ollama, vLLM,
    LM Studio, etc. Uses httpx (a core dep), so the judge/audit/generation
    backend runs against a local model with no extra packages and no API key
    (Ollama needs none). On any transport/parse error it returns "" so a flaky
    local server degrades gracefully instead of crashing a run."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        import httpx

        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            resp = await self._client.post(self._url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return ""
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""


class LiteLLMClient:
    """Universal catch-all backend routing through litellm.completion().

    Reaches providers without a first-class path here (Bedrock, Vertex AI, Azure
    OpenAI, Gemini, Cohere, and ~100 others). litellm is an optional dependency
    [litellm extra]; the import is deferred so a bare install never breaks. Per-
    cloud auth is via that cloud's own env vars (see docs/PROVIDERS.md); litellm
    reads them directly. The model string carries the provider prefix litellm
    expects (e.g. "bedrock/anthropic.claude-3-sonnet", "vertex_ai/gemini-1.5-pro").
    """

    def __init__(self, model: str, *, api_key: str | None = None):
        try:
            import litellm  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "litellm is required for this provider; install with "
                "'pip install promptpolygraph[litellm]'"
            ) from exc

        self.model = model
        self._api_key = api_key

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        import litellm

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Some models (e.g. Opus 4.8) reject sampling params; gate as elsewhere.
        if _accepts_sampling_params(self.model):
            kwargs["temperature"] = temperature
        if self._api_key:
            kwargs["api_key"] = self._api_key
        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception:
            return ""
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""


class ScriptedClient:
    """Returns queued responses in FIFO order; used by unit tests."""

    model = "scripted"

    def __init__(self, responses: list[str]):
        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append({"system": system, "user": user})
        return self._queue.pop(0) if self._queue else ""


DEFAULT_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DEFAULT_OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Provider aliases that speak the OpenAI-compatible chat protocol.
_OPENAI_COMPAT = {"openai", "openai-compatible", "compatible", "ollama", "vllm", "lmstudio", "local"}
# Providers that run locally and therefore need no API key.
_LOCAL_PROVIDERS = {"ollama", "vllm", "lmstudio", "local"}
# Cloud providers routed through LiteLLM. "litellm" is the explicit catch-all;
# the named aliases route through it too (each authenticates via its own cloud
# env vars — see docs/PROVIDERS.md). Maps an alias to the litellm model prefix
# prepended when the model string lacks one.
_LITELLM_PREFIXES = {
    "bedrock": "bedrock/",
    "vertex": "vertex_ai/",
    "vertex_ai": "vertex_ai/",
    "azure": "azure/",
    "gemini": "gemini/",
    "cohere": "cohere/",
}
_LITELLM_PROVIDERS = {"litellm"} | set(_LITELLM_PREFIXES)


def provider_needs_key(provider: str | None, api_key_env: str | None = None) -> str | None:
    """Return the env var that must be set for live calls, or None if no key is
    needed (local providers like Ollama). Used to decide mock vs. live."""
    p = (provider or "anthropic").lower()
    if p == "anthropic":
        return api_key_env or "ANTHROPIC_API_KEY"
    if p in _LOCAL_PROVIDERS:
        return None
    if p in _OPENAI_COMPAT:
        return api_key_env or "OPENAI_API_KEY"
    # LiteLLM-routed clouds authenticate via cloud-native env vars (AWS_*,
    # GOOGLE_*, AZURE_*, GEMINI_API_KEY, COHERE_API_KEY) read by litellm itself,
    # not a single POLYGRAPH-managed key. Return the explicit override if given,
    # else None so the caller does not gate live calls on a key we cannot name.
    if p in _LITELLM_PROVIDERS:
        return api_key_env
    return None


def make_client(
    model: str | None = None,
    *,
    provider: str = "anthropic",
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> LLMClient:
    """Construct the grader/audit/generation client for the configured backend.

    provider: anthropic (default) | openai | ollama | openai-compatible | vllm |
    lmstudio | litellm | bedrock | vertex/vertex_ai | azure | gemini | cohere.
    For OpenAI-compatible providers, `base_url` defaults to the Ollama local
    endpoint for `ollama`, else the OpenAI endpoint; the key (if any) is read
    from `api_key_env` or OPENAI_API_KEY. The litellm/cloud aliases route through
    litellm.completion() and authenticate via cloud-native env vars (see
    docs/PROVIDERS.md). Default behavior (anthropic) is unchanged.
    """
    p = (provider or "anthropic").lower()
    if p == "anthropic":
        key = os.environ.get(api_key_env) if api_key_env else None
        return AnthropicClient(model=model, api_key=key)
    if p in _LITELLM_PROVIDERS:
        # Prepend the litellm provider prefix for the named aliases unless the
        # caller already supplied a prefixed model string. Bare "litellm" passes
        # the model through verbatim (caller owns the prefix).
        m = model or ""
        prefix = _LITELLM_PREFIXES.get(p)
        if prefix and m and "/" not in m:
            m = prefix + m
        key = os.environ.get(api_key_env) if api_key_env else None
        return LiteLLMClient(m, api_key=key)
    if p in _OPENAI_COMPAT:
        if base_url:
            bu = base_url
        elif p in _LOCAL_PROVIDERS:
            bu = DEFAULT_OLLAMA_BASE_URL
        else:
            bu = DEFAULT_OPENAI_BASE_URL
        key_env = api_key_env or "OPENAI_API_KEY"
        return OpenAICompatibleClient(
            model or "gpt-4o-mini", base_url=bu, api_key=os.environ.get(key_env)
        )
    raise ValueError(f"unknown llm provider: {provider!r}")


def extract_json(text: str) -> Any:
    """Parse a JSON object out of an LLM response, tolerating code fences.

    Raises json.JSONDecodeError on unrecoverable input — callers decide how to
    degrade (the analyzer, for example, persists a structured failure record).
    """
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text and text.count("```") >= 2:
        text = text.split("```", 2)[1]
        # strip an optional leading language tag line
        if "\n" in text:
            first, rest = text.split("\n", 1)
            if first.strip().isalpha():
                text = rest
    return json.loads(text.strip())
