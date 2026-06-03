"""`polygraph tune` — scaffold a tailored evaluation project for a domain.

Given a one-line domain description, generate a ready-to-run project directory:

    <out>/
      config.yaml      # wires it together, domain set
      rubric.yaml      # dimensions tailored to the domain
      personas.yaml    # a persona panel specific to the domain
      corpus/*.json     # a starter fixed corpus of domain-specific probes
      README.md

This is the "tune the tool to my use case" workflow: it produces editable
artifacts you refine, then run with `polygraph all --config <out>/config.yaml`.
With an API key it uses the model to tailor everything; offline (`--mock`) it
produces deterministic starter content you can edit by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from . import analyze as A
from . import corpus as C
from . import persona as P
from .config import CorpusConfig

DEFAULT_CATEGORIES = ["core_tasks", "accuracy", "edge_input", "refusal_safety"]


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    s = "".join(keep).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return (s[:48] or "domain")


async def scaffold(
    domain: str,
    out_dir: str,
    *,
    categories: list[str] | None = None,
    count: int = 40,
    n_personas: int = 8,
    adapter_type: str = "demo",
    client=None,
    mock: bool = False,
) -> dict[str, Any]:
    """Generate a tailored project directory for `domain`. Returns a paths dict."""
    categories = categories or DEFAULT_CATEGORIES
    out = Path(out_dir).expanduser()
    (out / "corpus").mkdir(parents=True, exist_ok=True)

    # 1. rubric tailored to the domain
    rubric = await A.generate_rubric(client, domain, categories=categories, mock=mock)
    rubric_dict = {
        "name": rubric.name,
        "threshold": rubric.threshold,
        "scale_max": rubric.scale_max,
        "dimensions": [
            {"name": d.name, "description": d.description, "anchors": d.anchors}
            for d in rubric.dimensions
        ],
        "applicability": rubric.applicability,
        "blocked_shapes": rubric.blocked_shapes,
        "notes": rubric.notes,
    }
    (out / "rubric.yaml").write_text(yaml.safe_dump(rubric_dict, sort_keys=False))

    # 2. persona panel specific to the domain
    panel = await P.generate_panel(client, n_personas, domain, mock=mock)
    (out / "personas.yaml").write_text(
        yaml.safe_dump([p.model_dump() for p in panel], sort_keys=False)
    )

    # 3. starter corpus of domain-specific probes (written as a fixed set)
    cases = C.build_corpus(
        CorpusConfig(mode="varied", count=count, categories=categories, seed=7),
        resolve=lambda x: x, client=client, mock=mock, domain=domain,
    )
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c.model_dump(mode="json", exclude={"id"}))
    for cat, rows in by_cat.items():
        (out / "corpus" / f"{cat}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    # 4. config wiring it together
    config = {
        "name": _slug(domain),
        "domain": domain,
        "adapter": {"type": adapter_type},
        "corpus": {"mode": "fixed", "path": "corpus", "seed": 7},
        "analyze": {"rubric": "rubric.yaml", "judges": 1},
        "audit": {"enabled": True, "forensic": True, "sample_per_category": 3},
        "personas_path": "personas.yaml",
        "out_dir": "polygraph_out",
    }
    (out / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    # 5. readme
    (out / "README.md").write_text(
        f"# {domain}\n\n"
        "Tailored PromptPolygraph project scaffolded by `polygraph tune`.\n\n"
        "Run it:\n\n```bash\n"
        f"polygraph all --config {out.name}/config.yaml --mock --format md,html\n"
        "```\n\n"
        "Edit `rubric.yaml`, `personas.yaml`, and `corpus/*.json` to refine, then "
        "point the `adapter` in `config.yaml` at your real system (http or llm).\n"
    )

    return {
        "dir": str(out),
        "config": str(out / "config.yaml"),
        "rubric": str(out / "rubric.yaml"),
        "personas": str(out / "personas.yaml"),
        "categories": list(by_cat.keys()),
        "cases": len(cases),
        "personas_count": len(panel),
        "dimensions": rubric.dimension_names(),
    }
