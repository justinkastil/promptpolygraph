"""Text embedders for the semantic-similarity (`similar`) assertion.

Every embedder implements an async `embed(texts) -> list[list[float]]`. The
default `MockEmbedder` is deterministic and fully offline (a hashed bag-of-words
projection), so the `similar` scorer — and the whole pipeline — runs with no API
key and reproduces the same vectors run-over-run. `OpenAIEmbedder` is optional
and behind a try-import; if the `openai` package or a key is unavailable it
transparently falls back to the mock so a run never breaks on a missing dep.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Protocol, runtime_checkable

_TOKEN = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one dense vector per input text."""
        ...


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity, clamped to [0, 1] (negative -> 0)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    sim = dot / (na * nb)
    if sim < 0.0:
        return 0.0
    if sim > 1.0:
        return 1.0
    return float(sim)


class MockEmbedder:
    """Deterministic, offline embedder.

    Projects each token onto a fixed-dimension vector via a stable hash, so two
    texts that share words land near each other in cosine space. No network, no
    randomness — the same input always yields the same vector.
    """

    name = "mock"

    def __init__(self, dim: int = 64, **_: Any):
        self.dim = max(8, int(dim))

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = _TOKEN.findall((text or "").lower())
        for tok in toks:
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            # sign from a second slice keeps related tokens additive but spread.
            sign = 1.0 if (h[4] & 1) == 0 else -1.0
            vec[idx] += sign
        return vec

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbedder:
    """Optional embeddings via OpenAI. Falls back to MockEmbedder if the
    `openai` package or an API key is unavailable, so it is always safe to
    construct."""

    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key_env: str | None = None,
        base_url: str | None = None,
        dim: int = 64,
        **_: Any,
    ):
        self.model = model or "text-embedding-3-small"
        self._fallback = MockEmbedder(dim=dim)
        self._client: Any = None
        try:  # pragma: no cover - exercised only with the optional dep present
            import openai

            key = os.environ.get(api_key_env or "OPENAI_API_KEY")
            if key:
                self._client = openai.AsyncOpenAI(api_key=key, base_url=base_url)
        except Exception:  # noqa: BLE001 - any import/setup failure -> mock
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            return await self._fallback.embed(texts)
        try:  # pragma: no cover - needs a live key
            resp = await self._client.embeddings.create(model=self.model, input=texts)
            return [list(item.embedding) for item in resp.data]
        except Exception:  # noqa: BLE001 - never break a run on an embed call
            return await self._fallback.embed(texts)


def make_embedder(
    provider: str = "mock",
    model: str | None = None,
    options: dict[str, Any] | None = None,
) -> Embedder:
    """Build an embedder from config. Unknown providers fall back to mock."""
    opts = dict(options or {})
    if provider == "openai":
        return OpenAIEmbedder(model=model, **opts)
    return MockEmbedder(**opts)
