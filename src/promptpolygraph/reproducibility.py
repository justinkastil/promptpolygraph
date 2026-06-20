"""Sealed run bundles with tamper-evident verification.

A run's artifacts (cases, responses, scores, summary, reports, provenance) are
packed into a single ``.tar.gz`` alongside a ``MANIFEST.json`` that records a
SHA-256 of every file plus the tool/dependency provenance. ``verify`` re-hashes
the contents and **refuses** (non-zero) on any mismatch — so an archive handed to
an auditor is self-checking. An optional HMAC signature (keyed by
``POLYGRAPH_SIGNING_KEY``) adds origin authentication on top of the integrity
hashes; both use only the standard library, no crypto dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any

from .models import now_iso

_MANIFEST = "MANIFEST.json"
_SIG = "MANIFEST.sig"
_ENV_KEY = "POLYGRAPH_SIGNING_KEY"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sign(manifest_bytes: bytes, key: str | None) -> str | None:
    if not key:
        return None
    return hmac.new(key.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()


def build_manifest(src_dir: str | Path, *, timestamp: str | None = None) -> dict[str, Any]:
    """A manifest of every file under `src_dir` (relative path -> sha256) plus
    tool provenance. Files are sorted for a stable manifest."""
    from .provenance import tool_provenance

    src = Path(src_dir)
    files: dict[str, str] = {}
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.name not in (_MANIFEST, _SIG):
            files[str(p.relative_to(src))] = _sha256_bytes(p.read_bytes())
    return {
        "schema_version": 1,
        "created_at": timestamp or now_iso(),
        "tool": tool_provenance(),
        "file_count": len(files),
        "files": files,
    }


def bundle_dir(src_dir: str | Path, out_path: str | Path | None = None, *,
               key: str | None = None, timestamp: str | None = None) -> str:
    """Pack `src_dir` into a sealed .tar.gz with a checksum manifest (+ optional
    HMAC signature). Returns the archive path."""
    src = Path(src_dir)
    if not src.is_dir():
        raise NotADirectoryError(f"not a directory: {src}")
    out = Path(out_path) if out_path else src.with_suffix(".polygraph.tar.gz")
    manifest = build_manifest(src, timestamp=timestamp)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sig = _sign(manifest_bytes, key if key is not None else os.environ.get(_ENV_KEY))

    def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = 0  # reproducible
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(out, "w:gz") as tar:
        for rel in sorted(manifest["files"]):
            tar.add(src / rel, arcname=rel)
        _add_bytes(tar, _MANIFEST, manifest_bytes)
        if sig:
            _add_bytes(tar, _SIG, (sig + "\n").encode("utf-8"))
    return str(out)


def verify_bundle(path: str | Path, *, key: str | None = None) -> dict[str, Any]:
    """Re-hash a bundle's contents against its manifest. Returns
    {ok, reason, files_checked, mismatches, signed, signature_ok}. `ok` is False
    on any missing/extra/mismatched file or a bad signature."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "reason": f"no such bundle: {p}", "files_checked": 0,
                "mismatches": [], "signed": False, "signature_ok": None}
    try:
        with tarfile.open(p, "r:gz") as tar:
            members = {m.name: m for m in tar.getmembers() if m.isfile()}
            if _MANIFEST not in members:
                return {"ok": False, "reason": "manifest missing", "files_checked": 0,
                        "mismatches": [], "signed": False, "signature_ok": None}
            manifest_bytes = tar.extractfile(_MANIFEST).read()
            manifest = json.loads(manifest_bytes)
            expected = manifest.get("files", {})
            mismatches: list[str] = []
            for rel, want in expected.items():
                m = members.get(rel)
                if m is None:
                    mismatches.append(f"missing: {rel}")
                    continue
                got = _sha256_bytes(tar.extractfile(m).read())
                if got != want:
                    mismatches.append(f"checksum mismatch: {rel}")
            # extra payload files not in the manifest are tampering too
            payload = {n for n in members if n not in (_MANIFEST, _SIG)}
            for extra in sorted(payload - set(expected)):
                mismatches.append(f"unexpected file: {extra}")

            signed = _SIG in members
            signature_ok: bool | None = None
            eff_key = key if key is not None else os.environ.get(_ENV_KEY)
            if signed:
                stored = tar.extractfile(_SIG).read().decode("utf-8").strip()
                if eff_key:
                    signature_ok = hmac.compare_digest(stored, _sign(manifest_bytes, eff_key) or "")
                else:
                    signature_ok = None  # present but no key to check it
    except (tarfile.TarError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "reason": f"unreadable bundle: {e}", "files_checked": 0,
                "mismatches": [], "signed": False, "signature_ok": None}

    ok = not mismatches and (signature_ok is not False)
    if mismatches:
        reason = f"{len(mismatches)} integrity failure(s)"
    elif signature_ok is False:
        reason = "signature mismatch"
    else:
        reason = "all files match the manifest" + (
            " (signature verified)" if signature_ok else
            (" (signed; no key to verify)" if signed else ""))
    return {"ok": ok, "reason": reason, "files_checked": len(expected),
            "mismatches": mismatches, "signed": signed, "signature_ok": signature_ok}


def unbundle(path: str | Path, dest: str | Path) -> str:
    """Extract a bundle to `dest` for offline replay (after verifying)."""
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(Path(path), "r:gz") as tar:
        try:
            tar.extractall(out, filter="data")  # 3.12+: reject path-escaping members
        except TypeError:
            tar.extractall(out)  # 3.10/3.11 without the filter arg
    return str(out)
