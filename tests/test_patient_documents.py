"""Tests for the patient-documents router, with Supabase Storage mocked.

The router talks to Supabase on every path, so these fake out
``app.services.storage`` rather than reaching the network. That is enough to
cover the routing, permission and 404 logic, which is what the shared
get_or_404 refactor touched.
"""

import pytest

from tests.conftest import auth

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def fake_storage(monkeypatch):
    """Replace the Supabase calls with in-memory bookkeeping."""
    from app.routers import patient_documents as router_module

    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def upload_bytes(path, data, content_type):
        uploaded[path] = data

    def create_signed_url(path, expires_in=3600):
        return f"https://storage.test/{path}?signed=1"

    def delete(path):
        deleted.append(path)
        uploaded.pop(path, None)

    monkeypatch.setattr(router_module.storage, "upload_bytes", upload_bytes)
    monkeypatch.setattr(router_module.storage, "create_signed_url", create_signed_url)
    monkeypatch.setattr(router_module.storage, "delete", delete)

    return {"uploaded": uploaded, "deleted": deleted}


def _upload(client, token, patient_id, *, name="xray.png", data=PNG, mime="image/png"):
    return client.post(
        f"/api/patients/{patient_id}/documents",
        files={"file": (name, data, mime)},
        headers=auth(token),
    )


def test_upload_then_list_and_fetch(client, admin_token, patient, fake_storage):
    created = _upload(client, admin_token, patient["id"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["filename"] == "xray.png"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(PNG)
    assert body["signed_url"].startswith("https://storage.test/")
    assert len(fake_storage["uploaded"]) == 1

    listed = client.get(
        f"/api/patients/{patient['id']}/documents", headers=auth(admin_token)
    )
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [body["id"]]

    fetched = client.get(
        f"/api/patients/{patient['id']}/documents/{body['id']}",
        headers=auth(admin_token),
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_delete_removes_the_row_and_the_stored_object(
    client, admin_token, patient, fake_storage
):
    doc = _upload(client, admin_token, patient["id"]).json()

    resp = client.delete(
        f"/api/patients/{patient['id']}/documents/{doc['id']}",
        headers=auth(admin_token),
    )
    assert resp.status_code == 204
    assert len(fake_storage["deleted"]) == 1

    listed = client.get(
        f"/api/patients/{patient['id']}/documents", headers=auth(admin_token)
    )
    assert listed.json() == []


def test_missing_patient_is_404_with_the_patient_message(
    client, admin_token, fake_storage
):
    missing = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/patients/{missing}/documents", headers=auth(admin_token))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Patient not found"


def test_missing_document_is_404_with_the_document_message(
    client, admin_token, patient, fake_storage
):
    missing = "00000000-0000-0000-0000-000000000000"
    resp = client.get(
        f"/api/patients/{patient['id']}/documents/{missing}", headers=auth(admin_token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document not found"


def test_a_document_cannot_be_read_through_another_patient(
    client, admin_token, patient, fake_storage
):
    """The lookup filters on patient_id too, so cross-patient ids must 404."""
    doc = _upload(client, admin_token, patient["id"]).json()

    other = client.post(
        "/api/patients",
        json={
            "first_name": "Other",
            "last_name": "Person",
            "gender": "male",
            "date_of_birth": "1980-01-01",
        },
        headers=auth(admin_token),
    ).json()

    resp = client.get(
        f"/api/patients/{other['id']}/documents/{doc['id']}", headers=auth(admin_token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document not found"


def test_unsupported_content_type_is_415(client, admin_token, patient, fake_storage):
    resp = _upload(
        client, admin_token, patient["id"], name="notes.txt", mime="text/plain"
    )
    assert resp.status_code == 415
    assert "Unsupported file type" in resp.json()["detail"]


def test_empty_file_is_400(client, admin_token, patient, fake_storage):
    resp = _upload(client, admin_token, patient["id"], data=b"")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Uploaded file is empty"


def test_nurse_cannot_upload_but_can_read(
    client, nurse_token, admin_token, patient, fake_storage
):
    assert _upload(client, nurse_token, patient["id"]).status_code == 403

    _upload(client, admin_token, patient["id"])
    listed = client.get(
        f"/api/patients/{patient['id']}/documents", headers=auth(nurse_token)
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_nurse_cannot_delete(client, nurse_token, admin_token, patient, fake_storage):
    doc = _upload(client, admin_token, patient["id"]).json()
    resp = client.delete(
        f"/api/patients/{patient['id']}/documents/{doc['id']}",
        headers=auth(nurse_token),
    )
    assert resp.status_code == 403
