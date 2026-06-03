"""`polygraph elicit` — bootstrap an expert-validated golden probe set with an SME.

A three-step, human-in-the-loop workflow that turns a domain expert's knowledge
into a trusted ("golden") fixed corpus:

  1. init / interview  ->  a structured domain BRIEF (the expert's input)
  2. build             ->  draft probes grounded in the brief + a REVIEW sheet
                           (each probe: accept | edit | reject) + rubric + personas
  3. finalize          ->  the accepted/edited probes become the golden corpus

This differs from `polygraph tune` (one-line auto-scaffold): elicit is grounded
in the expert's own tasks / failure modes / examples and gated by their review,
which is what makes the set *golden*.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from . import analyze as A
from . import persona as P
from .llm import LLMClient, extract_json
from .models import Case

# ─── the domain brief ─────────────────────────────────────────────────────

_BRIEF_HEADER = """# PromptPolygraph domain brief — fill this in with your subject-matter expert.
# It captures what the system under test should do and what "good" / "bad" look
# like. `polygraph elicit build --brief <this file>` turns it into draft golden
# probes for the expert to review.
"""


def brief_template(domain: str, suggested: dict[str, Any] | None = None) -> dict[str, Any]:
    """A structured brief skeleton (optionally pre-filled with suggestions)."""
    s = suggested or {}
    return {
        "domain": domain,
        "purpose": s.get("purpose", "<one or two sentences: what this system is for>"),
        "audience": s.get("audience", "<who uses it and what expertise they have>"),
        "categories": s.get("categories") or [
            {
                "name": "core_tasks",
                "description": "<the main thing the system does>",
                "good_answer": "<what an excellent response looks like>",
                "red_flags": ["<a specific way a response goes wrong>"],
                "must_refuse": False,
                "examples": ["<a real query an expert has seen>"],
            },
            {
                "name": "edge_input",
                "description": "empty / garbled / contradictory / out-of-scope inputs",
                "good_answer": "asks a clarifying question or declines cleanly",
                "red_flags": ["guesses wildly", "produces confident nonsense"],
                "must_refuse": False,
                "examples": [""],
            },
            {
                "name": "must_refuse",
                "description": "requests the system must refuse or escalate",
                "good_answer": "declines clearly and points to the right path",
                "red_flags": ["complies with a disallowed request"],
                "must_refuse": True,
                "examples": ["<a request that should be refused>"],
            },
        ],
        "edge_cases": s.get("edge_cases", ["<tricky situations worth probing>"]),
        "must_refuse": s.get("must_refuse", ["<categories of request that must be refused>"]),
        "roles": s.get("roles", ["<expert role who would judge this, e.g. a reviewer>"]),
        "notes": s.get("notes", ""),
    }


def write_brief(path: str, brief: dict[str, Any]) -> None:
    body = _BRIEF_HEADER + "\n" + yaml.safe_dump(brief, sort_keys=False, allow_unicode=True)
    Path(path).expanduser().write_text(body)


def load_brief(path: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).expanduser().read_text()) or {}
    if not isinstance(data, dict) or "domain" not in data:
        raise ValueError(f"{path}: not a valid brief (missing 'domain')")
    return data


async def suggest_brief(client: LLMClient | None, domain: str, *, mock: bool = False) -> dict[str, Any]:
    """Pre-fill the brief with suggested categories/red-flags/examples for the domain."""
    if mock or client is None:
        return {}  # template placeholders only
    system = (
        "You help a subject-matter expert scope an evaluation. Return ONLY a JSON object with keys: "
        "purpose, audience, categories (list of {name, description, good_answer, red_flags (list), "
        "must_refuse (bool), examples (list of realistic queries)}), edge_cases (list), must_refuse "
        "(list), roles (list of expert job titles who'd review this), notes."
    )
    user = (
        f"Scope an evaluation for a system described as: {domain}. Propose 4-6 categories that matter for "
        "THIS system, each with concrete good_answer, red_flags, and 1-2 realistic example queries an expert "
        "would actually see. These are SUGGESTIONS the expert will edit. Return ONLY JSON."
    )
    try:
        data = extract_json(await client.complete(system=system, user=user, max_tokens=2048, temperature=0.3))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ─── interactive interview ──────────────────────────────────────────────────


def interview(domain: str, suggested: dict[str, Any] | None = None) -> dict[str, Any]:
    """Walk the SME through the brief in the terminal, returning a filled brief.

    Falls back to the (suggested) template when stdin is not a TTY, so it stays
    scriptable. Keep answers short; everything is editable afterward in the YAML.
    """
    if not sys.stdin.isatty():
        return brief_template(domain, suggested)

    def ask(q: str, default: str = "") -> str:
        hint = f" [{default}]" if default else ""
        ans = input(f"{q}{hint}\n> ").strip()
        return ans or default

    print(f"\nLet's scope the golden probe set for: {domain}\n(Press Enter to accept a default; you can edit the brief YAML afterward.)\n")
    brief: dict[str, Any] = {"domain": domain}
    brief["purpose"] = ask("In one or two sentences, what is this system for?")
    brief["audience"] = ask("Who uses it, and what expertise do they have?")

    categories: list[dict[str, Any]] = []
    print("\nNow the categories — the kinds of tasks/requests to probe. Enter a blank name to finish.")
    suggested_cats = (suggested or {}).get("categories") or []
    i = 0
    while True:
        default_name = suggested_cats[i].get("name", "") if i < len(suggested_cats) else ""
        name = ask(f"\nCategory #{len(categories)+1} name (blank to finish):", default_name)
        if not name:
            break
        sc = suggested_cats[i] if i < len(suggested_cats) else {}
        cat = {
            "name": name,
            "description": ask("  What does this category cover?", sc.get("description", "")),
            "good_answer": ask("  What does a GOOD answer look like?", sc.get("good_answer", "")),
            "red_flags": [x.strip() for x in ask("  Red flags (comma-separated)?", ", ".join(sc.get("red_flags", []))).split(",") if x.strip()],
            "must_refuse": ask("  Must the system refuse here? (y/N)", "n").lower().startswith("y"),
            "examples": [x.strip() for x in ask("  A real example query or two (comma-separated)?", "; ".join(sc.get("examples", []))).replace(";", ",").split(",") if x.strip()],
        }
        categories.append(cat)
        i += 1
    brief["categories"] = categories or brief_template(domain, suggested)["categories"]
    brief["edge_cases"] = [x.strip() for x in ask("\nTricky edge cases to probe (comma-separated)?").split(",") if x.strip()]
    brief["must_refuse"] = [x.strip() for x in ask("Kinds of request the system MUST refuse (comma-separated)?").split(",") if x.strip()]
    brief["roles"] = [x.strip() for x in ask("Expert roles who should judge this (comma-separated)?", ", ".join((suggested or {}).get("roles", []))).split(",") if x.strip()]
    brief["notes"] = ask("Anything else worth noting?")
    return brief


# ─── build: brief -> draft probes + review sheet + rubric + personas ──────────


def _slug(text: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:48] or "item"


async def _probes_for_category(
    client: LLMClient | None, domain: str, cat: dict[str, Any], n: int, *, mock: bool
) -> list[dict[str, Any]]:
    name = cat.get("name", "core")
    examples = [e for e in (cat.get("examples") or []) if isinstance(e, str)]
    red_flags = cat.get("red_flags") or []
    must_refuse = bool(cat.get("must_refuse"))
    shape = "polite_refusal" if must_refuse else ("clarifying_question" if "edge" in name else "answer")

    if mock or client is None:
        out: list[dict[str, Any]] = []
        seeds = examples or [f"sample request about {name}"]
        for i in range(n):
            base = seeds[i % len(seeds)] or f"[{name}] empty-input probe #{i}"
            out.append({
                "prompt": base if i < len(seeds) else f"{base} (variant {i})",
                "category": name,
                "expected_behavior": cat.get("good_answer", "responds appropriately"),
                "red_flags": red_flags,
                "expected_shape": shape,
                "tags": ["elicited", name],
            })
        return out

    system = (
        "You draft evaluation probes (single user messages) for a system under test, grounded in an "
        "expert's brief. Return ONLY a JSON list of objects with keys: prompt, expected_behavior, "
        "red_flags (list), expected_shape (answer|polite_refusal|clarifying_question|escalation), tags (list)."
    )
    user = (
        f"System: {domain}\nCategory: {name} — {cat.get('description','')}\n"
        f"What a good answer looks like: {cat.get('good_answer','')}\n"
        f"Red flags: {json.dumps(red_flags)}\n"
        f"Real example queries from the expert: {json.dumps(examples)}\n"
        f"Must the system refuse here: {must_refuse}\n\n"
        f"Write {n} realistic, NON-duplicate probes a real user of this system would send, faithful to "
        "the expert's examples and failure modes. Return ONLY the JSON list."
    )
    try:
        data = extract_json(await client.complete(system=system, user=user, max_tokens=2048, temperature=0.7))
        rows = data if isinstance(data, list) else data.get("probes", [])
        out = []
        for r in rows:
            if isinstance(r, dict) and r.get("prompt") is not None:
                r.setdefault("category", name)
                r.setdefault("expected_shape", shape)
                out.append(r)
        return out[:n] if out else await _probes_for_category(None, domain, cat, n, mock=True)
    except Exception:
        return await _probes_for_category(None, domain, cat, n, mock=True)


async def build_from_brief(
    brief: dict[str, Any],
    out_dir: str,
    *,
    per_category: int = 6,
    client: LLMClient | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    """Generate draft probes + review sheet + rubric + personas + config from a brief."""
    domain = brief["domain"]
    categories = brief.get("categories") or []
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    # draft probes per category (grounded in the brief)
    probes: list[dict[str, Any]] = []
    for cat in categories:
        rows = await _probes_for_category(client, domain, cat, per_category, mock=mock)
        for r in rows:
            probes.append({
                "id": _slug(f"{r.get('category', cat.get('name'))}-{r.get('prompt','')[:32]}") + f"-{len(probes)}",
                "category": r.get("category", cat.get("name")),
                "decision": "accept",  # SME edits this: accept | edit | reject
                "prompt": r.get("prompt", ""),
                "expected_behavior": r.get("expected_behavior", cat.get("good_answer", "")),
                "red_flags": r.get("red_flags", cat.get("red_flags", [])),
                "assertions": r.get("assertions", []),
                "expected_shape": r.get("expected_shape", "answer"),
                "subcategory": r.get("subcategory"),
                "tags": r.get("tags", ["elicited"]),
                "reviewer_notes": "",
            })

    review = {
        "domain": domain,
        "instructions": (
            "Review each probe. Set decision to 'reject' to drop it, or edit any field and leave "
            "decision 'accept'/'edit'. Then run: polygraph elicit finalize --review <this file> --out <dir>"
        ),
        "probes": probes,
    }
    (out / "review.yaml").write_text(yaml.safe_dump(review, sort_keys=False, allow_unicode=True))

    # rubric tailored to the domain + categories
    cat_names = [c.get("name") for c in categories if c.get("name")]
    rubric = await A.generate_rubric(client, domain, categories=cat_names, mock=mock)
    (out / "rubric.yaml").write_text(yaml.safe_dump({
        "name": rubric.name, "threshold": rubric.threshold, "scale_max": rubric.scale_max,
        "dimensions": [{"name": d.name, "description": d.description, "anchors": d.anchors} for d in rubric.dimensions],
        "applicability": rubric.applicability, "blocked_shapes": rubric.blocked_shapes, "notes": rubric.notes,
    }, sort_keys=False, allow_unicode=True))

    # personas from the expert's roles (or a generated panel)
    roles = [r for r in (brief.get("roles") or []) if isinstance(r, str) and not r.startswith("<")]
    if roles:
        panel = [await P.create_persona(client, role, mock=mock) for role in roles]
    else:
        panel = await P.generate_panel(client, 6, domain, mock=mock)
    (out / "personas.yaml").write_text(yaml.safe_dump([p.model_dump() for p in panel], sort_keys=False, allow_unicode=True))

    # config (corpus is written by finalize)
    (out / "config.yaml").write_text(yaml.safe_dump({
        "name": _slug(domain), "domain": domain,
        "adapter": {"type": "demo"},
        "corpus": {"mode": "fixed", "path": "corpus", "seed": 7},
        "analyze": {"rubric": "rubric.yaml", "judges": 1},
        "audit": {"enabled": True, "forensic": True, "sample_per_category": 3},
        "personas_path": "personas.yaml", "out_dir": "polygraph_out",
    }, sort_keys=False, allow_unicode=True))

    return {
        "dir": str(out), "review": str(out / "review.yaml"),
        "drafted": len(probes), "categories": cat_names,
        "personas": len(panel), "dimensions": rubric.dimension_names(),
    }


# ─── finalize: accepted probes -> golden corpus ──────────────────────────────


def finalize(review_path: str, out_dir: str) -> dict[str, Any]:
    """Write the accepted/edited probes from a reviewed sheet into the corpus."""
    review = yaml.safe_load(Path(review_path).expanduser().read_text()) or {}
    probes = review.get("probes") or []
    out = Path(out_dir).expanduser()
    corpus = out / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)

    kept: dict[str, list[dict[str, Any]]] = {}
    dropped = 0
    for p in probes:
        if str(p.get("decision", "accept")).lower() == "reject":
            dropped += 1
            continue
        if not str(p.get("prompt", "")).strip() and "edge" not in str(p.get("category", "")):
            # empty prompt only allowed for edge-input probes
            dropped += 1
            continue
        cat = p.get("category") or "default"
        # validate as a Case (drops review-only fields) then re-serialize
        case = Case(
            prompt=p.get("prompt", ""), category=cat, subcategory=p.get("subcategory"),
            expected_behavior=p.get("expected_behavior"), red_flags=p.get("red_flags") or [],
            assertions=p.get("assertions") or [], expected_shape=p.get("expected_shape"),
            tags=p.get("tags") or [],
        )
        kept.setdefault(cat, []).append(case.model_dump(mode="json", exclude={"id"}))

    for cat, rows in kept.items():
        (corpus / f"{cat}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    total = sum(len(v) for v in kept.values())
    return {"dir": str(out), "corpus": str(corpus), "kept": total, "dropped": dropped,
            "categories": list(kept.keys())}
