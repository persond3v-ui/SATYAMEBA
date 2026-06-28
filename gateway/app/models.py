"""ORM models — users, sessions, nodes, audit log."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# JSONB on PostgreSQL (indexable), portable JSON elsewhere (tests / SQLite).
JSONType = JSON().with_variant(JSONB, "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserStatus(str, enum.Enum):
    pending = "pending"      # registered, awaiting admin approval
    approved = "approved"    # may log in and spawn notebooks
    rejected = "rejected"    # explicitly denied
    suspended = "suspended"  # kicked off by an admin


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"
    owner = "owner"   # the un-removable super-admin (Samaraho Mukherjee)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.pending, nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # TOTP two-factor auth (secret stored Fernet-encrypted at rest)
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Force a password change (e.g. the seeded bootstrap admin)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Admin-ease fields: account expiry (auto-suspend), GPU-hours quota, tags/groups.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gpu_hours_limit: Mapped[float | None] = mapped_column(nullable=True)  # None = unlimited
    tags: Mapped[list] = mapped_column(JSONType, default=list)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """A refresh-token session. Each carries its own HMAC signing key used to
    sign API requests, so a token stolen without the signing key is useless."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    signing_key: Mapped[str] = mapped_column(String(128))  # per-session HMAC key (hex)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")

    user: Mapped["User"] = relationship(back_populates="sessions")


class SsoToken(Base):
    """A single-use, short-lived token that lets the SPA hand a logged-in user
    off to JupyterHub without a second login. Stored in the DB so it works
    across multiple gateway replicas."""

    __tablename__ = "sso_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    profile: Mapped[str] = mapped_column(String(32), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class NodeStatus(str, enum.Enum):
    online = "online"
    draining = "draining"
    offline = "offline"


class Node(Base):
    """A physical machine in the cluster (master or worker)."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(32), default="worker")  # master | worker
    swarm_node_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[NodeStatus] = mapped_column(Enum(NodeStatus), default=NodeStatus.online)
    labels: Mapped[dict] = mapped_column(JSONType, default=dict)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BoostStatus(str, enum.Enum):
    pending = "pending"      # awaiting admin decision
    approved = "approved"    # granted, not yet consumed by a launch
    denied = "denied"        # admin refused
    consumed = "consumed"    # used by one launch (the one-session grant is spent)
    expired = "expired"      # granted but the session ended without use / revoked


class GpuBoostRequest(Base):
    """A user's request to run multi-GPU / cross-node training (Kaggle-style).

    An admin approves it; the grant is good for exactly **one session** (one
    notebook launch), then it flips to ``consumed``. The scheduler spreads the
    boosted job across whatever GPU nodes are free at launch time."""

    __tablename__ = "gpu_boost_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    gpus: Mapped[int] = mapped_column(Integer, default=2)        # GPU nodes requested
    reason: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[BoostStatus] = mapped_column(
        Enum(BoostStatus), default=BoostStatus.pending, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)   # admin id
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotebookRun(Base):
    """Authoritative placement record. The gateway *decides* the node and the
    sharing mode (the Hub/Swarm just honour the constraint we pass), so we know
    exactly how loaded each node is and who is sharing with whom."""

    __tablename__ = "notebook_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    node_hostname: Mapped[str] = mapped_column(String(255), default="", index=True)
    profile: Mapped[str] = mapped_column(String(32), default="medium")
    mode: Mapped[str] = mapped_column(String(16), default="exclusive")  # exclusive|shared|boost
    gpus: Mapped[int] = mapped_column(Integer, default=0)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    boost_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|stopped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)   # ddp_nodes, rdzv, …


class Notification(Base):
    """An in-app message for a user (sharing started, boost approved, queued→free)."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="info")  # info|success|warning|boost
    message: Mapped[str] = mapped_column(String(512), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class InviteCode(Base):
    """A registration code that auto-approves the new account (skips the manual
    approval queue) — for onboarding a class roster in bulk."""

    __tablename__ = "invite_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    """Tiny key/value store for runtime toggles (maintenance mode, banner …)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048), default="")


class AuditLog(Base):
    """Append-only audit trail. Every privileged action lands here, chained with
    a hash of the previous row so tampering is detectable (OWASP A09)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_label: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
