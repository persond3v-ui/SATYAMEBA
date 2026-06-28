"""Database migrations (Alembic) — applied automatically at startup.

Plug-and-play rules so an operator never has to think about it:

* **Fresh database** → ``alembic upgrade head`` builds the whole schema.
* **Existing pre-Alembic database** (it was built by the old ``create_all`` path)
  → create any genuinely-missing tables, then *stamp* it at head so Alembic
  takes ownership going forward without trying to recreate what's there.
* **Already-migrated database** → ``upgrade head`` applies only what's pending.

Multi-replica safe: on PostgreSQL we take a session-level advisory lock so only
one gateway replica migrates at a time; the others wait, then see "head" and
no-op. On SQLite (tests / single host) no lock is needed.

The legacy Postgres ``role`` enum (which may predate the ``owner`` value and
which ``create_all``/``stamp`` cannot alter) is reconciled idempotently here.
"""
from __future__ import annotations

import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from .database import Base, engine

logger = logging.getLogger("satyameba")

_GATEWAY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # gateway/
_INI = os.path.join(_GATEWAY_DIR, "alembic.ini")
_MIGRATIONS = os.path.join(_GATEWAY_DIR, "migrations")
_ADVISORY_LOCK_KEY = 7270727  # arbitrary, stable across replicas


def _config() -> Config:
    cfg = Config(_INI if os.path.exists(_INI) else None)
    cfg.set_main_option("script_location", _MIGRATIONS)
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    return cfg


def _ensure_role_enum() -> None:
    """Idempotent: make sure the Postgres ``role`` enum has every current value.
    Neither ``create_all`` nor an Alembic *stamp* can add an enum value to an
    already-existing type, so a DB created before ``owner`` existed needs this.
    No-op on SQLite / fresh deploys."""
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


def _apply(cfg: Config) -> None:
    insp = inspect(engine)
    has_version = insp.has_table("alembic_version")
    has_users = insp.has_table("users")
    if not has_version and has_users:
        # Pre-Alembic DB: backfill any missing tables, then declare it current.
        Base.metadata.create_all(bind=engine)
        command.stamp(cfg, "head")
        logger.info("migrations: adopted existing database (stamped at head)")
    else:
        command.upgrade(cfg, "head")
        logger.info("migrations: database at head")


def run_migrations() -> None:
    cfg = _config()
    if engine.dialect.name == "postgresql":
        # Serialize migrations across gateway replicas.
        with engine.connect() as lock_conn:
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})
            try:
                _apply(cfg)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK_KEY})
    else:
        _apply(cfg)
    _ensure_role_enum()
