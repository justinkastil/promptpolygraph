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
        msg = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # The Messages API can return an empty content array or non-text blocks
        # in rare cases; never index [0] blindly.
        if not msg.content:
            return ""
        for block in msg.content:
            text = getattr(block, "text", None)
            if text is not None:
                return text
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


def make_client(model: str | None = None) -> LLMClient:
    """Construct the default (Anthropic) client."""
    return AnthropicClient(model=model)


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
