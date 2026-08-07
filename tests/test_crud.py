"""Characterization tests for the CRUD routers.

These pin the 404 detail strings and status codes verbatim. The get-or-404
block is currently written out 18 times across five routers; when it is
replaced by one shared helper, these tests are what proves each endpoint still
says the same thing.
"""

import pytest

from tests.conftest import auth

MISSING_ID = "00000000-0000-0000-0000-000000000000"


def test_patient_lifecycle(client, admin_token):
    headers = auth(admin_token)

    created = client.post(
        "/api/patients",
        json={
            "first_name": "Jovan",
            "last_name": "Jovanovic",
            "gender": "male",
            "date_of_birth": "1975-03-12",
            "city": "Beograd",
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["first_name"] == "Jovan"
    assert body["import_incomplete"] is False
    patient_id = body["id"]

    fetched = client.get(f"/api/patients/{patient_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == patient_id

    updated = client.put(
        f"/api/patients/{patient_id}",
        json={"city": "Nis", "phone": "0611111111"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["city"] == "Nis"
    # A partial update must not blank the untouched fields.
    assert updated.json()["first_name"] == "Jovan"

    assert client.delete(f"/api/patients/{patient_id}", headers=headers).status_code == 204
    assert client.get(f"/api/patients/{patient_id}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "path,detail",
    [
        ("/api/patients", "Patient not found"),
        ("/api/visits", "Visit not found"),
        ("/api/diagnoses", "Diagnosis not found"),
        ("/api/treatments", "Treatment not found"),
        ("/api/users", "User not found"),
    ],
)
def test_get_missing_resource_is_404_with_its_own_message(
    client, admin_token, path, detail
):
    resp = client.get(f"{path}/{MISSING_ID}", headers=auth(admin_token))
    assert resp.status_code == 404
    assert resp.json()["detail"] == detail


@pytest.mark.parametrize(
    "path,detail",
    [
        ("/api/patients", "Patient not found"),
        ("/api/visits", "Visit not found"),
        ("/api/diagnoses", "Diagnosis not found"),
        ("/api/treatments", "Treatment not found"),
        ("/api/users", "User not found"),
    ],
)
def test_delete_missing_resource_is_404_with_its_own_message(
    client, admin_token, path, detail
):
    resp = client.delete(f"{path}/{MISSING_ID}", headers=auth(admin_token))
    assert resp.status_code == 404
    assert resp.json()["detail"] == detail


def test_patient_search_and_city_filters(client, admin_token, patient):
    headers = auth(admin_token)

    hits = client.get("/api/patients", params={"search": "Nikol"}, headers=headers)
    assert [p["id"] for p in hits.json()] == [patient["id"]]

    misses = client.get("/api/patients", params={"search": "zzzz"}, headers=headers)
    assert misses.json() == []

    by_city = client.get("/api/patients", params={"city": "Novi Sad"}, headers=headers)
    assert [p["id"] for p in by_city.json()] == [patient["id"]]


def test_dismiss_patient_import_warning(client, admin_token, patient):
    resp = client.patch(
        f"/api/patients/{patient['id']}/dismiss-warning", headers=auth(admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["import_incomplete"] is False


def test_visit_lifecycle_and_embedded_doctor(client, admin_token, patient, doctor):
    headers = auth(admin_token)

    created = client.post(
        "/api/visits",
        json={
            "patient_id": patient["id"],
            "doctor_id": doctor.id,
            "date": "2024-03-01",
            "tooth_number": 16,
            "diagnosis_notes": "Caries d.16",
            "treatment_notes": "Composite filling",
            "price": "4000.00",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    visit_id = created.json()["id"]

    listed = client.get("/api/visits", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["doctor"]["first_name"] == "Milan"

    fetched = client.get(f"/api/visits/{visit_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tooth_number"] == 16

    updated = client.put(
        f"/api/visits/{visit_id}", json={"paid": False}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["paid"] is False

    assert client.delete(f"/api/visits/{visit_id}", headers=headers).status_code == 204


def test_visit_filters(client, admin_token, patient, doctor):
    headers = auth(admin_token)
    for visit_date in ("2024-01-15", "2024-06-15"):
        client.post(
            "/api/visits",
            json={
                "patient_id": patient["id"],
                "doctor_id": doctor.id,
                "date": visit_date,
            },
            headers=headers,
        )

    ranged = client.get(
        "/api/visits",
        params={"date_from": "2024-05-01", "date_to": "2024-12-31"},
        headers=headers,
    )
    assert [v["date"] for v in ranged.json()] == ["2024-06-15"]

    by_patient = client.get(
        "/api/visits", params={"patient_id": patient["id"]}, headers=headers
    )
    assert len(by_patient.json()) == 2
    # Newest first.
    assert by_patient.json()[0]["date"] == "2024-06-15"


def test_diagnosis_duplicate_code_is_rejected(client, admin_token):
    headers = auth(admin_token)
    payload = {"code": "T-100", "name": "Test diagnosis", "category": "Caries"}

    assert client.post("/api/diagnoses", json=payload, headers=headers).status_code == 201

    dupe = client.post("/api/diagnoses", json=payload, headers=headers)
    assert dupe.status_code == 400
    assert dupe.json()["detail"] == "Diagnosis code already exists"


def test_diagnosis_update_to_a_taken_code_is_rejected(client, admin_token):
    headers = auth(admin_token)
    client.post(
        "/api/diagnoses",
        json={"code": "T-200", "name": "A", "category": "Caries"},
        headers=headers,
    )
    second = client.post(
        "/api/diagnoses",
        json={"code": "T-201", "name": "B", "category": "Caries"},
        headers=headers,
    ).json()

    resp = client.put(
        f"/api/diagnoses/{second['id']}", json={"code": "T-200"}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Diagnosis code already in use"


def test_treatment_duplicate_code_is_rejected(client, admin_token):
    headers = auth(admin_token)
    payload = {
        "code": "TX-900",
        "name": "Test treatment",
        "category": "Preventive",
        "default_price": "1000.00",
    }

    assert client.post("/api/treatments", json=payload, headers=headers).status_code == 201

    dupe = client.post("/api/treatments", json=payload, headers=headers)
    assert dupe.status_code == 400
    assert dupe.json()["detail"] == "Treatment code already exists"


def test_treatment_update_to_a_taken_code_is_rejected(client, admin_token):
    headers = auth(admin_token)
    client.post(
        "/api/treatments",
        json={"code": "TX-901", "name": "A", "category": "Preventive"},
        headers=headers,
    )
    second = client.post(
        "/api/treatments",
        json={"code": "TX-902", "name": "B", "category": "Preventive"},
        headers=headers,
    ).json()

    resp = client.put(
        f"/api/treatments/{second['id']}", json={"code": "TX-901"}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Treatment code already in use"


def test_category_filters(client, admin_token):
    headers = auth(admin_token)

    caries = client.get(
        "/api/diagnoses", params={"category": "Caries"}, headers=headers
    ).json()
    assert caries and all(d["category"] == "Caries" for d in caries)

    endo = client.get(
        "/api/treatments", params={"category": "Endodontic"}, headers=headers
    ).json()
    assert endo and all(t["category"] == "Endodontic" for t in endo)


def test_duplicate_user_email_is_rejected(client, admin_token, nurse):
    resp = client.post(
        "/api/users",
        json={"email": nurse.email, "first_name": "Dup", "last_name": "User"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Email already registered"


def test_deleting_a_user_is_a_soft_delete(client, admin_token, nurse):
    headers = auth(admin_token)

    assert client.delete(f"/api/users/{nurse.id}", headers=headers).status_code == 204

    # Still fetchable by id...
    assert client.get(f"/api/users/{nurse.id}", headers=headers).status_code == 200
    # ...but gone from the list, which filters on is_active.
    listed = client.get("/api/users", headers=headers).json()
    assert nurse.id not in [u["id"] for u in listed]


def test_admin_bulk_delete_clears_visits_only(client, admin_token, patient, doctor):
    headers = auth(admin_token)
    client.post(
        "/api/visits",
        json={"patient_id": patient["id"], "doctor_id": doctor.id, "date": "2024-03-01"},
        headers=headers,
    )

    resp = client.delete("/api/admin/visits", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1}

    assert client.get("/api/visits", headers=headers).json() == []
    assert len(client.get("/api/patients", headers=headers).json()) == 1
