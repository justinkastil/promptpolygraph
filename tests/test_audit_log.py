"""Append-only hash-chained audit log."""

from __future__ import annotations

from promptpolygraph.audit_log import AuditLog, GENESIS


def test_append_and_chain(tmp_path):
    log = AuditLog(tmp_path / "al.jsonl")
    e0 = log.append("run_created", actor="ci", run="r1", ts="2026-01-01T00:00:00Z")
    e1 = log.append("gate_override", actor="justin", ts="2026-01-01T00:01:00Z")
    assert e0["seq"] == 0 and e0["prev_hash"] == GENESIS
    assert e1["seq"] == 1 and e1["prev_hash"] == e0["entry_hash"]
    res = log.verify_chain()
    assert res["ok"] and res["length"] == 2 and res["broken_at"] is None


def test_empty_log_verifies(tmp_path):
    assert AuditLog(tmp_path / "none.jsonl").verify_chain()["ok"]


def test_detects_content_tamper(tmp_path):
    p = tmp_path / "al.jsonl"
    log = AuditLog(p)
    log.append("a", ts="t1")
    log.append("b", ts="t2")
    lines = p.read_text().splitlines()
    lines[0] = lines[0].replace('"action": "a"', '"action": "HACKED"')
    p.write_text("\n".join(lines) + "\n")
    res = log.verify_chain()
    assert not res["ok"] and res["broken_at"] == 0
    assert "tamper" in res["reason"].lower()


def test_detects_deleted_entry(tmp_path):
    p = tmp_path / "al.jsonl"
    log = AuditLog(p)
    log.append("a", ts="t1")
    log.append("b", ts="t2")
    log.append("c", ts="t3")
    lines = p.read_text().splitlines()
    # drop the middle entry -> breaks the chain link + sequence
    p.write_text(lines[0] + "\n" + lines[2] + "\n")
    res = log.verify_chain()
    assert not res["ok"]


def test_deterministic_hash_for_same_content(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    b = AuditLog(tmp_path / "b.jsonl")
    ea = a.append("x", actor="me", ts="t", k=1)
    eb = b.append("x", actor="me", ts="t", k=1)
    assert ea["entry_hash"] == eb["entry_hash"]  # same content+genesis -> same hash


def test_cli_audit_log_verify(tmp_path):
    from promptpolygraph.cli import main
    p = tmp_path / "al.jsonl"
    log = AuditLog(p)
    log.append("run_created", ts="t1")
    assert main(["audit-log", "verify", str(p)]) == 0
    # tamper -> non-zero
    p.write_text(p.read_text().replace("run_created", "x"))
    assert main(["audit-log", "verify", str(p)]) == 1
