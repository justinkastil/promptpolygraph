"""Validation package — IQ/OQ/PQ evidence bundle."""

from __future__ import annotations

import json

from promptpolygraph import validate as V


def test_iq_all_pass():
    iq = V.run_iq()
    failed = [c for c in iq if not c["ok"]]
    assert not failed, f"IQ failures: {failed}"
    names = {c["name"] for c in iq}
    assert any("reference integrity" in n for n in names)
    assert any("persona library" in n for n in names)


def test_oq_all_pass():
    oq = V.run_oq()
    failed = [c for c in oq if not c["ok"]]
    assert not failed, f"OQ failures: {failed}"
    # the headline components are all exercised
    blob = " ".join(c["name"] for c in oq)
    assert "Wilson" in blob and "red-team" in blob and "calibration" in blob and "report" in blob


def test_pq_reproducible():
    pq = V.run_pq()
    assert pq and pq[0]["ok"], pq


def test_validate_bundle_structure_and_write(tmp_path):
    bundle = V.validate(tmp_path, timestamp="2026-06-19T00:00:00+00:00")
    assert bundle["overall_ok"] is True
    assert bundle["schema_version"] == V.SCHEMA_VERSION
    assert set(bundle["qualifications"]) == {"IQ", "OQ", "PQ"}
    assert bundle["generated_at"] == "2026-06-19T00:00:00+00:00"
    # files written + valid
    doc = json.loads((tmp_path / "evidence.json").read_text())
    assert doc["overall_ok"] is True
    md = (tmp_path / "evidence.md").read_text()
    assert "Installation qualification" in md and "PASS" in md


def test_validate_no_pq():
    bundle = V.validate(include_pq=False)
    assert bundle["qualifications"]["PQ"] == []
    assert bundle["summary"]["PQ"]["total"] == 0


def test_cli_validate_returns_zero(tmp_path):
    from promptpolygraph.cli import main
    assert main(["validate", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "evidence.json").exists()
