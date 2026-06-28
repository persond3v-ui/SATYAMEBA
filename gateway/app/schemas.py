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
    invite_code: str | None = Field(default=None, max_length=32)  # auto-approve if valid

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
    otp: str | None = Field(default=None, max_length=16)  # TOTP code when 2FA on


class TwoFASetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png_data_uri: str


class TwoFACodeRequest(BaseModel):
    code: str = Field(max_length=16)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    signing_key: str  # per-session HMAC key the SPA uses to sign requests


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
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


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    # plain str on output: the value was validated at registration, and EmailStr
    # would reject already-stored addresses on reserved domains (e.g. .local).
    email: str
    username: str
    full_name: str
    role: str
    status: str
    created_at: datetime
    approved_at: datetime | None = None
    last_login_at: datetime | None = None
    totp_enabled: bool = False
    must_change_password: bool = False


class ApproveRequest(BaseModel):
    user_id: str
    role: str = "user"


class RejectRequest(BaseModel):
    user_id: str
    reason: str = Field(default="", max_length=512)


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(user|admin)$")   # owner can never be granted/removed


class CreateUserRequest(BaseModel):
    email: EmailStr
    username: str = Field(pattern=USERNAME_RE)
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(default="user", pattern="^(user|admin)$")


class BulkAction(BaseModel):
    action: str = Field(pattern="^(approve|reject|suspend|reinstate|delete)$")
    user_ids: list[str] = Field(min_length=1, max_length=500)


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


class BoostRequestCreate(BaseModel):
    gpus: int = Field(default=2, ge=1, le=64)
    reason: str = Field(default="", max_length=512)


class BoostDecision(BaseModel):
    gpus: int | None = Field(default=None, ge=1, le=64)   # admin may adjust the grant
    reason: str = Field(default="", max_length=512)


class BoostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    gpus: int
    reason: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    message: str
    read: bool
    created_at: datetime


class InviteCreate(BaseModel):
    role: str = Field(default="user", pattern="^(user|admin)$")
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    role: str
    max_uses: int
    uses: int
    active: bool
    created_at: datetime
    expires_at: datetime | None = None


class ExpiryUpdate(BaseModel):
    days: int | None = Field(default=None, ge=1, le=3650)   # set expiry N days out
    clear: bool = False                                     # or remove the expiry


class QuotaUpdate(BaseModel):
    gpu_hours_limit: float | None = Field(default=None, ge=0)  # None+clear=unlimited
    clear: bool = False


class TagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)


class AnnounceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    kind: str = Field(default="info", pattern="^(info|success|warning|boost)$")


class MaintenanceRequest(BaseModel):
    on: bool
    message: str = Field(default="", max_length=512)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp: datetime
    actor_label: str
    action: str
    target: str
    ip: str
    detail: dict
