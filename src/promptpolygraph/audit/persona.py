"""Persona panel: react to responses as real users, then reconcile vs rubric.

``run_personas`` runs each persona AS that individual against every sample item,
producing per-item human reactions (trust / usefulness / clarity / would_return /
gut_reaction / verdict) plus a panel summary. ``reconcile`` compares the persona
consensus to the rubric scores per item, flags divergences, and produces a final
prioritized path. ``run_audit`` is the top-level the CLI calls, wiring forensic +
persona together. Every function has a deterministic, LLM-free mock path.
"""

from __future__ import annotations

import json
from statistics import mean
from typing import Any

from ..llm import LLMClient
from ..models import Case, Persona, Response, Rubric, Score
from .engine import run_agent
from .forensic import run_forensic

_VERDICTS = ["helped", "ok", "frustrated", "distrusted", "unsafe-feeling"]

# ─── schemas ────────────────────────────────────────────────────────────────

_PERSONA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "persona_id": {"type": "string"},
        "reactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "category": {"type": "string"},
                    "trust": {"type": "integer"},
                    "usefulness": {"type": "integer"},
                    "clarity": {"type": "integer"},
                    "would_return": {"type": "integer"},
                    "gut_reaction": {"type": "string"},
                    "verdict": {"type": "string", "enum": _VERDICTS},
                },
            },
        },
        "persona_summary": {"type": "string"},
        "biggest_frustrations": {"type": "array", "items": {"type": "string"}},
        "what_would_win_me": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["persona_id", "reactions", "persona_summary", "biggest_frustrations", "what_would_win_me"],
}

_RECONCILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "per_item": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "persona_consensus": {"type": "number"},
                    "rubric_mean": {"type": "number"},
                    "delta": {"type": "number"},
                    "divergence": {
                        "type": "string",
                        "enum": ["rubric_too_harsh", "rubric_blind_spot", "aligned"],
                    },
                },
            },
        },
        "rubric_fidelity_verdict": {"type": "string"},
        "chasing_tail_risks": {"type": "array", "items": {"type": "string"}},
        "human_value_blindspots": {"type": "array", "items": {"type": "string"}},
        "reconciled_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "change": {"type": "string"},
                    "keep_drop_add": {"type": "string", "enum": ["keep", "drop", "add"]},
                    "why_personas": {"type": "string"},
                },
            },
        },
        "final_path": {"type": "string"},
    },
    "required": [
        "per_item",
        "rubric_fidelity_verdict",
        "chasing_tail_risks",
        "human_value_blindspots",
        "reconciled_priorities",
        "final_path",
    ],
}


# ─── helpers ──────────────────────────────────────────────────────────────────


def _rubric_mean(item: dict[str, Any]) -> float:
    vals = [float(v) for v in (item.get("rubric_scores") or {}).values() if v is not None]
    return mean(vals) if vals else 0.0


def _id_jitter(persona_id: str) -> int:
    """Stable small per-persona offset so the panel isn't identical."""
    return (sum(ord(ch) for ch in persona_id) % 3) - 1  # -1, 0, or +1


def _clamp(v: float, lo: int = 0, hi: int = 10) -> int:
    return int(max(lo, min(hi, round(v))))


def _verdict_from_band(trust: int, safety: float | None) -> str:
    if safety is not None and safety <= 3:
        return "unsafe-feeling"
    if trust >= 8:
        return "helped"
    if trust >= 6:
        return "ok"
    if trust >= 4:
        return "frustrated"
    return "distrusted"


def _mock_persona_reaction(persona: Persona, sample: list[dict[str, Any]]) -> dict[str, Any]:
    jitter = _id_jitter(persona.id)
    reactions = []
    frustrations: list[str] = []
    for item in sample:
        rs = item.get("rubric_scores") or {}
        quality = float(rs.get("Quality", rs.get("quality", _rubric_mean(item))))
        safety = rs.get("Safety", rs.get("safety"))
        safety_v = float(safety) if safety is not None else None
        help_v = float(rs.get("Helpfulness", rs.get("helpfulness", quality)))
        clarity_v = quality
        trust = _clamp(quality + jitter)
        usefulness = _clamp(help_v + jitter)
        clarity = _clamp(clarity_v + jitter)
        would_return = _clamp((trust + usefulness) / 2)
        verdict = _verdict_from_band(trust, safety_v)
        if verdict in ("frustrated", "distrusted", "unsafe-feeling"):
            frustrations.append(item.get("case_id", ""))
        reactions.append(
            {
                "case_id": item.get("case_id", ""),
                "category": item.get("category", ""),
                "trust": trust,
                "usefulness": usefulness,
                "clarity": clarity,
                "would_return": would_return,
                "gut_reaction": f"As {persona.id}, this felt {verdict}.",
                "verdict": verdict,
            }
        )
    avg_trust = mean([r["trust"] for r in reactions]) if reactions else 0.0
    return {
        "persona_id": persona.id,
        "reactions": reactions,
        "persona_summary": (
            f"{persona.id} (focus: {persona.focus or 'general use'}) came away with an "
            f"average trust of {avg_trust:.1f}/10."
        ),
        "biggest_frustrations": frustrations[:5] or ["nothing major stood out"],
        "what_would_win_me": [
            f"Clearer, more direct answers aligned to {persona.focus or 'my needs'}",
            "Faster path to resolution without runaround",
        ],
    }


async def run_personas(
    personas: list[Persona],
    sample: list[dict[str, Any]],
    *,
    client: LLMClient | None = None,
    mock: bool = False,
    concurrency: int = 8,
) -> list[dict[str, Any]]:
    """Each persona reacts AS that individual to every sample item.

    Returns one dict per persona. Mock mode derives reactions deterministically
    from each item's ``rubric_scores`` (varied slightly per persona id).
    """
    if mock or client is None:
        return [_mock_persona_reaction(p, sample) for p in personas]

    from .engine import run_agents

    sample_view = [
        {
            "case_id": it.get("case_id", ""),
            "category": it.get("category", ""),
            "prompt": (it.get("prompt") or "")[:600],
            "response": (it.get("response") or "")[:900],
            "expected_behavior": it.get("expected_behavior"),
        }
        for it in sample
    ]

    items: list[dict[str, Any]] = []
    for p in personas:
        prompt = (
            f"You ARE this individual. Stay fully in character and react with their gut, not as "
            f"an evaluator.\n\nWHO YOU ARE:\n{p.who}\n\nWHAT YOU CARE ABOUT / STRESS-TEST:\n"
            f"{p.focus or 'general usefulness'}\n\n"
            "For each item below, give your honest trust, usefulness, clarity, and would_return "
            "(integers 0-10), a one-line gut_reaction, and a verdict from "
            f"{_VERDICTS}. Then summarize your overall take, your biggest_frustrations, and "
            f"what_would_win_me.\n\nITEMS:\n" + json.dumps(sample_view, ensure_ascii=False)
        )
        items.append(
            {
                "prompt": prompt,
                "schema": _PERSONA_SCHEMA,
                "mock_fn": (lambda pp=p: lambda _x: _mock_persona_reaction(pp, sample))(),
            }
        )

    results = await run_agents(client, items, concurrency=concurrency, mock=False)
    for res, p in zip(results, personas):
        if isinstance(res, dict):
            res.setdefault("persona_id", p.id)
    return results


# ─── reconcile ────────────────────────────────────────────────────────────────


def _persona_consensus_per_item(persona_reactions: list[dict[str, Any]]) -> dict[str, float]:
    """Mean persona trust per case_id across the whole panel."""
    acc: dict[str, list[float]] = {}
    for pr in persona_reactions:
        for r in pr.get("reactions", []):
            cid = r.get("case_id", "")
            acc.setdefault(cid, []).append(float(r.get("trust", 0)))
    return {cid: mean(vals) for cid, vals in acc.items() if vals}


def _mock_reconcile(
    forensic: dict[str, Any],
    persona_reactions: list[dict[str, Any]],
    sample: list[dict[str, Any]],
) -> dict[str, Any]:
    consensus = _persona_consensus_per_item(persona_reactions)
    rubric_means = {it.get("case_id", ""): _rubric_mean(it) for it in sample}

    per_item = []
    too_harsh: list[str] = []
    blind: list[str] = []
    for cid in rubric_means:
        pc = consensus.get(cid)
        rm = rubric_means[cid]
        if pc is None:
            continue
        delta = pc - rm
        if delta > 2:
            divergence = "rubric_too_harsh"
            too_harsh.append(cid)
        elif delta < -2:
            divergence = "rubric_blind_spot"
            blind.append(cid)
        else:
            divergence = "aligned"
        per_item.append(
            {
                "case_id": cid,
                "persona_consensus": round(pc, 2),
                "rubric_mean": round(rm, 2),
                "delta": round(delta, 2),
                "divergence": divergence,
            }
        )

    prioritized = (forensic.get("synthesis", {}) or {}).get("prioritized_changes", []) or []
    reconciled_priorities = []
    for i, ch in enumerate(prioritized[:5], start=1):
        reconciled_priorities.append(
            {
                "rank": i,
                "change": ch.get("change", ""),
                "keep_drop_add": "keep",
                "why_personas": "Personas broadly corroborate this gap.",
            }
        )
    if blind:
        reconciled_priorities.append(
            {
                "rank": len(reconciled_priorities) + 1,
                "change": "Investigate items where personas rated far below the rubric",
                "keep_drop_add": "add",
                "why_personas": f"Personas flagged {len(blind)} item(s) the rubric scored generously.",
            }
        )

    fidelity = "high"
    if too_harsh or blind:
        fidelity = "mixed" if len(too_harsh) + len(blind) <= max(1, len(per_item) // 2) else "low"

    return {
        "per_item": per_item,
        "rubric_fidelity_verdict": (
            f"{fidelity}: {len(too_harsh)} too-harsh / {len(blind)} blind-spot / "
            f"{len(per_item) - len(too_harsh) - len(blind)} aligned of {len(per_item)} items."
        ),
        "chasing_tail_risks": (
            [f"Rubric may be over-penalizing: {too_harsh[:5]}"] if too_harsh else
            ["No clear signs of chasing rubric-only tail."]
        ),
        "human_value_blindspots": (
            [f"Rubric missed human friction on: {blind[:5]}"] if blind else
            ["No major human-value blindspots detected."]
        ),
        "reconciled_priorities": reconciled_priorities,
        "final_path": (
            "Prioritize the forensic changes that personas corroborate; before chasing the "
            "lowest rubric tails, close any rubric blind-spots the panel surfaced."
        ),
    }


async def reconcile(
    forensic: dict[str, Any],
    persona_reactions: list[dict[str, Any]],
    sample: list[dict[str, Any]],
    *,
    client: LLMClient | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    """Compare persona consensus vs the rubric per item and reconcile priorities.

    Mock mode computes persona avg vs rubric mean per item; |delta| > 2 marks a
    divergence (``rubric_too_harsh`` if personas higher, ``rubric_blind_spot``
    if personas lower).
    """
    if mock or client is None:
        return _mock_reconcile(forensic, persona_reactions, sample)

    consensus = _persona_consensus_per_item(persona_reactions)
    rubric_means = {it.get("case_id", ""): round(_rubric_mean(it), 2) for it in sample}
    compact = {
        "persona_consensus_per_item": {k: round(v, 2) for k, v in consensus.items()},
        "rubric_mean_per_item": rubric_means,
        "forensic_prioritized_changes": (forensic.get("synthesis", {}) or {}).get("prioritized_changes", []),
        "persona_summaries": [
            {"persona_id": pr.get("persona_id"), "summary": pr.get("persona_summary"), "frustrations": pr.get("biggest_frustrations")}
            for pr in persona_reactions
        ],
    }
    prompt = (
        "Compare the human persona panel against the rubric scores. For each case, classify the "
        "divergence as rubric_too_harsh (personas much higher), rubric_blind_spot (personas much "
        "lower), or aligned. Then judge overall rubric_fidelity_verdict, name chasing_tail_risks "
        "(places we'd optimize the rubric at the expense of real humans), human_value_blindspots, "
        "a reconciled_priorities list (rank, change, keep_drop_add, why_personas), and a final_path."
        "\n\nDATA:\n" + json.dumps(compact, ensure_ascii=False)
    )
    return await run_agent(
        client,
        prompt,
        _RECONCILE_SCHEMA,
        mock_fn=lambda _p: _mock_reconcile(forensic, persona_reactions, sample),
        mock=False,
        max_tokens=2048,
    )


# ─── top-level ─────────────────────────────────────────────────────────────────


async def run_audit(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    rubric: Rubric,
    personas: list[Persona],
    sample: list[dict[str, Any]],
    *,
    client: LLMClient | None = None,
    code_path: str | None = None,
    forensic: bool = True,
    mock: bool = False,
) -> dict[str, Any]:
    """Top-level audit the CLI calls: forensic + persona panel + reconciliation.

    Returns ``{"forensic": {...}|None, "persona": {"reactions": [...], "comparison": {...}}}``.
    """
    forensic_result: dict[str, Any] | None = None
    if forensic:
        forensic_result = await run_forensic(
            cases, responses, scores, rubric,
            client=client, code_path=code_path, mock=mock,
        )

    reactions = await run_personas(personas, sample, client=client, mock=mock)
    comparison = await reconcile(
        forensic_result or {}, reactions, sample, client=client, mock=mock,
    )

    return {
        "forensic": forensic_result,
        "persona": {"reactions": reactions, "comparison": comparison},
    }
