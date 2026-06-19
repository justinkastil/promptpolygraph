"""JSON Schema generation + config validation.

The config and rubric are Pydantic models, so their JSON Schema is free and
always in sync with the code. Two uses:

1. ``polygraph schema`` writes the schemas to disk; dropping a
   ``# yaml-language-server: $schema=...`` line at the top of a config gives
   live autocomplete + inline validation in any YAML-LS editor (VS Code, etc.).
2. ``polygraph validate-config`` fails fast — *before* a run spends tokens — on a
   malformed config or rubric, with a precise dotted path to each error, and
   warns on unknown top-level keys (which the tolerant loader would silently
   ignore, so a typo'd key goes unnoticed without this check).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .config import Config
from .models import Rubric

# The yaml-language-server directive that wires editor validation to a schema.
_YLS = "# yaml-language-server: $schema={uri}"


def config_schema() -> dict[str, Any]:
    return Config.model_json_schema()


def rubric_schema() -> dict[str, Any]:
    return Rubric.model_json_schema()


def write_schemas(out_dir: str | Path) -> dict[str, str]:
    """Write config + rubric JSON Schemas into `out_dir`; return {name: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, schema in (("config", config_schema()), ("rubric", rubric_schema())):
        p = out / f"{name}.schema.json"
        p.write_text(json.dumps(schema, indent=2) + "\n")
        written[name] = str(p)
    return written


def _flatten_errors(exc: Any) -> list[str]:
    """Turn a pydantic ValidationError into precise 'path: message' lines."""
    lines: list[str] = []
    try:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
            lines.append(f"{loc}: {err.get('msg', 'invalid')}")
    except Exception:
        lines.append(str(exc))
    return lines


def validate_config_file(path: str | Path) -> dict[str, Any]:
    """Validate a config YAML file. Returns a result dict::

        {"ok": bool, "errors": [str], "warnings": [str]}

    `ok` is False on a structural/type error. Unknown top-level keys are a
    warning (the loader ignores them, so this surfaces likely typos).
    """
    from pydantic import ValidationError

    p = Path(path)
    if not p.exists():
        return {"ok": False, "errors": [f"file not found: {p}"], "warnings": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        return {"ok": False, "errors": [f"YAML parse error: {e}"], "warnings": []}
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["top-level config must be a mapping"], "warnings": []}

    warnings: list[str] = []
    known = set(Config.model_fields.keys())
    for key in data:
        if key not in known:
            warnings.append(f"unknown top-level key '{key}' (ignored — possible typo)")

    try:
        Config(**data)
    except ValidationError as e:
        return {"ok": False, "errors": _flatten_errors(e), "warnings": warnings}
    return {"ok": True, "errors": [], "warnings": warnings}


def validate_rubric_file(path: str | Path) -> dict[str, Any]:
    """Validate a rubric YAML file against the Rubric model."""
    from pydantic import ValidationError

    p = Path(path)
    if not p.exists():
        return {"ok": False, "errors": [f"file not found: {p}"], "warnings": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        return {"ok": False, "errors": [f"YAML parse error: {e}"], "warnings": []}
    try:
        Rubric(**data)
    except ValidationError as e:
        return {"ok": False, "errors": _flatten_errors(e), "warnings": []}
    return {"ok": True, "errors": [], "warnings": []}


def schema_comment(uri: str) -> str:
    """The yaml-language-server directive line for editor validation."""
    return _YLS.format(uri=uri)
