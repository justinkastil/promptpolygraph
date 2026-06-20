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

# Cloud providers routed through litellm. Each authenticates via its own env
# vars (see docs/PROVIDERS.md); availability here means [litellm] is installed
# and a credential signal is present. Model strings expect the litellm prefix.
_LITELLM_PROVIDERS = [
    {
        "id": "bedrock", "label": "AWS Bedrock",
        "models": ["anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic.claude-3-haiku-20240307-v1:0"],
        "creds": ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_REGION_NAME"),
        "creds_hint": "set AWS credentials (AWS_ACCESS_KEY_ID/AWS_PROFILE + region)",
    },
    {
        "id": "vertex_ai", "label": "Google Vertex AI",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
        "creds": ("GOOGLE_APPLICATION_CREDENTIALS", "VERTEXAI_PROJECT"),
        "creds_hint": "set GOOGLE_APPLICATION_CREDENTIALS + VERTEXAI_PROJECT/VERTEXAI_LOCATION",
    },
    {
        "id": "azure", "label": "Azure OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "creds": ("AZURE_API_KEY",),
        "creds_hint": "set AZURE_API_KEY + AZURE_API_BASE + AZURE_API_VERSION",
    },
    {
        "id": "gemini", "label": "Google Gemini (AI Studio)",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
        "creds": ("GEMINI_API_KEY",),
        "creds_hint": "set GEMINI_API_KEY",
    },
    {
        "id": "cohere", "label": "Cohere",
        "models": ["command-r-plus", "command-r"],
        "creds": ("COHERE_API_KEY",),
        "creds_hint": "set COHERE_API_KEY",
    },
]


def _litellm_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("litellm") is not None


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

    has_litellm = _litellm_installed()
    for spec in _LITELLM_PROVIDERS:
        creds_present = any(os.environ.get(v) for v in spec["creds"])
        if not has_litellm:
            reason = "install the [litellm] extra to enable"
        elif creds_present:
            reason = "litellm installed; credentials detected"
        else:
            reason = spec["creds_hint"]
        out.append({
            "id": spec["id"], "label": spec["label"],
            "available": has_litellm and creds_present, "reason": reason,
            "needs_key": None, "models": spec["models"],
            "default_model": spec["models"][0], "allow_custom": True,
        })

    return out
