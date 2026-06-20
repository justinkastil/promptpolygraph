"""Supply-chain CI guarantees: pip-audit gate, SBOM, release attestations.

Structural checks over the workflow YAML and docs so the supply-chain controls
cannot be silently dropped.
"""

from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def _step_runs(job: dict) -> str:
    """Concatenate every `run` block and `uses` ref in a job's steps."""
    parts = []
    for step in job.get("steps", []):
        if "run" in step:
            parts.append(step["run"])
        if "uses" in step:
            parts.append(step["uses"])
    return "\n".join(parts)


def test_workflows_parse():
    assert _load(CI)
    assert _load(PUBLISH)


def test_ci_has_pip_audit_gate():
    ci = _load(CI)
    audit = ci["jobs"]["audit"]
    runs = _step_runs(audit)
    assert "pip-audit" in runs
    # Documented ignore list is honored by the gate.
    assert ".pip-audit-ignore" in runs


def test_ci_build_emits_sbom_artifact():
    ci = _load(CI)
    build = ci["jobs"]["build"]
    runs = _step_runs(build)
    assert "cyclonedx-py environment" in runs
    upload_names = [
        s.get("with", {}).get("name")
        for s in build["steps"]
        if "actions/upload-artifact" in str(s.get("uses", ""))
    ]
    assert "sbom" in upload_names


def test_publish_grants_attestation_permission():
    pub = _load(PUBLISH)
    perms = pub["jobs"]["pypi"]["permissions"]
    assert perms.get("attestations") == "write"
    assert perms.get("contents") == "write"  # release asset upload


def test_publish_produces_attestations_and_attaches_sbom():
    pub = _load(PUBLISH)
    job = pub["jobs"]["pypi"]
    uses = [s.get("uses", "") for s in job["steps"]]
    assert any("attest-build-provenance" in u for u in uses)

    publish_step = next(
        s for s in job["steps"] if "gh-action-pypi-publish" in str(s.get("uses", ""))
    )
    assert publish_step.get("with", {}).get("attestations") is True

    runs = _step_runs(job)
    assert "gh release upload" in runs
    assert "sbom.cdx.json" in runs


def test_supply_chain_doc_present():
    doc = (ROOT / "docs" / "SUPPLY_CHAIN.md").read_text()
    assert "gh attestation verify" in doc
    assert "sbom.cdx.json" in doc
