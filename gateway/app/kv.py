"""Tiny key/value settings store for runtime toggles (maintenance mode, etc.)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Setting

MAINTENANCE = "maintenance_mode"
MAINTENANCE_MSG = "maintenance_message"


def get_setting(db: Session, key: str, default: str = "") -> str:
    s = db.get(Setting, key)
    return s.value if s is not None else default


def set_setting(db: Session, key: str, value: str) -> None:
    s = db.get(Setting, key)
    if s is not None:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))


def is_maintenance(db: Session) -> bool:
    return get_setting(db, MAINTENANCE, "0") == "1"
