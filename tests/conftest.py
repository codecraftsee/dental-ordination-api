"""Shared test fixtures.

The suite runs against a real PostgreSQL instance, the same engine production
uses. Start one with:

    docker compose -f docker-compose.test.yml up -d

Two things drive the slightly unusual shape of this file:

1. ``app/database.py`` builds its engine at import time from ``get_settings()``,
   which is ``lru_cache``d. So the environment has to be pointed at the test
   database *before* anything under ``app.`` is imported — hence the env
   assignments above the imports.
2. ``app/routers/import_xlsx.py`` uses ``SessionLocal`` directly rather than the
   ``get_db`` dependency. Overriding a FastAPI dependency would therefore miss
   it. Redirecting the whole process at the test database covers every code
   path uniformly and is closer to how the app really runs.
"""

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://dental:dental@localhost:55432/dental_test",
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-only-secret-key"
# Keep the suite offline: an empty key makes the Resend client fail fast rather
# than reach the network, and the routers already swallow invite-email errors.
os.environ["RESEND_API_KEY"] = ""

from urllib.parse import urlparse  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import bindparam, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

ADMIN_EMAIL = "admin@dentalclinic.com"
ADMIN_PASSWORD = "Test123#"

# This file drops and recreates the public schema. That is safe only against a
# throwaway database, so make it structurally impossible to aim it elsewhere.
_DB_NAME = (urlparse(TEST_DATABASE_URL).path or "").lstrip("/")
if "test" not in _DB_NAME.lower():
    raise RuntimeError(
        f"Refusing to run: test database name {_DB_NAME!r} does not contain 'test'. "
        "conftest.py drops the public schema, so it must never point at a real database."
    )


def auth(token: str) -> dict:
    """Authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def engine():
    from app.database import engine as app_engine

    try:
        with app_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.exit(
            f"Cannot reach the test database at {TEST_DATABASE_URL}\n"
            "Start it with:  docker compose -f docker-compose.test.yml up -d",
            returncode=1,
        )

    # Start from an empty schema so create_all() and the startup migrations in
    # app/main.py run from scratch every session — the same path a fresh deploy
    # takes.
    with app_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    return app_engine


@pytest.fixture(scope="session")
def client(engine):
    """TestClient with the app's startup event executed (DDL + seed data)."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


SEEDED_TABLES = ("users", "diagnoses", "treatments")


@pytest.fixture(scope="session")
def seeded_rows(client, engine):
    """Full snapshot of every row the startup seed created."""
    with engine.connect() as conn:
        return {
            table: [dict(row) for row in conn.execute(text(f"SELECT * FROM {table}")).mappings()]
            for table in SEEDED_TABLES
        }


@pytest.fixture(autouse=True)
def reset_db(client, engine, seeded_rows):
    """Return the database to its exact just-seeded state after every test.

    Deleting only the *extra* rows is not enough: a test that changes a seeded
    row (demoting the seeded admin, say) would leak that change into every test
    that ran afterwards. So the seeded tables are emptied and rewritten from the
    snapshot.
    """
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE patient_documents, visits, patients CASCADE"))
        for table in SEEDED_TABLES:
            conn.execute(text(f"DELETE FROM {table}"))
            for row in seeded_rows[table]:
                columns = ", ".join(row)
                placeholders = ", ".join(f":{name}" for name in row)
                conn.execute(
                    text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"),
                    row,
                )


@pytest.fixture
def make_user(client):
    """Create a login-ready user directly in the database.

    The POST /api/users endpoint deliberately creates users with no password
    (they set one via an emailed invite), so it cannot produce a user that can
    log in. Tests that need a usable account go around it.
    """
    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    counter = {"n": 0}

    def _make(role: "UserRole" = None, password: str = "Test123#", **kwargs):
        from app.models.user import UserRole as Role

        role = role or Role.NURSE
        counter["n"] += 1
        with SessionLocal() as db:
            user = User(
                # Not a .local/.test/.example domain: EmailStr rejects reserved
                # TLDs, so POST /api/users would 422 before its own validation.
                email=kwargs.pop("email", f"{role.value.lower()}{counter['n']}@dental-test.com"),
                # password=None models an invited user who has not set one yet
                password_hash=get_password_hash(password) if password else None,
                role=role,
                must_set_password=kwargs.pop("must_set_password", False),
                first_name=kwargs.pop("first_name", role.value.title()),
                last_name=kwargs.pop("last_name", "Tester"),
                **kwargs,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
        return user

    return _make


@pytest.fixture
def admin_token(client):
    return login(client, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def nurse(make_user):
    from app.models.user import UserRole

    return make_user(role=UserRole.NURSE)


@pytest.fixture
def doctor(make_user):
    from app.models.user import UserRole

    return make_user(role=UserRole.DOCTOR, first_name="Milan")


@pytest.fixture
def nurse_token(client, nurse):
    return login(client, nurse.email, "Test123#")


@pytest.fixture
def doctor_token(client, doctor):
    return login(client, doctor.email, "Test123#")


@pytest.fixture
def patient(client, admin_token):
    """A persisted patient, created through the API."""
    resp = client.post(
        "/api/patients",
        json={
            "first_name": "Ana",
            "last_name": "Nikolic",
            "gender": "female",
            "date_of_birth": "1990-02-01",
            "city": "Novi Sad",
            "phone": "0601234567",
        },
        headers=auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
