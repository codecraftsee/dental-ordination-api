"""Tests for the security guards added in the hardening pass.

Two properties are pinned here:
  1. a deployed instance refuses to boot with the built-in signing key, and
  2. unhandled crashes never echo internals back to the client.
"""

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_SECRET_KEY, Settings
from tests.conftest import auth

REAL_KEY = "z3Kq_not-the-default-key_9fXb2LmQ"


def test_default_secret_key_is_rejected_when_deployed():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="preprod", secret_key=DEFAULT_SECRET_KEY)


def test_empty_secret_key_is_rejected_when_deployed():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key="")


def test_default_secret_key_is_tolerated_locally():
    """Local dev must stay zero-config; only deployed instances are gated."""
    settings = Settings(app_env="local", secret_key=DEFAULT_SECRET_KEY)
    assert settings.secret_key == DEFAULT_SECRET_KEY


def test_a_real_secret_key_is_accepted_when_deployed():
    settings = Settings(app_env="preprod", secret_key=REAL_KEY)
    assert settings.secret_key == REAL_KEY


def test_the_guard_is_case_insensitive_about_app_env():
    assert Settings(app_env="LOCAL", secret_key=DEFAULT_SECRET_KEY)


def test_unhandled_errors_return_a_generic_500(client):
    """A crash must not echo the exception text, which carries SQL and DSNs."""
    from app.main import app

    leaky = "postgresql://postgres:hunter2@db.example.com:5432/dental"

    @app.get("/_boom_test_only")
    def boom():
        raise RuntimeError(f'relation "visits" does not exist -- {leaky}')

    try:
        resp = client.get(
            "/_boom_test_only", headers={"Origin": "http://localhost:4200"}
        )
    finally:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) != "/_boom_test_only"
        ]

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert leaky not in resp.text
    assert "relation" not in resp.text
    # The comment in main.py claims CORS stays outermost so error responses are
    # still readable by the browser. Verify that, rather than trusting it.
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:4200"


def test_failed_patient_delete_does_not_leak_db_errors(
    client, admin_token, patient, monkeypatch
):
    from sqlalchemy.orm import Session

    def explode(self, instance):
        raise RuntimeError('update or delete on table "patients" violates FK constraint')

    monkeypatch.setattr(Session, "delete", explode)

    resp = client.delete(f"/api/patients/{patient['id']}", headers=auth(admin_token))

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "violates" not in resp.text


class TestAdminLockout:
    """Nobody should be able to leave the system with no active admin.

    Deleting a user is a soft delete, and the startup seed only recreates
    admin@dentalclinic.com when the row is absent — so a lockout would need
    direct database access to undo.
    """

    def test_an_admin_cannot_delete_their_own_account(self, client, admin_token):
        me = client.get("/api/auth/me", headers=auth(admin_token)).json()

        resp = client.delete(f"/api/users/{me['id']}", headers=auth(admin_token))

        assert resp.status_code == 400
        assert resp.json()["detail"] == "You cannot deactivate your own account"
        assert client.get("/api/auth/me", headers=auth(admin_token)).status_code == 200

    def test_an_admin_cannot_deactivate_themselves_via_update(
        self, client, admin_token
    ):
        me = client.get("/api/auth/me", headers=auth(admin_token)).json()

        resp = client.put(
            f"/api/users/{me['id']}",
            json={"is_active": False},
            headers=auth(admin_token),
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "You cannot deactivate your own account"

    def test_the_only_admin_cannot_demote_themselves(self, client, admin_token):
        """The reachable lockout: role change on the sole admin."""
        me = client.get("/api/auth/me", headers=auth(admin_token)).json()

        resp = client.put(
            f"/api/users/{me['id']}", json={"role": "NURSE"}, headers=auth(admin_token)
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot remove the last active admin"
        assert (
            client.get("/api/auth/me", headers=auth(admin_token)).json()["role"]
            == "ADMIN"
        )

    def test_an_admin_can_demote_themselves_once_another_admin_exists(
        self, client, admin_token, make_user
    ):
        """The guard must not be broader than the problem it solves."""
        from app.models.user import UserRole

        make_user(role=UserRole.ADMIN)
        me = client.get("/api/auth/me", headers=auth(admin_token)).json()

        resp = client.put(
            f"/api/users/{me['id']}", json={"role": "NURSE"}, headers=auth(admin_token)
        )

        assert resp.status_code == 200
        assert resp.json()["role"] == "NURSE"

    def test_a_second_admin_can_still_be_deleted(
        self, client, admin_token, make_user
    ):
        from app.models.user import UserRole

        other = make_user(role=UserRole.ADMIN)

        resp = client.delete(f"/api/users/{other.id}", headers=auth(admin_token))

        assert resp.status_code == 204

    def test_deleting_a_non_admin_is_unaffected(self, client, admin_token, nurse):
        resp = client.delete(f"/api/users/{nurse.id}", headers=auth(admin_token))
        assert resp.status_code == 204


def test_storage_reports_a_missing_signed_url_clearly(monkeypatch):
    """A Supabase error response used to surface as a bare KeyError."""
    from app.services import storage

    class FakeBucket:
        def create_signed_url(self, path, expires_in):
            return {"error": "Object not found"}

    class FakeStorage:
        def from_(self, bucket):
            return FakeBucket()

    class FakeClient:
        storage = FakeStorage()

    monkeypatch.setattr(storage, "_client", lambda: FakeClient())

    with pytest.raises(RuntimeError, match="no signed URL"):
        storage.create_signed_url("patients/1/file.pdf")
