"""Provenance manifest + pinned reference (OWASP/ATLAS) integrity."""

from __future__ import annotations

import asyncio
import json

from promptpolygraph import provenance as P
from promptpolygraph.adapters.demo import DemoAdapter
from promptpolygraph.models import RunMeta
from promptpolygraph.redteam.orchestrator import run_redteam
from promptpolygraph.redteam.profiles import get_profile


def test_tool_provenance_shape():
    tp = P.tool_provenance()
    assert tp["tool"] == "promptpolygraph" and tp["version"]
    assert tp["python"] and tp["platform"]
    # core deps that are always installed must be pinned
    assert "pydantic" in tp["dependencies"] and "httpx" in tp["dependencies"]


def test_reference_manifest_stable_and_mapped():
    m = P.reference_manifest()
    assert m["count"] >= 10 and m["mapping_hash"]
    # deterministic
    assert P.reference_manifest()["mapping_hash"] == m["mapping_hash"]
    # every technique carries both standards tags + a probe checksum
    for t in m["techniques"]:
        assert t["owasp"] and t["atlas"] and t["probe_checksum"]


def test_no_unmapped_techniques():
    assert P.unmapped_techniques() == []


def test_committed_lock_matches_live_mapping():
    res = P.check_reference_integrity()
    assert res["ok"] is True, res["reason"]


def test_reference_drift_is_detected(tmp_path):
    bad = tmp_path / "lock.json"
    bad.write_text(json.dumps({"mapping_hash": "deadbeef"}))
    res = P.check_reference_integrity(bad)
    assert res["ok"] is False and "drift" in res["reason"].lower()
    assert res["expected"] == "deadbeef"


def test_write_lock_roundtrip(tmp_path):
    p = tmp_path / "references.lock.json"
    P.write_reference_lock(p)
    assert P.check_reference_integrity(p)["ok"] is True


def test_source_provenance_builtin_and_optional():
    rows = P.source_provenance(["catalog", "garak", "dataset:advbench"])
    by = {r["source"]: r for r in rows}
    assert by["catalog"]["kind"] == "built-in" and by["catalog"]["available"]
    # garak is an optional extra; available reflects whether it is installed
    assert by["garak"]["package"] == "garak"
    assert by["dataset:advbench"]["package"] == "datasets"


def test_eval_provenance_carries_fingerprints():
    meta = RunMeta(name="r", mode="fixed", corpus_fingerprint="abc123",
                   rubric_fingerprint="def456", config_fingerprint="ghi789")
    prov = P.eval_provenance(meta)
    assert prov["kind"] == "eval"
    assert prov["fingerprints"]["corpus"] == "abc123"
    assert prov["tool"]["tool"] == "promptpolygraph"


def test_redteam_provenance_pins_mapping():
    report = asyncio.run(run_redteam(DemoAdapter(), get_profile("quick"), mock=True))
    prov = P.redteam_provenance(report, sources=["catalog"])
    assert prov["kind"] == "redteam"
    assert prov["reference"]["mapping_hash"] == P.reference_manifest()["mapping_hash"]
    assert prov["sources"][0]["source"] == "catalog"


def test_cli_references_and_manifest(tmp_path):
    from promptpolygraph.cli import main
    assert main(["references", "--check"]) == 0
