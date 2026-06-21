"""Detect train/test contamination and judge-circularity in an eval corpus.

Three independent checks, each additive and deterministic:

  1. reference overlap   — corpus prompts that exactly match, or are near-
     duplicates of (normalized token-set Jaccard above a threshold), entries in
     a user-supplied reference dataset. A high overlap rate means the eval set
     leaks into training/reference material and scores are inflated.
  2. judge circularity   — the model that generated the corpus is also the judge
     that grades it, so generation and grading share the same priors and the
     verdict is self-referential.
  3. seed-bank leakage    — eval cases that are near-duplicates of seed-bank
     entries; generation was meant to produce NEW prompts, not echo the seeds.

`check_contamination` returns a plain report dict plus a human-readable caveat
string. Verdict only; the CLI decides exit codes (non-zero is opt-in via
--strict). Everything runs offline with no LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from promptpolygraph.models import Case

# Default token-set Jaccard above which two prompts are "near-duplicates".
# Empirically separates paraphrases/templated variants from genuinely distinct
# prompts; exposed as a parameter so callers can tighten or loosen it.
_DEFAULT_THRESHOLD = 0.8

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    """Normalized token set: lowercased alphanumeric runs, punctuation dropped.

    A set (not a bag) so word order and repetition do not affect the match —
    paraphrase and reordering are exactly the contamination we want to catch.
    """
    return frozenset(_TOKEN_RE.findall(text.lower()))


def _normalized(text: str) -> str:
    """Whitespace/case-normalized form for the exact-match pass."""
    return " ".join(text.lower().split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def _read_reference_lines(path: str) -> list[str]:
    """Reference dataset is a newline-delimited file of prompt strings.

    Blank lines are skipped so a trailing newline does not register as an empty
    reference entry that everything trivially matches.
    """
    from pathlib import Path

    raw = Path(path).expanduser().read_text(encoding="utf-8")
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _best_match(
    case_tokens: frozenset[str],
    case_norm: str,
    ref_index: Sequence[tuple[str, frozenset[str]]],
    threshold: float,
) -> tuple[str, float] | None:
    """Closest reference entry to a case, or None if below threshold.

    Exact (normalized) equality short-circuits at similarity 1.0; otherwise the
    highest token-set Jaccard wins and must clear `threshold`.
    """
    best_text: str | None = None
    best_sim = 0.0
    for ref_norm, ref_tokens in ref_index:
        if ref_norm == case_norm:
            return ref_norm, 1.0
        sim = _jaccard(case_tokens, ref_tokens)
        if sim > best_sim:
            best_sim, best_text = sim, ref_norm
    if best_text is not None and best_sim >= threshold:
        return best_text, best_sim
    return None


def _overlap_check(
    cases: Sequence[Case],
    reference: Sequence[str],
    threshold: float,
) -> dict[str, Any]:
    ref_index = [(_normalized(r), _tokens(r)) for r in reference]
    matches: list[dict[str, Any]] = []
    for case in cases:
        hit = _best_match(_tokens(case.prompt), _normalized(case.prompt), ref_index, threshold)
        if hit is None:
            continue
        ref_text, sim = hit
        matches.append(
            {
                "case_id": case.id,
                "category": case.category,
                "similarity": round(sim, 4),
                "exact": sim >= 1.0,
                "reference": ref_text,
            }
        )
    n = len(cases)
    return {
        "checked": n,
        "reference_size": len(reference),
        "overlap_count": len(matches),
        "overlap_rate": round(len(matches) / n, 4) if n else 0.0,
        "exact_count": sum(1 for m in matches if m["exact"]),
        "threshold": threshold,
        "matches": matches,
    }


def _seed_leak_check(
    cases: Sequence[Case],
    seed_bank: Sequence[dict],
    threshold: float,
) -> dict[str, Any]:
    seeds = [str(s.get("prompt", "")) for s in seed_bank if s.get("prompt")]
    seed_index = [(_normalized(s), _tokens(s)) for s in seeds]
    leaked: list[dict[str, Any]] = []
    for case in cases:
        hit = _best_match(_tokens(case.prompt), _normalized(case.prompt), seed_index, threshold)
        if hit is None:
            continue
        seed_text, sim = hit
        leaked.append(
            {
                "case_id": case.id,
                "category": case.category,
                "similarity": round(sim, 4),
                "exact": sim >= 1.0,
                "seed": seed_text,
            }
        )
    n = len(cases)
    return {
        "checked": n,
        "seed_bank_size": len(seeds),
        "leak_count": len(leaked),
        "leak_rate": round(len(leaked) / n, 4) if n else 0.0,
        "threshold": threshold,
        "leaks": leaked,
    }


def _circularity_check(
    gen_model: str | None,
    judge_model: str | None,
) -> dict[str, Any]:
    """Same-model warning: corpus generator == judge -> circular influence."""
    same = bool(gen_model) and bool(judge_model) and gen_model == judge_model
    return {
        "generation_model": gen_model,
        "judge_model": judge_model,
        "same_model": same,
    }


def _build_caveat(report: dict[str, Any]) -> str:
    """One-line-per-finding caveat for reports; empty-clean when nothing fires."""
    lines: list[str] = []
    ov = report["reference_overlap"]
    if ov["overlap_count"]:
        lines.append(
            f"{ov['overlap_count']}/{ov['checked']} corpus prompts "
            f"({ov['overlap_rate']:.0%}) overlap the reference dataset "
            f"({ov['exact_count']} exact); scores on those cases may be inflated."
        )
    circ = report["judge_circularity"]
    if circ["same_model"]:
        lines.append(
            f"corpus generator and judge are the same model "
            f"({circ['judge_model']}); grading is self-referential and "
            "agreement is not independent confirmation."
        )
    seed = report["seed_leakage"]
    if seed["leak_count"]:
        lines.append(
            f"{seed['leak_count']}/{seed['checked']} cases are near-duplicates "
            "of seed-bank entries; generation echoed the seeds rather than "
            "producing novel prompts."
        )
    if not lines:
        return "No contamination signals detected."
    return " ".join(lines)


def check_contamination(
    cases: Iterable[Case],
    *,
    reference: Sequence[str] | None = None,
    reference_path: str | None = None,
    seed_bank: Sequence[dict] | None = None,
    generation_model: str | None = None,
    judge_model: str | None = None,
    threshold: float = _DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Run all three contamination checks and return a report dict.

    `reference` is a list of prompt strings, or `reference_path` a newline-
    delimited file of them (the list wins if both are given). `seed_bank` is the
    list of seed dicts used during generation. `generation_model` and
    `judge_model` drive the circularity check. `threshold` is the Jaccard cutoff
    for near-duplicate matching.

    The returned dict carries `reference_overlap`, `judge_circularity`,
    `seed_leakage`, a top-level `contaminated` flag (any signal fired), and a
    `caveat` string. No exit code is implied; callers gate as they see fit.
    """
    case_list = list(cases)

    refs: list[str] = list(reference) if reference is not None else []
    if not refs and reference_path:
        refs = _read_reference_lines(reference_path)

    overlap = _overlap_check(case_list, refs, threshold)
    circ = _circularity_check(generation_model, judge_model)
    seed = _seed_leak_check(case_list, list(seed_bank or []), threshold)

    report: dict[str, Any] = {
        "reference_overlap": overlap,
        "judge_circularity": circ,
        "seed_leakage": seed,
    }
    report["contaminated"] = bool(
        overlap["overlap_count"] or circ["same_model"] or seed["leak_count"]
    )
    report["caveat"] = _build_caveat(report)
    return report
