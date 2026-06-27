"""Pytest fixtures for the gateway.

Runs the app against a throwaway SQLite database with HS256 tokens so the suite
needs no Postgres or external services. Environment is configured before the app
is imported so ``get_settings()`` picks it up.
"""
import os
import pathlib
import sys
import tempfile

_DB = pathlib.Path(tempfile.gettempdir()) / "satyameba_test.db"
if _DB.exists():
    _DB.unlink()

os.environ.update({
    "SAT_ENVIRONMENT": "development",       # don't trip the production fail-closed check
    "SAT_DATABASE_URL": f"sqlite+pysqlite:///{_DB}",
    "SAT_JWT_ALGORITHM": "HS256",
    "SAT_JWT_SECRET": "x" * 48,
    "SAT_JWT_PRIVATE_KEY_PATH": "",
    "SAT_JWT_PUBLIC_KEY_PATH": "",
    "SAT_BOOTSTRAP_ADMIN_USERNAME": "admin",
    "SAT_BOOTSTRAP_ADMIN_PASSWORD": "AdminP@ss123!",
    "SAT_REQUEST_SIGNING_ENABLED": "true",
    "SAT_REDIS_URL": "",
    # The rate limiter is exercised separately; raise limits so the rapid-fire
    # login calls in this suite (all from one client IP) aren't throttled.
    "SAT_AUTH_RATE_LIMIT_PER_MINUTE": "1000",
    "SAT_RATE_LIMIT_PER_MINUTE": "1000",
})

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # gateway/

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
