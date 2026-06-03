"""Load a fixed corpus of probe cases from disk.

A corpus on disk is a directory of `<category>.json` files; each file is a JSON
list of case dicts. The file stem supplies the default category for the cases
it contains. A single `.json` file is also accepted (its stem is the category).
Pydantic coerces nested `assertions` dicts into `AssertionSpec` objects.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from promptpolygraph.models import Case


def _content_id(category: str, prompt: str) -> str:
    """A stable id derived from the case content.

    Fixed corpora must yield the SAME case id run-over-run so resume, the
    response cache, baselines, and A/B comparison all align two runs of the
    same corpus by case rather than by a fresh random UUID each run.
    """
    return hashlib.sha256(f"{category}\n{prompt}".encode("utf-8")).hexdigest()[:32]


def _build_case(raw: dict[str, Any], default_category: str) -> Case:
    data = dict(raw)
    data.setdefault("category", default_category)
    # A case may pin its own id; otherwise derive a stable one from content.
    if not data.get("id"):
        data["id"] = _content_id(data["category"], data.get("prompt", ""))
    # Pydantic v2 will coerce the assertion dicts into AssertionSpec.
    return Case(**data)


def _load_file(path: Path) -> list[Case]:
    default_category = path.stem
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list of case dicts")
    return [_build_case(item, default_category) for item in payload]


def load_corpus(
    path: str,
    *,
    categories: list[str] | None = None,
    per_category: int | None = None,
    count: int | None = None,
) -> list[Case]:
    """Load a directory of `<category>.json` files (or one `.json` file).

    Cases are returned in a deterministic order: sorted by category, then in
    each file's original order. `categories` filters which categories load;
    `per_category` caps each category; `count` caps the grand total.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"corpus path does not exist: {p}")

    files: list[Path]
    if p.is_file():
        files = [p]
    else:
        files = sorted(f for f in p.glob("*.json") if f.is_file())

    # Group cases by category, preserving file order within each category.
    by_category: dict[str, list[Case]] = {}
    for f in files:
        for case in _load_file(f):
            by_category.setdefault(case.category, []).append(case)

    if categories is not None:
        wanted = set(categories)
        by_category = {k: v for k, v in by_category.items() if k in wanted}

    if per_category is not None:
        by_category = {k: v[:per_category] for k, v in by_category.items()}

    cases: list[Case] = []
    for category in sorted(by_category):
        cases.extend(by_category[category])

    if count is not None:
        cases = cases[:count]

    return cases
