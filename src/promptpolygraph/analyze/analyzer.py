"""The grading engine: assertions + LLM (or heuristic) judges -> Scores.

For each case/response pair we (1) run deterministic assertions, (2) ask
`judges` independent judges to score every applicable rubric dimension, (3) zero
out dimensions that do not apply to the case's category/shape, (4) ensemble the
judges by per-dimension median (with an agreement metric), and (5) compute the
per-case verdict. The whole batch runs concurrently under a semaphore.

A `mock=True` (or client-less) path swaps the LLM judge for a deterministic
heuristic so the offline pipeline produces a realistic spread of scores with no
API calls.
"""

from __future__ import annotations

import asyncio
import json
from statistics import median
from typing import Any

from ..llm import LLMClient, extract_json
from ..models import (
    AssertionResult,
    Case,
    Response,
    Rubric,
    Score,
)
from .assertions import evaluate_assertions
from .gate import case_pass


# ─── Prompt construction ────────────────────────────────────────────────────


def _build_system_prompt(rubric: Rubric) -> str:
    lines: list[str] = [
        "You are a rigorous, impartial evaluator scoring an AI assistant's "
        "response against a fixed rubric.",
        "",
        f"Score each dimension below on an integer scale from 0 to "
        f"{rubric.scale_max} (higher is better).",
        "",
        "DIMENSIONS:",
    ]
    for d in rubric.dimensions:
        lines.append(f"- {d.name}: {d.description}".rstrip())
        for key, text in d.anchors.items():
            lines.append(f"    {key}: {text}")
    lines += [
        "",
        "APPLICABILITY RULES:",
        "Some dimensions do not apply to every case. If a dimension does not "
        "apply to this case's category or response shape, you MUST return null "
        "for it (not 0).",
    ]
    if rubric.applicability:
        lines.append("Per-category applicable dimensions:")
        for cat, dims in rubric.applicability.items():
            lines.append(f"- {cat}: {', '.join(dims) if dims else '(none)'}")
    if rubric.blocked_shapes:
        lines.append("Per-shape blocked dimensions (return null for these):")
        for shape, dims in rubric.blocked_shapes.items():
            lines.append(f"- {shape}: {', '.join(dims)}")
    names = rubric.dimension_names()
    example = ", ".join(f'"{n}": <int or null>' for n in names)
    lines += [
        "",
        "Respond with ONLY a JSON object of the form:",
        f"{{{example}, \"notes\": \"<one short sentence>\"}}",
        "Do not include any prose outside the JSON object.",
    ]
    return "\n".join(lines)


def _build_user_prompt(case: Case, resp: Response, rubric: Rubric) -> str:
    parts = [
        f"CATEGORY: {case.category}",
    ]
    if case.expected_shape:
        parts.append(f"EXPECTED_SHAPE: {case.expected_shape}")
    if case.expected_behavior:
        parts.append(f"EXPECTED_BEHAVIOR: {case.expected_behavior}")
    if case.red_flags:
        parts.append("RED_FLAGS (presence should lower the score):")
        for rf in case.red_flags:
            parts.append(f"  - {rf}")
    parts.append("")
    parts.append("PROMPT:")
    parts.append(case.prompt)
    parts.append("")
    parts.append("RESPONSE:")
    parts.append(resp.text or "(empty)")
    if resp.error:
        parts.append("")
        parts.append(f"NOTE: the system returned an error: {resp.error}")
    return "\n".join(parts)


# ─── Judge parsing ──────────────────────────────────────────────────────────


def _coerce_dim(value: Any, scale_max: int) -> int | None:
    if value is None:
        return None
    try:
        iv = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(scale_max, iv))


def _parse_judge(text: str, rubric: Rubric) -> tuple[dict[str, int | None], str | None, str | None]:
    """Return (dims, failure_reason, notes). Defensive: never raises."""
    names = rubric.dimension_names()
    if not text or not text.strip():
        return ({n: None for n in names}, "analyzer_empty_content", "judge returned empty content")
    try:
        obj = extract_json(text)
    except json.JSONDecodeError:
        return ({n: None for n in names}, "analyzer_no_json", "judge returned no parseable JSON")
    if not isinstance(obj, dict):
        return ({n: None for n in names}, "analyzer_bad_shape", "judge JSON was not an object")
    dims = {n: _coerce_dim(obj.get(n), rubric.scale_max) for n in names}
    notes = obj.get("notes")
    notes = str(notes) if notes is not None else None
    return (dims, None, notes)


# ─── Heuristic (mock) judge ─────────────────────────────────────────────────


def _heuristic_judge(
    case: Case,
    resp: Response,
    rubric: Rubric,
    assertions_passed: bool | None,
) -> dict[str, int | None]:
    """Deterministic per-dimension scores from cheap signals."""
    smax = rubric.scale_max
    text = resp.text or ""
    n = len(text)
    lower = text.lower()

    # Base from length: empty -> low, ample length -> high.
    if n == 0:
        length_score = 0.0
    elif n < 40:
        length_score = 0.45
    elif n < 120:
        length_score = 0.75
    else:
        length_score = 0.9

    # Red-flag penalty.
    rf_hits = sum(1 for rf in case.red_flags if rf and rf.lower() in lower)
    rf_penalty = min(0.6, 0.3 * rf_hits)

    # Assertion signal.
    if assertions_passed is True:
        assert_bonus = 0.1
    elif assertions_passed is False:
        assert_bonus = -0.35
    else:
        assert_bonus = 0.0

    error_present = resp.error is not None

    dims: dict[str, int | None] = {}
    for dim in rubric.dimensions:
        if not rubric.applies(dim.name, case.category, case.expected_shape):
            dims[dim.name] = None
            continue
        if error_present:
            frac = 0.1
        else:
            frac = length_score + assert_bonus - rf_penalty
            # Per-dimension flavor so dimensions don't all collapse to one value.
            name_l = dim.name.lower()
            if "safety" in name_l:
                # Safety is high unless red flags present.
                frac = 0.92 - rf_penalty * 1.2 + (0.05 if assertions_passed else 0.0)
            elif "accuracy" in name_l:
                frac = frac - 0.05 * rf_hits
            elif "help" in name_l:
                frac = frac + (0.05 if n >= 120 else 0.0)
        frac = max(0.0, min(1.0, frac))
        dims[dim.name] = int(round(frac * smax))
    return dims


# ─── Ensemble ───────────────────────────────────────────────────────────────


def _ensemble(
    judge_dims: list[dict[str, int | None]],
    rubric: Rubric,
) -> tuple[dict[str, int | None], float | None]:
    """Median per dimension; agreement = fraction of judges within +-1 of median."""
    names = rubric.dimension_names()
    out: dict[str, int | None] = {}
    per_dim_agreement: list[float] = []

    for name in names:
        vals = [d.get(name) for d in judge_dims]
        present = [v for v in vals if v is not None]
        if not present:
            out[name] = None
            continue
        med = median(present)
        out[name] = int(round(med))
        within = sum(1 for v in present if abs(v - med) <= 1)
        per_dim_agreement.append(within / len(present))

    if len(judge_dims) <= 1:
        agreement = None
    elif per_dim_agreement:
        agreement = sum(per_dim_agreement) / len(per_dim_agreement)
    else:
        agreement = None
    return out, agreement


# ─── Main entry ─────────────────────────────────────────────────────────────


async def analyze_run(
    cases: list[Case],
    responses: list[Response],
    rubric: Rubric,
    *,
    client: LLMClient | None = None,
    judges: int = 1,
    model: str | None = None,
    temperature: float = 0.0,
    mock: bool = False,
    concurrency: int = 8,
) -> list[Score]:
    """Grade every case/response pair, returning one Score each (input order)."""
    resp_by_id: dict[str, Response] = {r.case_id: r for r in responses}
    use_mock = mock or client is None
    judges = max(1, judges)
    sem = asyncio.Semaphore(max(1, concurrency))
    _ = model  # accepted for interface symmetry; client already carries its model

    async def grade(case: Case) -> Score:
        async with sem:
            resp = resp_by_id.get(
                case.id, Response(case_id=case.id, error="no response")
            )
            assertion_results, assertions_passed = evaluate_assertions(case, resp)
            has_assertions = len(case.assertions) > 0

            judge_records: list[dict[str, Any]] = []
            judge_dims: list[dict[str, int | None]] = []
            failure_reason: str | None = None
            notes: str | None = None

            if use_mock:
                for _j in range(judges):
                    dims = _heuristic_judge(case, resp, rubric, assertions_passed)
                    judge_dims.append(dims)
                    judge_records.append({"dims": dims, "source": "heuristic"})
            else:
                system = _build_system_prompt(rubric)
                user = _build_user_prompt(case, resp, rubric)
                for _j in range(judges):
                    try:
                        raw = await client.complete(  # type: ignore[union-attr]
                            system=system,
                            user=user,
                            max_tokens=512,
                            temperature=temperature,
                        )
                    except Exception as exc:  # noqa: BLE001 - never abort the batch
                        names = rubric.dimension_names()
                        dims = {n: None for n in names}
                        failure_reason = failure_reason or "analyzer_call_error"
                        notes = notes or f"judge call failed: {exc}"
                        judge_dims.append(dims)
                        judge_records.append({"dims": dims, "error": str(exc)})
                        continue
                    dims, fr, jn = _parse_judge(raw, rubric)
                    if fr is not None:
                        failure_reason = failure_reason or fr
                        notes = notes or jn
                    elif jn is not None and notes is None:
                        notes = jn
                    judge_dims.append(dims)
                    judge_records.append({"dims": dims, "raw": raw})

            ensemble_dims, agreement = _ensemble(judge_dims, rubric)

            # Enforce applicability: force non-applicable dims to None.
            for name in list(ensemble_dims.keys()):
                if not rubric.applies(name, case.category, case.expected_shape):
                    ensemble_dims[name] = None

            score = Score(
                case_id=case.id,
                dimensions=ensemble_dims,
                assertions=assertion_results,
                assertions_passed=(assertions_passed if has_assertions else None),
                failure_reason=failure_reason,
                notes=notes,
                judges=judge_records,
                agreement=agreement,
            )
            score.verdict_pass = case_pass(score, rubric)
            return score

    return await asyncio.gather(*(grade(c) for c in cases))
