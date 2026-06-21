"""Provenance manifest + reference integrity.

Records what produced a result: tool version and dependency versions, the probe
sources used (and their versions), and the standards mapping the OWASP/ATLAS tags
came from. The technique-to-standards mapping is pinned behind a checksum so CI
catches drift instead of a finding's tags changing silently.

Pure-Python and offline: versions from ``importlib.metadata``, hashes from
``hashlib``; nothing is fetched.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from . import __version__
from .redteam.catalog import TECHNIQUES

# Dependencies whose version is worth recording for reproducibility/audit.
_TRACKED_DEPS = (
    "anthropic", "httpx", "pydantic", "pyyaml", "jsonschema", "jmespath",
    "python-docx", "jinja2", "openai", "garak", "pyrit", "deepteam",
    "datasets", "huggingface-hub",
)

# Where the committed reference lock lives (shipped in the wheel).
_LOCK_PATH = Path(__file__).parent / "data" / "references.lock.json"


def _dep_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── tool + environment ───────────────────────────────────────────────────────

def tool_provenance() -> dict[str, Any]:
    """Tool version, interpreter, platform, and tracked dependency versions."""
    deps = {n: v for n in _TRACKED_DEPS if (v := _dep_version(n)) is not None}
    return {
        "tool": "promptpolygraph",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "dependencies": deps,
    }


# ── reference integrity (technique → standards mapping) ───────────────────────

def reference_manifest() -> dict[str, Any]:
    """The full technique→OWASP/ATLAS mapping plus a stable checksum.

    Each technique carries a content checksum over its benign seed templates, so
    a probe library change is visible; ``mapping_hash`` is the checksum over the
    whole id→(owasp,atlas) table — the single value a lock pins.
    """
    techniques = []
    mapping_pairs = []
    for t in sorted(TECHNIQUES, key=lambda x: x.id):
        seed_blob = json.dumps(list(t.seeds), ensure_ascii=False, sort_keys=True)
        techniques.append({
            "id": t.id, "name": t.name, "strategy": t.strategy,
            "owasp": t.owasp, "atlas": t.atlas,
            "probe_checksum": _sha256(seed_blob)[:16],
        })
        mapping_pairs.append([t.id, t.owasp, t.atlas])
    mapping_hash = _sha256(json.dumps(mapping_pairs, sort_keys=True, ensure_ascii=False))
    return {
        "techniques": techniques,
        "mapping_hash": mapping_hash,
        "owasp_categories": sorted({t.owasp for t in TECHNIQUES if t.owasp}),
        "atlas_techniques": sorted({t.atlas for t in TECHNIQUES if t.atlas}),
        "count": len(techniques),
    }


def unmapped_techniques() -> list[str]:
    """Technique ids missing an OWASP or ATLAS tag — CI should treat these as a
    reference-integrity failure (a finding with no sourced standard)."""
    return [t.id for t in TECHNIQUES if not t.owasp or not t.atlas]


def write_reference_lock(path: str | Path | None = None) -> str:
    """Write the current reference manifest to the lock file. Run intentionally
    when a mapping changes; the drift check compares against this committed file."""
    p = Path(path) if path else _LOCK_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reference_manifest(), indent=2, sort_keys=True) + "\n")
    return str(p)


def check_reference_integrity(path: str | Path | None = None) -> dict[str, Any]:
    """Compare the live mapping against the committed lock. Returns
    {ok, reason, expected, actual, unmapped}. ``ok`` is False on drift or any
    unmapped technique."""
    p = Path(path) if path else _LOCK_PATH
    current = reference_manifest()
    unmapped = unmapped_techniques()
    if unmapped:
        return {"ok": False, "reason": f"techniques missing a standard tag: {', '.join(unmapped)}",
                "expected": None, "actual": current["mapping_hash"], "unmapped": unmapped}
    if not p.exists():
        return {"ok": False, "reason": f"no reference lock at {p} (run `polygraph references --write`)",
                "expected": None, "actual": current["mapping_hash"], "unmapped": []}
    locked = json.loads(p.read_text())
    expected = locked.get("mapping_hash")
    if expected != current["mapping_hash"]:
        return {"ok": False, "reason": "OWASP/ATLAS mapping drifted from the committed lock",
                "expected": expected, "actual": current["mapping_hash"], "unmapped": []}
    return {"ok": True, "reason": "mapping matches the committed lock",
            "expected": expected, "actual": current["mapping_hash"], "unmapped": []}


# ── source provenance ─────────────────────────────────────────────────────────

# Probe sources -> the distribution that backs them (None for the built-in).
_SOURCE_PACKAGE = {
    "catalog": None, "garak": "garak", "pyrit": "pyrit",
    "deepteam": "deepteam", "dataset": "datasets", "datasets": "datasets",
}


def source_provenance(names: list[str] | None) -> list[dict[str, Any]]:
    """For each named source: availability + backing package version."""
    out: list[dict[str, Any]] = []
    for raw in names or []:
        key = str(raw).split(":")[0]
        pkg = _SOURCE_PACKAGE.get(key, key)
        version = _dep_version(pkg) if pkg else "built-in"
        out.append({
            "source": raw,
            "kind": "built-in" if pkg is None else "oss",
            "package": pkg,
            "version": version,
            "available": pkg is None or version is not None,
        })
    return out


# ── run manifests ──────────────────────────────────────────────────────────

def eval_provenance(run_meta: Any, config: Any | None = None) -> dict[str, Any]:
    """Provenance for an evaluation run: identity fingerprints + backend + tool."""
    backend = None
    seed = None
    if config is not None:
        llm = getattr(config, "llm", None)
        backend = {"provider": getattr(llm, "provider", None),
                   "model": getattr(config, "model", None)} if llm else None
        seed = getattr(getattr(config, "corpus", None), "seed", None)
    return {
        "schema_version": 1,
        "kind": "eval",
        "run_id": getattr(run_meta, "run_id", None),
        "created_at": getattr(run_meta, "created_at", None),
        "mode": getattr(run_meta, "mode", None),
        "fingerprints": {
            "corpus": getattr(run_meta, "corpus_fingerprint", None),
            "rubric": getattr(run_meta, "rubric_fingerprint", None),
            "config": getattr(run_meta, "config_fingerprint", None),
        },
        "seed": seed,
        "sut": {"git_sha": getattr(run_meta, "sut_git_sha", None),
                "ref": getattr(run_meta, "sut_ref", None)},
        "backend": backend,
        "tool": tool_provenance(),
    }


def redteam_provenance(report: Any, *, sources: list[str] | None = None) -> dict[str, Any]:
    """Provenance for a red-team run: profile, sources+versions, and the pinned
    reference mapping the OWASP/ATLAS tags were drawn from."""
    ref = reference_manifest()
    profile_sources = sources if sources is not None else (report.stats or {}).get("sources")
    return {
        "schema_version": 1,
        "kind": "redteam",
        "run_id": getattr(report, "run_id", None),
        "profile": getattr(report, "profile", None),
        "target": getattr(report, "target", None),
        "sources": source_provenance(profile_sources),
        "reference": {
            "mapping_hash": ref["mapping_hash"],
            "owasp_categories": ref["owasp_categories"],
            "atlas_techniques": ref["atlas_techniques"],
            "technique_count": ref["count"],
        },
        "tool": tool_provenance(),
    }
