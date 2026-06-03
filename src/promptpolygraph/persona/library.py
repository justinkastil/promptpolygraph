"""Persona library: bundled panel of distinct individuals + selection helpers.

The library is package data — one YAML file per persona under
``promptpolygraph/data/personas/`` — loaded via ``importlib.resources`` so it
works whether the package is installed or run from source. Helpers let callers
take a random reproducible sample, select by id, or load a run-specific
``personas.yaml`` from disk.
"""

from __future__ import annotations

import random
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from ..models import Persona

_DATA_PKG = "promptpolygraph.data.personas"


def _coerce_persona(raw: dict[str, Any]) -> Persona | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id", "")).strip()
    who = str(raw.get("who", "")).strip()
    if not pid or not who:
        return None
    return Persona(id=pid, who=who, focus=str(raw.get("focus", "")).strip())


def load_library() -> list[Persona]:
    """Load every ``*.yaml`` persona file bundled in the package data dir."""
    personas: list[Persona] = []
    root = files(_DATA_PKG)
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith((".yaml", ".yml")):
            continue
        data = yaml.safe_load(entry.read_text(encoding="utf-8")) or {}
        p = _coerce_persona(data)
        if p is not None:
            personas.append(p)
    return personas


def sample_pool(
    n: int,
    *,
    seed: int | None = None,
    library: list[Persona] | None = None,
) -> list[Persona]:
    """Return ``n`` distinct personas sampled (reproducibly if seeded)."""
    lib = library if library is not None else load_library()
    n = max(0, min(n, len(lib)))
    rng = random.Random(seed)
    return rng.sample(lib, n)


def select(ids: list[str], library: list[Persona] | None = None) -> list[Persona]:
    """Select personas by id, preserving the order of ``ids``."""
    lib = library if library is not None else load_library()
    by_id = {p.id: p for p in lib}
    return [by_id[i] for i in ids if i in by_id]


def load_personas_file(path: str) -> list[Persona]:
    """Load a run-specific ``personas.yaml`` (a list of {id, who, focus})."""
    data = yaml.safe_load(Path(path).expanduser().read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        # tolerate a {personas: [...]} wrapper
        data = data.get("personas", [])
    personas: list[Persona] = []
    for raw in data or []:
        p = _coerce_persona(raw)
        if p is not None:
            personas.append(p)
    return personas
