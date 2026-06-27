"""Pydantic request/response schemas. These enforce strict input validation
(OWASP A03/A04) before anything touches the database or the orchestrator."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_RE = r"^[a-z0-9][a-z0-9_-]{2,31}$"


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(pattern=USERNAME_RE)
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        classes = [
            any(c.islower() for c in v),
            any(c.isupper() for c in v),
            any(c.isdigit() for c in v),
            any(not c.isalnum() for c in v),
        ]
        if sum(classes) < 3:
            raise ValueError(
                "Password must mix at least three of: lowercase, uppercase, digit, symbol."
            )
        return v


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    signing_key: str  # per-session HMAC key the SPA uses to sign requests


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    username: str
    full_name: str
    role: str
    status: str
    created_at: datetime
    approved_at: datetime | None = None
    last_login_at: datetime | None = None


class ApproveRequest(BaseModel):
    user_id: str
    role: str = "user"


class RejectRequest(BaseModel):
    user_id: str
    reason: str = Field(default="", max_length=512)


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hostname: str
    ip: str
    role: str
    status: str
    labels: dict
    joined_at: datetime
    last_heartbeat: datetime | None = None


class NodeRegister(BaseModel):
    hostname: str = Field(max_length=255)
    ip: str = Field(default="", max_length=64)
    role: str = "worker"
    swarm_node_id: str = ""
    labels: dict = Field(default_factory=dict)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp: datetime
    actor_label: str
    action: str
    target: str
    ip: str
    detail: dict
