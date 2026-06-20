"""Sealed run bundles + tamper-evident verification."""

from __future__ import annotations

import io
import tarfile

from promptpolygraph import reproducibility as R


def _make_run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "summary.json").write_text('{"overall_pass": true}')
    (d / "report.md").write_text("# report\nbody\n")
    sub = d / "redteam"
    sub.mkdir()
    (sub / "redteam.json").write_text('{"asr": 0.1}')
    return d


def _retar_modified(path, target_suffix, mutate):
    """Rewrite an archive, applying `mutate(bytes)->bytes` to the file whose name
    ends with target_suffix (simulating tampering inside the sealed bundle)."""
    tmp = str(path) + ".t"
    with tarfile.open(path, "r:gz") as tin, tarfile.open(tmp, "w:gz") as tout:
        for m in tin.getmembers():
            data = tin.extractfile(m).read() if m.isfile() else b""
            if m.name.endswith(target_suffix):
                data = mutate(data)
            ti = tarfile.TarInfo(m.name)
            ti.size = len(data)
            tout.addfile(ti, io.BytesIO(data))
    import os
    os.replace(tmp, path)


def test_bundle_and_verify_intact(tmp_path):
    d = _make_run(tmp_path)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz")
    res = R.verify_bundle(arc)
    assert res["ok"] is True
    assert res["files_checked"] == 3
    assert res["mismatches"] == []
    assert res["signed"] is False


def test_verify_detects_tampered_file(tmp_path):
    d = _make_run(tmp_path)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz")
    _retar_modified(arc, "report.md", lambda b: b + b"TAMPERED")
    res = R.verify_bundle(arc)
    assert res["ok"] is False
    assert any("report.md" in m for m in res["mismatches"])


def test_verify_detects_extra_file(tmp_path):
    d = _make_run(tmp_path)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz")
    # inject a file not present in the manifest
    with tarfile.open(arc, "a:") if False else tarfile.open(arc, "r:gz") as _:
        pass
    # rebuild adding an extra payload file
    tmp = str(arc) + ".t"
    with tarfile.open(arc, "r:gz") as tin, tarfile.open(tmp, "w:gz") as tout:
        for m in tin.getmembers():
            if m.isfile():
                tout.addfile(m, io.BytesIO(tin.extractfile(m).read()))
        extra = tarfile.TarInfo("sneaked.txt")
        data = b"surprise"
        extra.size = len(data)
        tout.addfile(extra, io.BytesIO(data))
    import os
    os.replace(tmp, arc)
    res = R.verify_bundle(arc)
    assert res["ok"] is False
    assert any("sneaked.txt" in m for m in res["mismatches"])


def test_signing_roundtrip_and_wrong_key(tmp_path):
    d = _make_run(tmp_path)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz", key="s3cret")
    # right key -> signature verified
    ok = R.verify_bundle(arc, key="s3cret")
    assert ok["ok"] is True and ok["signed"] is True and ok["signature_ok"] is True
    # wrong key -> signature mismatch fails verification
    bad = R.verify_bundle(arc, key="nope")
    assert bad["ok"] is False and bad["signature_ok"] is False
    # no key -> integrity still holds; signature present but unverified
    nokey = R.verify_bundle(arc)
    assert nokey["ok"] is True and nokey["signed"] is True and nokey["signature_ok"] is None


def test_unbundle_roundtrip(tmp_path):
    d = _make_run(tmp_path)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz")
    out = R.unbundle(arc, tmp_path / "extracted")
    from pathlib import Path
    assert (Path(out) / "report.md").read_text() == "# report\nbody\n"
    assert (Path(out) / "MANIFEST.json").exists()


def test_verify_missing_bundle(tmp_path):
    res = R.verify_bundle(tmp_path / "nope.tar.gz")
    assert res["ok"] is False and "no such bundle" in res["reason"]


def test_cli_bundle_verify(tmp_path):
    from promptpolygraph.cli import main
    d = tmp_path / "polygraph_out" / "abc123"
    d.mkdir(parents=True)
    (d / "summary.json").write_text("{}")
    arc = tmp_path / "b.tar.gz"
    assert main(["bundle", "--out-dir", str(tmp_path / "polygraph_out"),
                 "--run", "abc123", "--out", str(arc)]) == 0
    assert main(["verify", str(arc)]) == 0


def test_ed25519_signed_bundle(tmp_path):
    import pytest
    from promptpolygraph import signing
    if not signing.ed25519_available():
        pytest.skip("cryptography not installed")
    d = _make_run(tmp_path)
    priv, pub = signing.generate_keypair()
    (tmp_path / "k.key").write_text(priv)
    arc = R.bundle_dir(d, tmp_path / "run.tar.gz", sign_key=str(tmp_path / "k.key"))
    ok = R.verify_bundle(arc, pub_key=pub)
    assert ok["ok"] is True and ok["signed"] is True and ok["signature_ok"] is True
    # a different public key fails
    _, other = signing.generate_keypair()
    bad = R.verify_bundle(arc, pub_key=other)
    assert bad["ok"] is False and bad["signature_ok"] is False
    # no key -> integrity holds, signature unverified
    nokey = R.verify_bundle(arc)
    assert nokey["ok"] is True and nokey["signature_ok"] is None
