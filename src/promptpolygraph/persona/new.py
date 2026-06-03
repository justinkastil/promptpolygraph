"""Persona creation tools: one-line description -> full Persona, and panels.

``create_persona`` turns a short description into a richly-drawn Persona (id slug
+ vivid ``who`` + a ``focus`` describing what they stress-test). ``generate_panel``
synthesizes a diverse panel for a product domain. Both have deterministic mock
paths so they run offline.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm import LLMClient
from ..models import Persona
from ..audit.engine import run_agent

_PERSONA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "short snake_case slug"},
        "who": {"type": "string", "description": "2-4 vivid sentences"},
        "focus": {"type": "string", "description": "what they stress-test"},
    },
    "required": ["id", "who", "focus"],
}

_PANEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "personas": {
            "type": "array",
            "items": _PERSONA_SCHEMA,
        }
    },
    "required": ["personas"],
}


def _slugify(text: str, *, fallback: str = "persona") -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # prefer the first few salient words
    slug = "_".join(words[:4]) if words else ""
    return slug or fallback


def _mock_persona(description: str) -> Persona:
    desc = description.strip()
    slug = _slugify(desc)
    who = (
        f"A user best summed up as: {desc}. They bring this exact disposition to every "
        f"interaction and judge a product by whether it respects it. What frustrates them is "
        f"anything that ignores or works against {desc}."
    )
    focus = f"Whether the product holds up for someone who is {desc}."
    return Persona(id=slug, who=who, focus=focus)


def _mock_panel(count: int, domain: str) -> list[Persona]:
    archetypes = [
        ("the_skeptic", "doubts marketing claims and probes for weak spots", "trustworthiness and overpromising"),
        ("first_timer", "has never used a product like this and needs gentle orientation", "onboarding and jargon"),
        ("power_user", "wants depth, shortcuts, and control", "advanced capability and efficiency"),
        ("time_pressed", "has thirty seconds and wants the answer now", "speed and directness"),
        ("budget_conscious", "scrutinizes every cost and hidden fee", "pricing transparency"),
        ("plain_language_needer", "needs simple, jargon-free explanations", "readability"),
        ("the_troll", "tries to provoke, confuse, or break the system", "robustness under abuse"),
        ("enthusiast", "is excited and wants to push the product to its limits", "delight and edge features"),
    ]
    count = max(0, count)
    out: list[Persona] = []
    for i in range(count):
        base_id, trait, foc = archetypes[i % len(archetypes)]
        suffix = "" if i < len(archetypes) else f"_{i // len(archetypes) + 1}"
        pid = f"{base_id}{suffix}"
        who = (
            f"A {domain} user who {trait}. They value a product that meets them where they are, "
            f"and they lose patience the moment it does not. Their reactions are honest and "
            f"unfiltered."
        )
        out.append(Persona(id=pid, who=who, focus=f"{foc} in a {domain} context"))
    return out


async def create_persona(
    client: LLMClient | None,
    description: str,
    *,
    mock: bool = False,
) -> Persona:
    """Turn a one-line description into a full Persona.

    Mock mode builds the Persona deterministically from the description.
    """
    if mock or client is None:
        return _mock_persona(description)

    prompt = (
        "Turn this one-line description into a fully-realized evaluation persona: a short "
        "snake_case id, a vivid 2-4 sentence 'who' (who they are, what they value, what "
        "frustrates them), and a 'focus' describing what they stress-test. Keep it neutral and "
        "general-consumer flavored.\n\nDESCRIPTION: " + description
    )
    result = await run_agent(
        client,
        prompt,
        _PERSONA_SCHEMA,
        mock_fn=lambda _p: _mock_persona(description).model_dump(),
        mock=False,
        max_tokens=1024,
    )
    pid = str(result.get("id") or _slugify(description)).strip() or _slugify(description)
    who = str(result.get("who") or "").strip()
    if not who:
        return _mock_persona(description)
    return Persona(id=pid, who=who, focus=str(result.get("focus", "")).strip())


async def generate_panel(
    client: LLMClient | None,
    count: int,
    domain: str,
    *,
    mock: bool = False,
) -> list[Persona]:
    """Synthesize a diverse panel of ``count`` personas for a product ``domain``.

    Mock mode returns a deterministic, varied archetype panel.
    """
    if mock or client is None:
        return _mock_panel(count, domain)

    prompt = (
        f"Synthesize a diverse panel of {count} distinct evaluation personas for a '{domain}' "
        "product. Span skill levels, attitudes, and stress cases (skeptic, first-timer, power "
        "user, time-pressed, budget-conscious, plain-language needer, an abusive/troll case, an "
        "enthusiast). Each persona: snake_case id, vivid 2-4 sentence 'who', and a 'focus'. Keep "
        "everything neutral and general-consumer flavored; avoid sensitive regulated domains."
    )
    result = await run_agent(
        client,
        prompt,
        _PANEL_SCHEMA,
        mock_fn=lambda _p: {"personas": [p.model_dump() for p in _mock_panel(count, domain)]},
        mock=False,
        max_tokens=4096,
    )
    raw = result.get("personas") if isinstance(result, dict) else None
    if not isinstance(raw, list) or not raw:
        return _mock_panel(count, domain)
    out: list[Persona] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("id", "")).strip()
        who = str(r.get("who", "")).strip()
        if pid and who:
            out.append(Persona(id=pid, who=who, focus=str(r.get("focus", "")).strip()))
    return out or _mock_panel(count, domain)
