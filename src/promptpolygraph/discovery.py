"""Provider/model discovery.

Replaces free-text provider/model entry with a real picture of what's configured:
which backends are usable right now (API key present, or a local server reachable)
and which models each offers. The dashboard turns this into dropdowns; `polygraph
init` turns it into a setup report. No network calls except a short, optional probe
of a local model server's tag list.
"""

from __future__ import annotations

import os
from typing import Any

from .llm import DEFAULT_OLLAMA_BASE_URL

# Curated default model menus for the key-based providers (these evolve, so the
# UI also offers a "custom" entry — see allow_custom).
_ANTHROPIC_MODELS = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
_OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini", "o3-mini"]


def _ollama_root(base_url: str | None = None) -> str:
    # The OpenAI-compat URL ends in /v1; the native tag list lives at the root.
    base = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


def _list_ollama_models(base_url: str | None = None, timeout: float = 0.8) -> tuple[bool, list[str], str]:
    """(reachable, model_names, reason). Probes GET {root}/api/tags."""
    try:
        import httpx

        url = _ollama_root(base_url) + "/api/tags"
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        names = [m.get("name") for m in data.get("models", []) if m.get("name")]
        if not names:
            return True, [], "reachable, but no models pulled (try: ollama pull llama3.1)"
        return True, names, "reachable"
    except Exception as exc:
        return False, [], f"not reachable at {_ollama_root(base_url)} ({type(exc).__name__})"


def discover_providers(*, ollama_base: str | None = None, probe_local: bool = True) -> list[dict[str, Any]]:
    """Return the configured/available providers + their models for UI dropdowns.

    Each entry: {id, label, available, reason, needs_key, models, default_model,
    allow_custom, base_url?}.
    """
    out: list[dict[str, Any]] = []

    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    out.append({
        "id": "anthropic", "label": "Anthropic (Claude)", "available": has_anthropic,
        "reason": "ANTHROPIC_API_KEY set" if has_anthropic else "set ANTHROPIC_API_KEY to enable",
        "needs_key": "ANTHROPIC_API_KEY", "models": _ANTHROPIC_MODELS,
        "default_model": _ANTHROPIC_MODELS[0], "allow_custom": True,
    })

    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    out.append({
        "id": "openai", "label": "OpenAI", "available": has_openai,
        "reason": "OPENAI_API_KEY set" if has_openai else "set OPENAI_API_KEY to enable",
        "needs_key": "OPENAI_API_KEY", "models": _OPENAI_MODELS,
        "default_model": _OPENAI_MODELS[0], "allow_custom": True,
    })

    if probe_local:
        reachable, models, reason = _list_ollama_models(ollama_base)
    else:
        reachable, models, reason = False, [], "probe skipped"
    out.append({
        "id": "ollama", "label": "Ollama (local)", "available": reachable and bool(models),
        "reason": reason, "needs_key": None, "models": models,
        "default_model": models[0] if models else None, "allow_custom": True,
        "base_url": _ollama_root(ollama_base) + "/v1",
    })

    return out
