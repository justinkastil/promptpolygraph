"""AI config designer.

Given a one-paragraph description of the system under test and what the operator
wants to evaluate, design a complete run config (adapter shape, corpus mode +
categories, analysis/audit/report settings, red-team profile). The dashboard
injects the result into the config builder for review + save — the human stays
in control; this just removes the blank-page problem.

Returns a config dict that validates against `Config` (unknown keys are ignored
by Config), plus short notes on the choices. Mock mode is deterministic + offline.
"""

from __future__ import annotations

import re
from typing import Any

from .llm import LLMClient, extract_json

# Categories are user-defined; these are sensible neutral defaults the mock path
# uses and the LLM is told it may adapt. Nothing domain-specific is hardcoded.
_DEFAULT_CATEGORIES = ["core_capability", "edge_cases", "safety", "refusal_robustness"]
_PROFILES = ["all_frontier", "deep", "multi_frontier", "mixed", "local_swarm", "pressure", "quick"]

_SYSTEM = (
    "You design evaluation configs for an LLM/API testing harness. Given a description of the "
    "system under test and the operator's goals, return ONLY JSON with this shape: "
    '{"name": "<kebab-case>", "domain": "<one line>", '
    '"adapter": {"type": "http|llm|callable|demo", "options": {}}, '
    '"corpus": {"mode": "varied|adversarial|hybrid", "per_category": <int>, '
    '"categories": ["<lowercase_snake>", ...], "difficulty": "mild|standard|aggressive"}, '
    '"analyze": {"judges": <int 1-3>, "gate_mode": "strict|weighted"}, '
    '"audit": {"forensic": <bool>, "persona_pool": <int>}, '
    '"report": {"formats": ["md","html"]}, '
    '"redteam": {"profile": "all_frontier|deep|mixed|local_swarm|pressure|quick"}, '
    '"notes": "<1-3 sentences on why these choices>"}. '
    "Pick categories that probe THIS system's risks and capabilities (6-10 of them). "
    "Default adapter.type to llm for a model/chatbot, http for a web API, demo if unclear. "
    "Do not invent secrets or real endpoints; leave adapter.options minimal."
)


def _slug(text: str, fallback: str = "eval") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return ("-".join(s.split("-")[:5]) or fallback)[:48]


def _mock_design(description: str) -> dict[str, Any]:
    desc = (description or "").strip()
    low = desc.lower()
    adapter_type = "llm" if any(w in low for w in ("model", "chatbot", "assistant", "llm", "gpt", "claude")) \
        else "http" if any(w in low for w in ("api", "endpoint", "service", "rest", "http")) else "demo"
    difficulty = "aggressive" if any(w in low for w in ("adversarial", "jailbreak", "red team", "attack", "security")) \
        else "standard"
    return {
        "name": _slug(desc, "eval"),
        "domain": desc[:160] or "a general-purpose assistant",
        "adapter": {"type": adapter_type, "options": {}},
        "corpus": {"mode": "varied", "per_category": 8, "categories": list(_DEFAULT_CATEGORIES),
                   "difficulty": difficulty},
        "analyze": {"judges": 1, "gate_mode": "weighted"},
        "audit": {"forensic": True, "persona_pool": 5},
        "report": {"formats": ["md", "html"]},
        "redteam": {"profile": "all_frontier"},
        "notes": "Offline draft: varied corpus across neutral categories, weighted gate, "
                 "forensic audit on, all_frontier red team. Edit categories + adapter to fit your system.",
    }


def _sanitize(cfg: dict[str, Any]) -> dict[str, Any]:
    """Coerce an LLM-designed config into safe, in-range values."""
    out = dict(cfg)
    out["name"] = _slug(str(out.get("name") or out.get("domain") or "eval"))
    rt = out.get("redteam") or {}
    if rt.get("profile") not in _PROFILES:
        rt["profile"] = "all_frontier"
    out["redteam"] = rt
    corpus = out.get("corpus") or {}
    if corpus.get("mode") not in ("varied", "adversarial", "hybrid", "fixed"):
        corpus["mode"] = "varied"
    cats = corpus.get("categories")
    corpus["categories"] = [str(c) for c in cats][:12] if isinstance(cats, list) and cats else list(_DEFAULT_CATEGORIES)
    out["corpus"] = corpus
    an = out.get("analyze") or {}
    try:
        an["judges"] = max(1, min(3, int(an.get("judges", 1))))
    except (TypeError, ValueError):
        an["judges"] = 1
    out["analyze"] = an
    return out


async def design_config(client: LLMClient | None, description: str, *, mock: bool = False) -> dict[str, Any]:
    """Design a run config from a natural-language description. Returns
    {"config": <validated dict>, "notes": <str>}."""
    if mock or client is None:
        data = _mock_design(description)
    else:
        try:
            raw = await client.complete(
                system=_SYSTEM,
                user=f"System under test and goals:\n{description}\n\nDesign the config.",
                max_tokens=900, temperature=0.3,
            )
            data = extract_json(raw)
            if not isinstance(data, dict) or not data.get("corpus"):
                data = _mock_design(description)
        except Exception:
            data = _mock_design(description)

    notes = str(data.pop("notes", "") or "")
    config = _sanitize(data)
    # Validate it constructs a Config (unknown keys ignored); fall back if not.
    try:
        from .config import Config

        Config(**config)
    except Exception:
        config = _sanitize(_mock_design(description))
    return {"config": config, "notes": notes}
