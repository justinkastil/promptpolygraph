"""Multi-tenant workspaces + RBAC for the service.

The tenancy layer lives at the request boundary, so the engine and its stores
stay untouched. It owns four tables — ``workspaces``, ``members``, ``api_keys``,
``resource_workspace`` — plus a per-workspace hash-chained audit log
(``audit_log.py``).

Design decisions (matching what institutional security review expects):

- **Workspaces** are the isolation boundary; every run is stamped to one and a
  request can only see its own workspace's runs (cross-workspace reads 404, so
  existence is not leaked).
- **RBAC**: ``admin`` > ``editor`` > ``viewer``. Admin manages members + keys +
  reads the audit log; editor creates/cancels runs; viewer is read-only.
- **API keys are hashed at rest** (SHA-256); the plaintext is shown once at
  creation and never recoverable. A key carries its workspace + role.
- **Backward compatible**: a legacy flat ``POLYGRAPH_API_KEYS`` value maps to an
  admin principal in an auto-provisioned ``default`` workspace, and an
  auth-disabled dev server resolves to that same admin — so existing behavior is
  preserved with zero config.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from ..audit_log import _entry_hash  # reuse the hash-chain primitive
from ..models import new_id, now_iso

from functools import lru_cache

ROLES = ("viewer", "editor", "admin")
_RANK = {r: i for i, r in enumerate(ROLES)}
DEFAULT_WORKSPACE = "default"

_meta = MetaData()

workspaces = Table(
    "workspaces", _meta,
    Column("workspace_id", String(64), primary_key=True),
    Column("name", String(120)),
    Column("created_at", String(40)),
)
members = Table(
    "members", _meta,
    Column("workspace_id", String(64), index=True),
    Column("subject", String(200)),   # a user identifier (email / sub claim)
    Column("role", String(16)),
    Column("created_at", String(40)),
)
api_keys = Table(
    "api_keys", _meta,
    Column("key_hash", String(64), primary_key=True),  # sha256(plaintext)
    Column("workspace_id", String(64), index=True),
    Column("role", String(16)),
    Column("label", String(120)),
    Column("created_at", String(40)),
    Column("last_used_at", String(40)),
    Column("revoked", Integer, default=0),
)
# Maps a run to its owning workspace (the engine's RunMeta stays tenancy-free).
resource_workspace = Table(
    "resource_workspace", _meta,
    Column("run_id", String(64), primary_key=True),
    Column("workspace_id", String(64), index=True),
    Column("created_at", String(40)),
)
# Per-workspace hash-chained audit entries (mirrors audit_log.py on disk-less DB).
audit_entries = Table(
    "audit_entries", _meta,
    Column("workspace_id", String(64), index=True),
    Column("seq", Integer),
    Column("ts", String(40)),
    Column("action", String(80)),
    Column("actor", String(200)),
    Column("data", Text),
    Column("prev_hash", String(64)),
    Column("entry_hash", String(64), primary_key=True),
)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


@dataclass
class Principal:
    """The authenticated caller: which workspace, which role, who."""
    workspace_id: str
    role: str
    subject: str
    via: str  # "api_key" | "legacy" | "dev"

    def can(self, required: str) -> bool:
        return _RANK.get(self.role, -1) >= _RANK.get(required, 99)


class Tenancy:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        _meta.create_all(self.engine)

    # ─── workspaces / members ────────────────────────────────────────────────
    def ensure_workspace(self, workspace_id: str, name: str | None = None) -> None:
        with self.engine.begin() as c:
            exists = c.execute(select(workspaces.c.workspace_id)
                               .where(workspaces.c.workspace_id == workspace_id)).first()
            if not exists:
                c.execute(insert(workspaces), {"workspace_id": workspace_id,
                          "name": name or workspace_id, "created_at": now_iso()})

    def create_workspace(self, name: str) -> dict:
        wid = new_id()[:16]
        self.ensure_workspace(wid, name)
        return {"workspace_id": wid, "name": name}

    def list_workspaces(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(m) for m in c.execute(select(workspaces)).mappings().all()]

    def add_member(self, workspace_id: str, subject: str, role: str) -> dict:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        with self.engine.begin() as c:
            c.execute(delete(members).where(members.c.workspace_id == workspace_id,
                                            members.c.subject == subject))
            c.execute(insert(members), {"workspace_id": workspace_id, "subject": subject,
                      "role": role, "created_at": now_iso()})
        return {"workspace_id": workspace_id, "subject": subject, "role": role}

    def list_members(self, workspace_id: str) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(m) for m in c.execute(
                select(members).where(members.c.workspace_id == workspace_id)).mappings().all()]

    def member_role(self, workspace_id: str, subject: str) -> Optional[str]:
        with self.engine.connect() as c:
            row = c.execute(select(members.c.role).where(
                members.c.workspace_id == workspace_id, members.c.subject == subject)).first()
        return row[0] if row else None

    # ─── api keys ────────────────────────────────────────────────────────────
    def create_api_key(self, workspace_id: str, role: str, label: str = "") -> dict:
        """Mint a key. Returns the plaintext ONCE (only the hash is stored)."""
        if role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        plaintext = f"ppg_{workspace_id[:8]}_{secrets.token_urlsafe(24)}"
        with self.engine.begin() as c:
            c.execute(insert(api_keys), {
                "key_hash": hash_key(plaintext), "workspace_id": workspace_id,
                "role": role, "label": label, "created_at": now_iso(),
                "last_used_at": None, "revoked": 0})
        return {"api_key": plaintext, "workspace_id": workspace_id, "role": role, "label": label}

    def list_api_keys(self, workspace_id: str) -> list[dict]:
        """Metadata only — never the plaintext or full hash."""
        with self.engine.connect() as c:
            rows = c.execute(select(api_keys).where(
                api_keys.c.workspace_id == workspace_id)).mappings().all()
        return [{"label": r["label"], "role": r["role"], "created_at": r["created_at"],
                 "last_used_at": r["last_used_at"], "revoked": bool(r["revoked"]),
                 "key_prefix": r["key_hash"][:8]} for r in rows]

    def revoke_api_key(self, workspace_id: str, key_prefix: str) -> bool:
        with self.engine.begin() as c:
            rows = c.execute(select(api_keys.c.key_hash).where(
                api_keys.c.workspace_id == workspace_id)).all()
            target = next((h[0] for h in rows if h[0].startswith(key_prefix)), None)
            if not target:
                return False
            c.execute(update(api_keys).where(api_keys.c.key_hash == target).values(revoked=1))
        return True

    def resolve_api_key(self, plaintext: str) -> Optional[Principal]:
        kh = hash_key(plaintext)
        with self.engine.begin() as c:
            row = c.execute(select(api_keys).where(api_keys.c.key_hash == kh)).mappings().first()
            if not row or row["revoked"]:
                return None
            c.execute(update(api_keys).where(api_keys.c.key_hash == kh)
                      .values(last_used_at=now_iso()))
        return Principal(workspace_id=row["workspace_id"], role=row["role"],
                         subject=f"key:{kh[:8]}", via="api_key")

    # ─── resource ownership ──────────────────────────────────────────────────
    def claim_run(self, run_id: str, workspace_id: str) -> None:
        with self.engine.begin() as c:
            exists = c.execute(select(resource_workspace.c.run_id)
                               .where(resource_workspace.c.run_id == run_id)).first()
            if not exists:
                c.execute(insert(resource_workspace), {"run_id": run_id,
                          "workspace_id": workspace_id, "created_at": now_iso()})

    def run_workspace(self, run_id: str) -> Optional[str]:
        with self.engine.connect() as c:
            row = c.execute(select(resource_workspace.c.workspace_id)
                            .where(resource_workspace.c.run_id == run_id)).first()
        return row[0] if row else None

    def owns_run(self, run_id: str, workspace_id: str) -> bool:
        """True if the run belongs to the workspace OR is unclaimed (legacy runs
        created before tenancy existed are visible to keep upgrades non-breaking)."""
        wid = self.run_workspace(run_id)
        return wid is None or wid == workspace_id

    def workspace_run_ids(self, workspace_id: str) -> set[str]:
        with self.engine.connect() as c:
            rows = c.execute(select(resource_workspace.c.run_id)
                             .where(resource_workspace.c.workspace_id == workspace_id)).all()
        return {r[0] for r in rows}

    def has_any_claims(self) -> bool:
        with self.engine.connect() as c:
            return c.execute(select(resource_workspace.c.run_id).limit(1)).first() is not None

    # ─── audit log (hash-chained, per workspace) ─────────────────────────────
    def audit(self, workspace_id: str, action: str, *, actor: str | None = None, **data) -> dict:
        with self.engine.begin() as c:
            rows = c.execute(select(audit_entries).where(
                audit_entries.c.workspace_id == workspace_id)
                .order_by(audit_entries.c.seq)).mappings().all()
            seq = len(rows)
            prev = rows[-1]["entry_hash"] if rows else "0" * 64
            entry = {"seq": seq, "ts": now_iso(), "action": action, "actor": actor,
                     "data": data, "prev_hash": prev}
            entry["entry_hash"] = _entry_hash(entry)
            c.execute(insert(audit_entries), {
                "workspace_id": workspace_id, "seq": seq, "ts": entry["ts"],
                "action": action, "actor": actor,
                "data": json.dumps(data, default=str),
                "prev_hash": prev, "entry_hash": entry["entry_hash"]})
        return entry

    def list_audit(self, workspace_id: str, limit: int = 200) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(audit_entries).where(
                audit_entries.c.workspace_id == workspace_id)
                .order_by(audit_entries.c.seq.desc()).limit(limit)).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d.get("data") or "{}")
            out.append(d)
        return out

    def verify_audit_chain(self, workspace_id: str) -> dict:
        with self.engine.connect() as c:
            rows = c.execute(select(audit_entries).where(
                audit_entries.c.workspace_id == workspace_id)
                .order_by(audit_entries.c.seq)).mappings().all()
        prev = "0" * 64
        for i, r in enumerate(rows):
            entry = {"seq": r["seq"], "ts": r["ts"], "action": r["action"], "actor": r["actor"],
                     "data": json.loads(r["data"] or "{}"), "prev_hash": r["prev_hash"]}
            if r["prev_hash"] != prev or _entry_hash(entry) != r["entry_hash"] or r["seq"] != i:
                return {"ok": False, "reason": f"broken at seq {r['seq']}", "length": len(rows)}
            prev = r["entry_hash"]
        return {"ok": True, "reason": f"chain intact ({len(rows)} entries)", "length": len(rows)}


@lru_cache
def get_tenancy() -> Tenancy:
    """Process-wide tenancy bound to the same database as the store."""
    from .settings import get_settings

    t = Tenancy(get_settings().database_url)
    t.ensure_workspace(DEFAULT_WORKSPACE, "Default")
    return t
