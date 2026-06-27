"""Tamper-evident audit logging.

Each entry stores ``entry_hash = sha256(prev_hash + canonical(entry))``. Because
every row commits the hash of the one before it, an attacker who edits or
deletes a historical row breaks the chain for every subsequent row, which a
verifier (``verify_chain``) detects. This gives us OWASP A09 (security logging
& monitoring) coverage that survives a compromised DB account.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog
from .timeutil import aware


def _canonical(entry: AuditLog) -> str:
    ts = aware(entry.timestamp)
    return json.dumps(
        {
            "ts": ts.isoformat() if ts else "",
            "actor": entry.actor_id,
            "action": entry.action,
            "target": entry.target,
            "ip": entry.ip,
            "detail": entry.detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def record(
    db: Session,
    *,
    action: str,
    actor_id: str | None = None,
    actor_label: str = "",
    target: str = "",
    ip: str = "",
    user_agent: str = "",
    detail: dict | None = None,
) -> AuditLog:
    prev = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = prev.entry_hash if prev else ""
    entry = AuditLog(
        actor_id=actor_id,
        actor_label=actor_label,
        action=action,
        target=target,
        ip=ip,
        user_agent=user_agent[:512],
        detail=detail or {},
        prev_hash=prev_hash,
    )
    db.add(entry)
    db.flush()  # populate timestamp default
    entry.entry_hash = hashlib.sha256((prev_hash + _canonical(entry)).encode()).hexdigest()
    db.commit()
    return entry


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Return (ok, first_bad_id). ok=True means the chain is intact."""
    prev_hash = ""
    for entry in db.execute(select(AuditLog).order_by(AuditLog.id.asc())).scalars():
        expected = hashlib.sha256((prev_hash + _canonical(entry)).encode()).hexdigest()
        if expected != entry.entry_hash:
            return False, entry.id
        prev_hash = entry.entry_hash
    return True, None
