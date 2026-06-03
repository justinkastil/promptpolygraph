"""Generic async multi-agent fan-out for structured-output agents.

This is a tiny, dependency-free workflow engine: each "agent" is a single
LLM call that must return JSON conforming to a caller-supplied schema. The
engine builds a JSON-only system prompt, calls the LLM, and defensively parses
the result. When run in mock mode (or with no client) a deterministic
``mock_fn`` is used instead of the LLM, so the whole audit pipeline runs
offline and reproducibly.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from ..llm import LLMClient, extract_json

_JSON_SYSTEM = (
    "You are a precise structured-output agent. You respond with a SINGLE JSON "
    "value and nothing else: no prose, no markdown fences, no commentary. The "
    "JSON MUST conform to this schema:\n\n{schema}\n\n"
    "Emit only valid JSON. Do not wrap it in code fences."
)


def _build_system(system: str, schema: dict[str, Any]) -> str:
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    base = _JSON_SYSTEM.format(schema=schema_str)
    if system:
        return f"{system.strip()}\n\n{base}"
    return base


async def run_agent(
    client: LLMClient | None,
    prompt: str,
    schema: dict[str, Any],
    *,
    system: str = "",
    mock_fn: Callable[[str], dict[str, Any]] | None = None,
    mock: bool = False,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """Run one structured-output agent and return its parsed JSON dict.

    When ``mock`` is true or ``client`` is None, ``mock_fn(prompt)`` is called
    to produce a deterministic dict instead of contacting the LLM. On any LLM
    parse failure the function degrades to ``{"_error": ...}`` rather than
    raising, so a single bad agent never sinks a fan-out.
    """
    if mock or client is None:
        if mock_fn is None:
            return {"_error": "no mock_fn supplied for mock/offline run"}
        try:
            result = mock_fn(prompt)
        except Exception as exc:  # pragma: no cover - defensive
            return {"_error": f"mock_fn raised: {exc!r}"}
        return result if isinstance(result, dict) else {"_error": "mock_fn did not return a dict"}

    sys_prompt = _build_system(system, schema)
    try:
        raw = await client.complete(
            system=sys_prompt,
            user=prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
    except Exception as exc:
        return {"_error": f"llm call failed: {exc!r}"}

    try:
        parsed = extract_json(raw)
    except Exception as exc:
        return {"_error": f"json parse failed: {exc!r}", "_raw": raw}

    if not isinstance(parsed, dict):
        return {"_error": "agent did not return a JSON object", "_raw": parsed}
    return parsed


async def run_agents(
    client: LLMClient | None,
    items: list[dict[str, Any]],
    *,
    concurrency: int = 8,
    mock: bool = False,
) -> list[dict[str, Any]]:
    """Fan out a list of agent items under an asyncio.Semaphore.

    Each item is a dict with keys: ``prompt`` (str), ``schema`` (dict),
    optional ``system`` (str), optional ``mock_fn`` (callable). Results come
    back in the same order as ``items``.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await run_agent(
                client,
                item.get("prompt", ""),
                item.get("schema", {}),
                system=item.get("system", ""),
                mock_fn=item.get("mock_fn"),
                mock=mock,
                max_tokens=item.get("max_tokens", 2048),
            )

    return await asyncio.gather(*(_one(it) for it in items))
