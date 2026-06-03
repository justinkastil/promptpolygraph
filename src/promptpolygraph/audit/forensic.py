"""Forensic audit: trace weak rubric dimensions to root causes + leverage.

One agent per category inspects that category's cases, responses, and scores
against the rubric, naming concrete failure modes per weak dimension and the
highest-leverage change to make. A final synthesis agent finds cross-category
patterns and produces a prioritized change list. The mock path derives the same
shape deterministically from the score data (no LLM calls).
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from ..llm import LLMClient
from ..models import Case, Response, Rubric, Score
from .code_context import CodeIndex, build_code_context
from .engine import run_agent, run_agents

# ─── schemas ────────────────────────────────────────────────────────────────

_CATEGORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "gap_dims": {"type": "array", "items": {"type": "string"}},
        "failure_modes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string"},
                    "pattern": {"type": "string"},
                    "example_case_ids": {"type": "array", "items": {"type": "string"}},
                    "rubric_criterion_missed": {"type": "string"},
                    "code_locus": {"type": "string", "description": "file:line in the source tree, when code is provided"},
                    "frequency": {"type": "string"},
                },
            },
        },
        "leverage_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "change": {"type": "string"},
                    "target_dimension": {"type": "string"},
                    "code_locus": {"type": "string", "description": "file:line to change, when code is provided"},
                    "est_impact": {"type": "string"},
                    "effort": {"type": "string"},
                    "confidence": {"type": "string"},
                },
            },
        },
        "highest_leverage_one_liner": {"type": "string"},
    },
    "required": ["category", "gap_dims", "failure_modes", "leverage_changes", "highest_leverage_one_liner"],
}

_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cross_category_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "affected_categories": {"type": "array", "items": {"type": "string"}},
                    "shared_root_cause": {"type": "string"},
                    "code_locus": {"type": "string", "description": "file:line, when code is provided"},
                },
            },
        },
        "prioritized_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "change": {"type": "string"},
                    "unlocks_categories": {"type": "array", "items": {"type": "string"}},
                    "est_after": {"type": "string"},
                    "effort": {"type": "string"},
                    "confidence": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        },
        "closest_to_pass": {"type": "array", "items": {"type": "string"}},
        "narrative": {"type": "string"},
    },
    "required": ["cross_category_patterns", "prioritized_changes", "closest_to_pass", "narrative"],
}


# ─── data shaping ─────────────────────────────────────────────────────────────


def _group_by_category(
    cases: list[Case], responses: list[Response], scores: list[Score]
) -> dict[str, dict[str, Any]]:
    """Bundle cases/responses/scores per category, keyed by case_id joins."""
    resp_by_case = {r.case_id: r for r in responses}
    score_by_case = {s.case_id: s for s in scores}
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"cases": [], "responses": [], "scores": []})
    for c in cases:
        g = grouped[c.category]
        g["cases"].append(c)
        if c.id in resp_by_case:
            g["responses"].append(resp_by_case[c.id])
        if c.id in score_by_case:
            g["scores"].append(score_by_case[c.id])
    return dict(grouped)


def _dim_means(scores: list[Score]) -> dict[str, float]:
    """Mean of each dimension across non-None values."""
    acc: dict[str, list[int]] = defaultdict(list)
    for s in scores:
        for dim, val in s.dimensions.items():
            if val is not None:
                acc[dim].append(int(val))
    return {dim: (sum(v) / len(v)) for dim, v in acc.items() if v}


def _weak_dims(means: dict[str, float], threshold: float) -> list[str]:
    return sorted([d for d, m in means.items() if m < threshold], key=lambda d: means[d])


def _category_payload(cat: str, group: dict[str, Any], rubric: Rubric) -> dict[str, Any]:
    """JSON-serializable slice of one category for an agent prompt."""
    cases = {c.id: c for c in group["cases"]}
    resp_by_case = {r.case_id: r for r in group["responses"]}
    rows = []
    for s in group["scores"]:
        c = cases.get(s.case_id)
        r = resp_by_case.get(s.case_id)
        rows.append(
            {
                "case_id": s.case_id,
                "prompt": (c.prompt if c else "")[:600],
                "expected_behavior": (c.expected_behavior if c else None),
                "response": (r.text if r else "")[:800],
                "dimensions": s.dimensions,
                "failure_reason": s.failure_reason,
                "verdict_pass": s.verdict_pass,
            }
        )
    return {
        "category": cat,
        "threshold": rubric.threshold,
        "scale_max": rubric.scale_max,
        "dimensions": [{"name": d.name, "description": d.description} for d in rubric.dimensions],
        "dimension_means": _dim_means(group["scores"]),
        "rows": rows,
    }


def _category_terms(cat: str, group: dict[str, Any], rubric: Rubric) -> list[str]:
    """Query terms for ranking source files relevant to this category's gaps."""
    terms: list[str] = [cat]
    terms += [d.name for d in rubric.dimensions]
    terms += _weak_dims(_dim_means(group["scores"]), rubric.threshold)
    for c in group["cases"]:
        terms += list(c.red_flags or [])
        if c.expected_shape:
            terms.append(c.expected_shape)
    return terms


# ─── mock builders ────────────────────────────────────────────────────────────


def _mock_category_audit(cat: str, group: dict[str, Any], rubric: Rubric) -> dict[str, Any]:
    means = _dim_means(group["scores"])
    weak = _weak_dims(means, rubric.threshold)
    # gather example case ids for the weakest dim
    failure_modes = []
    for dim in weak:
        examples = [
            s.case_id
            for s in group["scores"]
            if s.dimensions.get(dim) is not None and int(s.dimensions[dim]) < rubric.threshold
        ]
        failure_modes.append(
            {
                "dimension": dim,
                "pattern": f"{dim} scores below threshold (mean {means[dim]:.1f}) on {cat} cases",
                "example_case_ids": examples[:5],
                "rubric_criterion_missed": dim,
                "frequency": f"{len(examples)}/{len(group['scores'])}",
            }
        )
    lowest = weak[0] if weak else (min(means, key=means.get) if means else "Quality")
    leverage_changes = [
        {
            "change": f"Strengthen handling that drives {dim} on {cat}",
            "target_dimension": dim,
            "est_impact": f"+{max(1.0, rubric.threshold - means.get(dim, 0)):.1f} on {dim}",
            "effort": "medium",
            "confidence": "medium",
        }
        for dim in (weak or [lowest])
    ]
    return {
        "category": cat,
        "gap_dims": weak,
        "failure_modes": failure_modes,
        "leverage_changes": leverage_changes,
        "highest_leverage_one_liner": f"raise {lowest} on {cat}",
    }


def _mock_synthesis(category_audits: list[dict[str, Any]], rubric: Rubric) -> dict[str, Any]:
    # cross-category pattern: dims that are weak in more than one category
    dim_to_cats: dict[str, list[str]] = defaultdict(list)
    for ca in category_audits:
        for dim in ca.get("gap_dims", []):
            dim_to_cats[dim].append(ca["category"])
    cross = [
        {
            "pattern": f"{dim} is weak across multiple categories",
            "affected_categories": cats,
            "shared_root_cause": f"systematic underperformance on {dim}",
        }
        for dim, cats in dim_to_cats.items()
        if len(cats) > 1
    ]
    # prioritize by how many categories a change unlocks
    prioritized = []
    rank = 1
    for dim, cats in sorted(dim_to_cats.items(), key=lambda kv: -len(kv[1])):
        prioritized.append(
            {
                "rank": rank,
                "change": f"Address {dim} systematically",
                "unlocks_categories": cats,
                "est_after": f">= {rubric.threshold}",
                "effort": "medium",
                "confidence": "medium",
                "rationale": f"{dim} is the gap dimension in {len(cats)} categor(y/ies)",
            }
        )
        rank += 1
    # closest to pass = categories with the fewest gap dims (but still >0)
    closest = [
        ca["category"]
        for ca in sorted(category_audits, key=lambda c: len(c.get("gap_dims", [])))
        if ca.get("gap_dims")
    ][:3]
    narrative = (
        f"{len([c for c in category_audits if c.get('gap_dims')])} of "
        f"{len(category_audits)} categories have at least one dimension below the "
        f"{rubric.threshold} threshold. Highest-leverage work targets the dimensions "
        f"shared across the most categories."
    )
    return {
        "cross_category_patterns": cross,
        "prioritized_changes": prioritized,
        "closest_to_pass": closest,
        "narrative": narrative,
    }


# ─── public entrypoint ─────────────────────────────────────────────────────────


async def run_forensic(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    rubric: Rubric,
    *,
    client: LLMClient | None = None,
    code_path: str | None = None,
    mock: bool = False,
    concurrency: int = 8,
) -> dict[str, Any]:
    """Per-category forensic audit + cross-category synthesis.

    Returns ``{"category_audits": [...], "synthesis": {...}}``. In mock mode
    (or with no client) the result is computed deterministically from the score
    data, with no LLM calls.
    """
    grouped = _group_by_category(cases, responses, scores)
    categories = sorted(grouped.keys())

    if mock or client is None:
        category_audits = [_mock_category_audit(cat, grouped[cat], rubric) for cat in categories]
        synthesis = _mock_synthesis(category_audits, rubric)
        return {"category_audits": category_audits, "synthesis": synthesis}

    # LLM path: one agent per category. When a local source tree is provided,
    # walk it once and hand each category agent a relevance-ranked slice so it
    # can cite real file:line root causes (token-free — reads a local checkout,
    # e.g. the CI workspace; it never contacts a remote repo).
    index = CodeIndex(code_path) if code_path else None
    has_code = bool(index and index.ok and index._files)
    code_instruction = (
        " The system-under-test source is included below as a repository map plus relevant "
        "excerpts; populate code_locus with the concrete file:line you'd inspect or change."
        if has_code else ""
    )

    items: list[dict[str, Any]] = []
    for cat in categories:
        payload = _category_payload(cat, grouped[cat], rubric)
        code_block = ""
        if has_code:
            terms = _category_terms(cat, grouped[cat], rubric)
            ctx = build_code_context(code_path, terms, index=index)
            if ctx:
                code_block = "\n\nSOURCE (cite as file:line):\n" + ctx
        prompt = (
            "You are a forensic evaluator. Below is one category of an evaluation run: the "
            "rubric dimensions, per-dimension means, and individual scored cases (prompt, "
            "expected behavior, target response, dimension scores).\n\n"
            "Identify which dimensions fall below the threshold (gap_dims), the concrete "
            "failure modes behind each weak dimension (with example case_ids and the rubric "
            "criterion missed), ranked leverage_changes to close the gap, and a single "
            "highest_leverage_one_liner." + code_instruction
            + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False) + code_block
        )
        items.append(
            {
                "prompt": prompt,
                "schema": _CATEGORY_SCHEMA,
                "mock_fn": (lambda c=cat: lambda _p: _mock_category_audit(c, grouped[c], rubric))(),
            }
        )

    category_audits = await run_agents(client, items, concurrency=concurrency, mock=False)
    # backfill category field defensively
    for ca, cat in zip(category_audits, categories):
        if isinstance(ca, dict):
            ca.setdefault("category", cat)

    synth_code = ""
    if has_code and index is not None:
        synth_code = (
            "\n\nREPOSITORY MAP (cite shared root causes as file:line where you can):\n"
            + index.repo_map()
        )
    synth_prompt = (
        "You are a synthesis agent. Below are per-category forensic audits from an evaluation "
        "run. Find cross_category_patterns (shared root causes), produce a prioritized_changes "
        "ranking (rank, change, which categories it unlocks, estimated after-state, effort, "
        "confidence, rationale), list the categories closest_to_pass, and write a short "
        "narrative.\n\nCATEGORY AUDITS:\n" + json.dumps(category_audits, ensure_ascii=False)
        + synth_code
    )
    synthesis = await run_agent(
        client,
        synth_prompt,
        _SYNTHESIS_SCHEMA,
        mock_fn=lambda _p: _mock_synthesis(category_audits, rubric),
        mock=False,
        max_tokens=2048,
    )
    return {"category_audits": category_audits, "synthesis": synthesis}
