"""Characterization tests for role-based access.

This is the file that guards the shared-dependency refactor: if the permission
wiring on any endpoint changes, one of these flips.
"""

from tests.conftest import auth

PATIENT_PAYLOAD = {
    "first_name": "Petar",
    "last_name": "Petrovic",
    "gender": "male",
    "date_of_birth": "1985-05-05",
}


def test_unauthenticated_requests_are_401(client):
    for path in ("/api/patients", "/api/visits", "/api/users", "/api/diagnoses"):
        assert client.get(path).status_code == 401, path


def test_nurse_can_read_patients(client, nurse_token):
    assert client.get("/api/patients", headers=auth(nurse_token)).status_code == 200


def test_nurse_cannot_create_a_patient(client, nurse_token):
    resp = client.post("/api/patients", json=PATIENT_PAYLOAD, headers=auth(nurse_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Insufficient permissions"


def test_nurse_cannot_delete_a_patient(client, nurse_token, patient):
    resp = client.delete(f"/api/patients/{patient['id']}", headers=auth(nurse_token))
    assert resp.status_code == 403


def test_doctor_can_create_a_patient(client, doctor_token):
    resp = client.post("/api/patients", json=PATIENT_PAYLOAD, headers=auth(doctor_token))
    assert resp.status_code == 201


def test_doctor_cannot_delete_a_patient(client, doctor_token, patient):
    """Doctors hold PATIENTS_UPDATE but deliberately not PATIENTS_DELETE."""
    resp = client.delete(f"/api/patients/{patient['id']}", headers=auth(doctor_token))
    assert resp.status_code == 403


def test_admin_can_delete_a_patient(client, admin_token, patient):
    resp = client.delete(f"/api/patients/{patient['id']}", headers=auth(admin_token))
    assert resp.status_code == 204


def test_non_admin_user_list_hides_admins(client, nurse_token):
    users = client.get("/api/users", headers=auth(nurse_token)).json()
    assert users, "nurse should see the non-admin users"
    assert all(u["role"] != "ADMIN" for u in users)


def test_admin_user_list_includes_admins(client, admin_token):
    users = client.get("/api/users", headers=auth(admin_token)).json()
    assert any(u["role"] == "ADMIN" for u in users)


def test_user_list_omits_permissions(client, admin_token):
    """GET /api/users returns an empty permissions list; only /me populates it.

    Pinned because it is exactly the kind of detail a shared response helper
    would silently change.
    """
    users = client.get("/api/users", headers=auth(admin_token)).json()
    assert all(u["permissions"] == [] for u in users)


def test_nurse_cannot_create_a_user(client, nurse_token):
    resp = client.post(
        "/api/users",
        json={"email": "x@dental-test.com", "first_name": "X", "last_name": "Y"},
        headers=auth(nurse_token),
    )
    assert resp.status_code == 403


def test_nurse_cannot_bulk_delete(client, nurse_token):
    assert client.delete("/api/admin/visits", headers=auth(nurse_token)).status_code == 403


def test_doctor_cannot_bulk_delete(client, doctor_token):
    assert client.delete("/api/admin/all", headers=auth(doctor_token)).status_code == 403


def test_nurse_cannot_import(client, nurse_token):
    resp = client.post(
        "/api/import/xlsx",
        files=[("files", ("card.xlsx", b"not-a-real-xlsx", "application/vnd.ms-excel"))],
        headers=auth(nurse_token),
    )
    assert resp.status_code == 403
