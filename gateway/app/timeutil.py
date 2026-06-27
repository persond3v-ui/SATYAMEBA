"""Datetime helpers.

We always work in UTC. Some database drivers (and SQLite) return naive
datetimes even when the column is declared timezone-aware; comparing a naive
value against an aware ``datetime.now(timezone.utc)`` raises TypeError. ``aware``
normalizes any value to a timezone-aware UTC datetime so comparisons are safe.
"""
from __future__ import annotations

from datetime import datetime, timezone


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
