"""Test configuration.

API tests run against the database in CLPI_TEST_DATABASE_URL (PostgreSQL recommended,
schema created by the real Alembic migrations). Without it they fall back to a
temporary SQLite file so the suite can still run anywhere.
"""
import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="clpi-test-"))
DB_URL = os.environ.get("CLPI_TEST_DATABASE_URL") or f"sqlite:///{_tmp / 'test.db'}"
if os.environ.get("CLPI_TEST_DATABASE_URL"):
    from sqlalchemy.engine import make_url
    _test_url = make_url(DB_URL)
    if _test_url.drivername.startswith("postgresql") and not (_test_url.database or "").endswith("_test"):
        raise RuntimeError("CLPI_TEST_DATABASE_URL must name a disposable database ending in _test; tests recreate its public schema")
os.environ["CLPI_DATABASE_URL"] = DB_URL
os.environ["CLPI_UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["CLPI_SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["CLPI_BOOTSTRAP_ADMIN_EMAIL"] = "admin@test.local"
os.environ["CLPI_BOOTSTRAP_ADMIN_PASSWORD"] = "admin-password-123"
os.environ.pop("CLPI_ANTHROPIC_API_KEY", None)
os.environ["CLPI_RESEARCH_WORKER"] = "off"  # tests drive research jobs synchronously
for _k in ("CLPI_BRAVE_API_KEY", "CLPI_TAVILY_API_KEY", "CLPI_RESEARCH_PROVIDER"):
    os.environ.pop(_k, None)

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, get_engine, reset_engine  # noqa: E402

get_settings.cache_clear()
reset_engine()


def _create_schema():
    engine = get_engine()
    if DB_URL.startswith("postgresql"):
        from alembic import command
        from alembic.config import Config
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        command.upgrade(cfg, "head")
    else:
        import app.models as _models  # noqa: F401  (registers tables)
        assert _models
        Base.metadata.create_all(engine)


_create_schema()


def _truncate():
    engine = get_engine()
    tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    with engine.begin() as c:
        if DB_URL.startswith("postgresql"):
            c.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
        else:
            for t in tables:
                c.execute(text(f"DELETE FROM {t}"))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app
    _truncate()
    with TestClient(create_app()) as c:
        yield c


def login(client, email="admin@test.local", password="admin-password-123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client)


def make_user(client, admin_headers, role):
    email = f"{role}@test.local"
    r = client.post("/api/users", headers=admin_headers,
                    json={"email": email, "name": role.title(), "role": role, "password": "password-1234"})
    assert r.status_code == 200, r.text
    return login(client, email, "password-1234")
