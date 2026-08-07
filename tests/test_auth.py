"""Characterization tests for the auth flow.

These pin the exact status codes and detail strings the Angular frontend
already depends on.
"""

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, auth, login


def test_login_returns_a_token_pair(client):
    resp = client.post(
        "/api/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_with_wrong_password_is_401(client):
    resp = client.post(
        "/api/auth/login", data={"username": ADMIN_EMAIL, "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


def test_login_with_unknown_email_is_401(client):
    resp = client.post(
        "/api/auth/login", data={"username": "nobody@dental-test.com", "password": "x"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


def test_disabled_user_cannot_log_in(client, make_user):
    user = make_user(is_active=False)
    resp = client.post(
        "/api/auth/login", data={"username": user.email, "password": "Test123#"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "User account is disabled"


def test_me_returns_profile_and_permissions(client, admin_token):
    resp = client.get("/api/auth/me", headers=auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["role"] == "ADMIN"
    assert body["must_set_password"] is False
    # Admin holds every permission; the frontend drives its menu off this list.
    assert "patients:read" in body["permissions"]
    assert "admin:bulk_delete" in body["permissions"]


def test_me_without_a_token_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_refresh_issues_a_new_pair(client):
    tokens = client.post(
        "/api/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    ).json()

    resp = client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.json()["refresh_token"]


def test_access_token_is_rejected_at_refresh(client, admin_token):
    """An access token carries no `type` claim, so it must not work here."""
    resp = client.post("/api/auth/refresh", json={"refresh_token": admin_token})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid refresh token"


def test_garbage_refresh_token_is_401(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401


def test_deactivating_a_user_invalidates_their_existing_token(client, make_user):
    """Soft-delete must take effect immediately, not at token expiry."""
    from app.database import SessionLocal
    from app.models.user import User

    user = make_user()
    token = login(client, user.email, "Test123#")
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 200

    with SessionLocal() as db:
        db.query(User).filter(User.id == user.id).update({"is_active": False})
        db.commit()

    resp = client.get("/api/auth/me", headers=auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "User account is disabled"


def test_change_password_rejects_the_current_password(client, make_user):
    user = make_user()
    token = login(client, user.email, "Test123#")

    resp = client.put(
        "/api/auth/change-password",
        json={
            "current_password": "Test123#",
            "new_password": "Test123#",
            "confirm_password": "Test123#",
        },
        headers=auth(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "New password must be different from current password"


def test_change_password_then_login_with_the_new_one(client, make_user):
    user = make_user()
    token = login(client, user.email, "Test123#")

    resp = client.put(
        "/api/auth/change-password",
        json={
            "current_password": "Test123#",
            "new_password": "NewPass456#",
            "confirm_password": "NewPass456#",
        },
        headers=auth(token),
    )
    assert resp.status_code == 200

    assert login(client, user.email, "NewPass456#")
    failed = client.post(
        "/api/auth/login", data={"username": user.email, "password": "Test123#"}
    )
    assert failed.status_code == 401


def test_health_reports_the_environment(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "env": "test"}
