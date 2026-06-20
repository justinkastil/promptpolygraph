"""Append-only, hash-chained audit log.

Every entry stores the hash of the previous entry, so the log forms a chain:
altering or removing any past entry breaks every hash after it, and
`verify_chain` pinpoints where. This gives a tamper-evident record of privileged
actions (run created/deleted, config changed, gate overridden) for a shared
deployment, without a database — a JSONL file is the store.

Pure stdlib. Genesis entry links to a fixed zero hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from .models import now_iso

GENESIS = "0" * 64


def _entry_hash(entry: dict[str, Any]) -> str:
    """SHA-256 over the canonical entry, excluding its own hash field."""
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _last_hash(self) -> tuple[int, str]:
        rows = self.entries()
        if not rows:
            return -1, GENESIS
        last = rows[-1]
        return int(last.get("seq", len(rows) - 1)), last.get("entry_hash", GENESIS)

    def append(self, action: str, *, actor: str | None = None,
               ts: str | None = None, **data: Any) -> dict[str, Any]:
        """Append a record and return it (with its computed hash)."""
        with self._lock:
            seq, prev = self._last_hash()
            entry = {
                "seq": seq + 1,
                "ts": ts or now_iso(),
                "action": action,
                "actor": actor,
                "data": data,
                "prev_hash": prev,
            }
            entry["entry_hash"] = _entry_hash(entry)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    def verify_chain(self) -> dict[str, Any]:
        """Recompute the chain. Returns {ok, reason, length, broken_at}."""
        rows = self.entries()
        prev = GENESIS
        for i, entry in enumerate(rows):
            if entry.get("prev_hash") != prev:
                return {"ok": False, "reason": f"broken link at seq {entry.get('seq', i)} "
                        "(prev_hash does not match the prior entry)",
                        "length": len(rows), "broken_at": i}
            if _entry_hash(entry) != entry.get("entry_hash"):
                return {"ok": False, "reason": f"tampered entry at seq {entry.get('seq', i)} "
                        "(content does not match its hash)",
                        "length": len(rows), "broken_at": i}
            if entry.get("seq") != i:
                return {"ok": False, "reason": f"sequence gap at index {i} (seq={entry.get('seq')})",
                        "length": len(rows), "broken_at": i}
            prev = entry["entry_hash"]
        return {"ok": True, "reason": f"chain intact ({len(rows)} entries)",
                "length": len(rows), "broken_at": None}


def default_log_path(out_dir: str | Path = "polygraph_out") -> Path:
    return Path(os.environ.get("POLYGRAPH_AUDIT_LOG", str(Path(out_dir) / "audit_log.jsonl")))
