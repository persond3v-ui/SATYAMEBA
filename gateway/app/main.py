"""SATYAMEBA gateway entrypoint.

Owner: Samaraho Mukherjee.

Middleware order (outermost first):
    SecurityHeaders -> CORS -> RateLimit -> BotFilter -> RequestSigning -> app
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from starlette.responses import PlainTextResponse

from . import audit
from .config import get_settings
from .database import Base, SessionLocal, engine
from .maintenance import cleanup_once
from .middleware.bot_filter import BotFilterMiddleware
from .middleware.metrics import MetricsMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_signing import RequestSigningMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .models import User, UserRole, UserStatus
from .routers import admin, auth, internal, nodes, notebooks
from .security import hash_password

logger = logging.getLogger("satyameba")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()

MAINTENANCE_INTERVAL = 900  # 15 min


def _assert_production_secrets(s=None) -> None:
    """Fail closed: refuse to start a production deployment with forgeable tokens."""
    s = s or settings
    if not s.is_production:
        return
    weak = []
    rs256_ok = s.jwt_algorithm == "RS256" and s.jwt_private_key and s.jwt_public_key
    if s.jwt_algorithm == "RS256" and not rs256_ok:
        weak.append("RS256 selected but JWT keypair is missing (would fall back to HS256)")
    elif not rs256_ok and "CHANGE_ME" in s.jwt_secret:
        # Only relevant when HS256 is actually in effect.
        weak.append("default JWT HS256 secret still in use")
    if "CHANGE_ME" in s.internal_shared_secret:
        weak.append("default internal shared secret still in use")
    if weak:
        raise RuntimeError(
            "SATYAMEBA refuses to start in production with insecure secrets:\n  - "
            + "\n  - ".join(weak)
            + "\nRun scripts/gen_secrets.sh (or the setup wizard) to provision them."
        )


def _ensure_role_enum() -> None:
    """Idempotent micro-migration: make sure the Postgres 'role' enum has all
    current values. ``create_all`` never alters an existing enum type, so on an
    upgraded database the new 'owner' value would otherwise be missing and the
    owner account could not be created. (No-op on SQLite / fresh deploys.)"""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect() as c:
            c = c.execution_options(isolation_level="AUTOCOMMIT")
            row = c.execute(text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='role'"
            )).fetchone()
            if row and row[0]:
                for val in ("user", "admin", "owner"):
                    c.execute(text(f'ALTER TYPE "{row[0]}" ADD VALUE IF NOT EXISTS \'{val}\''))
    except Exception:
        logger.exception("role-enum ensure failed (non-fatal)")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_production_secrets()
    Base.metadata.create_all(bind=engine)
    _ensure_role_enum()
    _ensure_bootstrap_admin()

    async def _maintenance_loop():
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                await asyncio.to_thread(cleanup_once)
            except Exception:
                logger.exception("maintenance sweep failed")

    task = asyncio.create_task(_maintenance_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="SATYAMEBA Gateway",
    version="0.1.0",
    description="Auth & orchestration control plane for the SATYAMEBA notebook cluster.",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",  # no route enum in prod
    lifespan=lifespan,
)

# Middleware. add_middleware adds the *outermost* layer last, so the calls
# below are written innermost-first.
app.add_middleware(RequestSigningMiddleware)      # innermost: reads/replays body
app.add_middleware(BotFilterMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware)             # outermost: count every response

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(nodes.router)
app.include_router(notebooks.router)
app.include_router(internal.router)


def _ensure_bootstrap_admin() -> None:
    db = SessionLocal()
    try:
        has_admin = db.execute(
            select(func.count()).select_from(User).where(
                User.role.in_([UserRole.admin, UserRole.owner])
            )
        ).scalar_one()
        if has_admin:
            return
        password = settings.bootstrap_admin_password or secrets.token_urlsafe(16)
        admin_user = User(
            email=settings.bootstrap_admin_email,
            username=settings.bootstrap_admin_username,
            full_name="SATYAMEBA Owner — Samaraho Mukherjee",
            password_hash=hash_password(password),
            role=UserRole.owner,            # the un-removable owner account
            status=UserStatus.approved,
            must_change_password=True,      # force rotation of the seeded password
        )
        db.add(admin_user)
        try:
            db.commit()
        except IntegrityError:
            # Another gateway replica created the admin first — that's fine.
            db.rollback()
            return
        audit.record(db, action="system.bootstrap_admin", actor_label="system",
                     target=admin_user.username)
        if not settings.bootstrap_admin_password:
            logger.warning(
                "=== BOOTSTRAP ADMIN CREATED ===\n  username: %s\n  password: %s\n"
                "  CHANGE THIS PASSWORD IMMEDIATELY ===",
                admin_user.username, password,
            )
    finally:
        db.close()


@app.get("/healthz")
def healthz():
    # Minimal, unauthenticated — no project/owner disclosure.
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
