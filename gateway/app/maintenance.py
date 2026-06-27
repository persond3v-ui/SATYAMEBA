"""Periodic housekeeping: purge expired one-time tokens and dead sessions.

Without this, ``sso_tokens`` (one row per launch) and expired ``user_sessions``
grow unbounded. ``cleanup_once`` is safe to call repeatedly and is run on a timer
by the app lifespan.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, or_

from .config import get_settings
from .database import SessionLocal
from .models import AuditLog, SsoToken, UserSession
from .timeutil import utcnow

logger = logging.getLogger("satyameba.maintenance")
settings = get_settings()


def cleanup_once() -> dict:
    """Delete used/expired SSO tokens and sessions past their refresh lifetime."""
    db = SessionLocal()
    try:
        now = utcnow()
        sso = db.execute(
            delete(SsoToken).where(or_(SsoToken.used.is_(True), SsoToken.expires_at < now))
        ).rowcount
        # A session is dead once its refresh window has fully elapsed.
        cutoff = now - timedelta(seconds=settings.refresh_token_ttl_seconds)
        sessions = db.execute(
            delete(UserSession).where(UserSession.expires_at < cutoff)
        ).rowcount
        # Optional audit retention (default 0 = keep everything). NOTE: pruning the
        # oldest rows breaks hash-chain verification before the retention window —
        # only enable if you archive first / accept windowed verification.
        audit = 0
        if settings.audit_retention_days > 0:
            audit_cutoff = now - timedelta(days=settings.audit_retention_days)
            audit = db.execute(
                delete(AuditLog).where(AuditLog.timestamp < audit_cutoff)
            ).rowcount
        db.commit()
        if sso or sessions or audit:
            logger.info("maintenance: removed %s sso tokens, %s sessions, %s audit rows",
                        sso, sessions, audit)
        return {"sso_tokens": sso or 0, "sessions": sessions or 0, "audit": audit or 0}
    finally:
        db.close()
