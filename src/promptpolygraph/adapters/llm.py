"""LLM chat adapter — evaluate a model/assistant directly.

Supports Anthropic (via the bundled `anthropic` dep) and any OpenAI-compatible
chat endpoint (OpenAI, Azure, local servers, etc.) via the optional `openai`
extra. The target *is* the model: each case prompt becomes a single user turn
under an optional system prompt.

    adapter:
      type: llm
      options:
        provider: anthropic            # or "openai"
        model: claude-opus-4-8
        system: "You are a helpful customer-support assistant."
        max_tokens: 512
        # base_url: https://...        # openai-compatible servers
        # api_key_env: OPENAI_API_KEY
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..models import Case, Response
from .base import BaseAdapter


class LLMAdapter(BaseAdapter):
    name = "llm"

    def __init__(
        self,
        name: str | None = None,
        *,
        provider: str = "anthropic",
        model: str = "claude-opus-4-8",
        system: str = "",
        max_tokens: int = 512,
        temperature: float = 0.0,
        base_url: str | None = None,
        api_key_env: str | None = None,
        **_: Any,
    ):
        super().__init__(name)
        self._provider = provider.lower()
        self._model = model
        self._system = system
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._base_url = base_url
        self._api_key_env = api_key_env
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._provider == "anthropic":
            import anthropic

            key = os.environ.get(self._api_key_env or "ANTHROPIC_API_KEY")
            self._client = anthropic.AsyncAnthropic(api_key=key)
        elif self._provider in ("openai", "openai-compatible", "compatible"):
            try:
                import openai
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "the LLM adapter's openai provider needs the optional dep: "
                    "pip install 'promptpolygraph[llm]'"
                ) from exc
            key = os.environ.get(self._api_key_env or "OPENAI_API_KEY")
            self._client = openai.AsyncOpenAI(api_key=key, base_url=self._base_url)
        else:
            raise ValueError(f"unknown llm provider: {self._provider!r}")
        return self._client

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        try:
            if self._provider == "anthropic":
                text, tin, tout = await self._anthropic(case.prompt)
            else:
                text, tin, tout = await self._openai(case.prompt)
        except Exception as exc:
            return Response(
                case_id=case.id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(start),
                source=self.name,
                model=self._model,
            )
        return Response(
            case_id=case.id,
            text=text,
            latency_ms=self._elapsed_ms(start),
            tokens_in=tin,
            tokens_out=tout,
            model=self._model,
            source=self.name,
        )

    async def _anthropic(self, prompt: str) -> tuple[str, int | None, int | None]:
        client = self._ensure_client()
        msg = await client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=self._system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        if msg.content:
            for block in msg.content:
                t = getattr(block, "text", None)
                if t is not None:
                    text = t
                    break
        usage = getattr(msg, "usage", None)
        tin = getattr(usage, "input_tokens", None) if usage else None
        tout = getattr(usage, "output_tokens", None) if usage else None
        return text, tin, tout

    async def _openai(self, prompt: str) -> tuple[str, int | None, int | None]:
        client = self._ensure_client()
        messages = []
        if self._system:
            messages.append({"role": "system", "content": self._system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=messages,
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "prompt_tokens", None) if usage else None
        tout = getattr(usage, "completion_tokens", None) if usage else None
        return text, tin, tout
