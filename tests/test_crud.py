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
def test_get_missing_resource_is_404_with_its_own_message(client, admin_token, path, detail):
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
def test_delete_missing_resource_is_404_with_its_own_message(client, admin_token, path, detail):
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
    resp = client.patch(f"/api/patients/{patient['id']}/dismiss-warning", headers=auth(admin_token))
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

    updated = client.put(f"/api/visits/{visit_id}", json={"paid": False}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["paid"] is False

    assert client.delete(f"/api/visits/{visit_id}", headers=headers).status_code == 204


def test_a_visit_date_can_actually_be_changed(client, admin_token, patient, doctor):
    """Regression: VisitUpdate.date used to be annotated NoneType.

    The field name shadowed the imported `date` type inside the class body, so
    `Optional[date]` silently became `Optional[None]` and every real date was
    rejected with a 422. Nothing caught it because the lifecycle test above only
    ever updates `paid`.
    """
    headers = auth(admin_token)
    visit_id = client.post(
        "/api/visits",
        json={"patient_id": patient["id"], "doctor_id": doctor.id, "date": "2024-03-01"},
        headers=headers,
    ).json()["id"]

    updated = client.put(f"/api/visits/{visit_id}", json={"date": "2024-09-30"}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["date"] == "2024-09-30"

    # and null is still rejected, since visits.date is NOT NULL
    nulled = client.put(f"/api/visits/{visit_id}", json={"date": None}, headers=headers)
    assert nulled.status_code == 400
    assert nulled.json()["detail"] == "Field 'date' cannot be null"


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

    by_patient = client.get("/api/visits", params={"patient_id": patient["id"]}, headers=headers)
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

    resp = client.put(f"/api/diagnoses/{second['id']}", json={"code": "T-200"}, headers=headers)
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

    resp = client.put(f"/api/treatments/{second['id']}", json={"code": "TX-901"}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Treatment code already in use"


def test_category_filters(client, admin_token):
    headers = auth(admin_token)

    caries = client.get("/api/diagnoses", params={"category": "Caries"}, headers=headers).json()
    assert caries and all(d["category"] == "Caries" for d in caries)

    endo = client.get("/api/treatments", params={"category": "Endodontic"}, headers=headers).json()
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


class TestUserInvites:
    """POST /api/users and resend-invite, with the Resend call stubbed out.

    A created user has no password: they receive a signed link and set one via
    /api/auth/set-password.
    """

    @pytest.fixture
    def sent(self, monkeypatch):
        from app.routers import users as users_router

        captured = []
        monkeypatch.setattr(
            users_router,
            "send_invite_email",
            lambda to, name, url: captured.append((to, name, url)),
        )
        return captured

    def test_creating_a_user_sends_an_invite_link(self, client, admin_token, sent):
        resp = client.post(
            "/api/users",
            json={
                "email": "newdoc@dental-test.com",
                "first_name": "New",
                "last_name": "Doc",
                "role": "DOCTOR",
            },
            headers=auth(admin_token),
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["must_set_password"] is True
        assert body["permissions"] == []

        assert len(sent) == 1
        to, name, url = sent[0]
        assert to == "newdoc@dental-test.com"
        assert name == "New"
        assert "/set-password?token=" in url

    def test_a_created_user_cannot_log_in_until_they_set_a_password(
        self, client, admin_token, sent
    ):
        client.post(
            "/api/users",
            json={
                "email": "nopass@dental-test.com",
                "first_name": "No",
                "last_name": "Pass",
            },
            headers=auth(admin_token),
        )

        resp = client.post(
            "/api/auth/login",
            data={"username": "nopass@dental-test.com", "password": "anything"},
        )
        assert resp.status_code == 401

    def test_a_failing_email_does_not_fail_the_request(self, client, admin_token, monkeypatch):
        """The user is still created; the invite link can be handed over manually."""
        from app.routers import users as users_router

        def boom(*args, **kwargs):
            raise RuntimeError("Resend is down")

        monkeypatch.setattr(users_router, "send_invite_email", boom)

        resp = client.post(
            "/api/users",
            json={
                "email": "resilient@dental-test.com",
                "first_name": "Still",
                "last_name": "Created",
            },
            headers=auth(admin_token),
        )
        assert resp.status_code == 201

    def test_resend_invite(self, client, admin_token, sent):
        created = client.post(
            "/api/users",
            json={
                "email": "again@dental-test.com",
                "first_name": "Again",
                "last_name": "User",
            },
            headers=auth(admin_token),
        ).json()
        sent.clear()

        resp = client.post(f"/api/users/{created['id']}/resend-invite", headers=auth(admin_token))

        assert resp.status_code == 204
        assert len(sent) == 1

    def test_resend_invite_for_an_unknown_user_is_404(self, client, admin_token, sent):
        resp = client.post(f"/api/users/{MISSING_ID}/resend-invite", headers=auth(admin_token))
        assert resp.status_code == 404
        assert resp.json()["detail"] == "User not found"

    def test_resend_invite_after_the_password_is_set_is_400(self, client, admin_token, nurse, sent):
        resp = client.post(f"/api/users/{nurse.id}/resend-invite", headers=auth(admin_token))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "User has already set their password"


class TestExplicitNulls:
    """A field sent as `null` must be a 400, not a 500.

    model_dump(exclude_unset=True) keeps explicit nulls, so these used to reach
    the database and fail a NOT NULL constraint.
    """

    def test_nulling_a_required_user_field_is_400(self, client, admin_token, nurse):
        resp = client.put(f"/api/users/{nurse.id}", json={"role": None}, headers=auth(admin_token))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Field 'role' cannot be null"

    def test_nulling_a_required_patient_field_is_400(self, client, admin_token, patient):
        resp = client.put(
            f"/api/patients/{patient['id']}",
            json={"first_name": None},
            headers=auth(admin_token),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Field 'first_name' cannot be null"

    def test_nulling_a_required_visit_field_is_400(self, client, admin_token, patient, doctor):
        visit = client.post(
            "/api/visits",
            json={"patient_id": patient["id"], "doctor_id": doctor.id, "date": "2024-03-01"},
            headers=auth(admin_token),
        ).json()

        resp = client.put(
            f"/api/visits/{visit['id']}", json={"date": None}, headers=auth(admin_token)
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Field 'date' cannot be null"

    def test_nulling_an_optional_field_still_works(self, client, admin_token, patient):
        """The guard must only fire on columns that are actually NOT NULL."""
        resp = client.put(
            f"/api/patients/{patient['id']}",
            json={"phone": None},
            headers=auth(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["phone"] is None

    def test_a_rejected_update_leaves_the_row_untouched(self, client, admin_token, patient):
        """Validation happens before any field is applied."""
        resp = client.put(
            f"/api/patients/{patient['id']}",
            json={"city": "Kragujevac", "first_name": None},
            headers=auth(admin_token),
        )
        assert resp.status_code == 400

        after = client.get(f"/api/patients/{patient['id']}", headers=auth(admin_token)).json()
        assert after["city"] == "Novi Sad"
        assert after["first_name"] == "Ana"


class TestAdminBulkDelete:
    def test_delete_all_patients_takes_their_visits_too(self, client, admin_token, patient, doctor):
        headers = auth(admin_token)
        client.post(
            "/api/visits",
            json={"patient_id": patient["id"], "doctor_id": doctor.id, "date": "2024-03-01"},
            headers=headers,
        )

        resp = client.delete("/api/admin/patients", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}
        assert client.get("/api/patients", headers=headers).json() == []
        assert client.get("/api/visits", headers=headers).json() == []

    def test_delete_all_diagnoses(self, client, admin_token):
        headers = auth(admin_token)
        seeded = len(client.get("/api/diagnoses", headers=headers).json())
        assert seeded == 6

        resp = client.delete("/api/admin/diagnoses", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {"deleted": seeded}
        assert client.get("/api/diagnoses", headers=headers).json() == []

    def test_delete_all_treatments(self, client, admin_token):
        headers = auth(admin_token)
        seeded = len(client.get("/api/treatments", headers=headers).json())
        assert seeded == 6

        resp = client.delete("/api/admin/treatments", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {"deleted": seeded}
        assert client.get("/api/treatments", headers=headers).json() == []

    def _visit_referencing_catalogue(self, client, headers, patient, doctor):
        diagnosis = client.get("/api/diagnoses", headers=headers).json()[0]
        treatment = client.get("/api/treatments", headers=headers).json()[0]
        return client.post(
            "/api/visits",
            json={
                "patient_id": patient["id"],
                "doctor_id": doctor.id,
                "date": "2024-03-01",
                "diagnosis_id": diagnosis["id"],
                "treatment_id": treatment["id"],
                "diagnosis_notes": "Caries d.16",
            },
            headers=headers,
        ).json()

    def test_deleting_diagnoses_unlinks_visits_instead_of_failing(
        self, client, admin_token, patient, doctor
    ):
        """visits.diagnosis_id is a FK; this used to 500 on any real database."""
        headers = auth(admin_token)
        visit = self._visit_referencing_catalogue(client, headers, patient, doctor)

        resp = client.delete("/api/admin/diagnoses", headers=headers)
        assert resp.status_code == 200

        after = client.get(f"/api/visits/{visit['id']}", headers=headers).json()
        assert after["diagnosis_id"] is None
        # The visit itself and its clinical notes survive.
        assert after["diagnosis_notes"] == "Caries d.16"

    def test_deleting_treatments_unlinks_visits_instead_of_failing(
        self, client, admin_token, patient, doctor
    ):
        headers = auth(admin_token)
        visit = self._visit_referencing_catalogue(client, headers, patient, doctor)

        resp = client.delete("/api/admin/treatments", headers=headers)
        assert resp.status_code == 200

        after = client.get(f"/api/visits/{visit['id']}", headers=headers).json()
        assert after["treatment_id"] is None
        assert after["diagnosis_notes"] == "Caries d.16"

    def test_delete_all_still_works_with_linked_visits(self, client, admin_token, patient, doctor):
        headers = auth(admin_token)
        self._visit_referencing_catalogue(client, headers, patient, doctor)

        resp = client.delete("/api/admin/all", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["visits"] == 1

    def test_delete_all_returns_a_count_per_resource(self, client, admin_token, patient, doctor):
        headers = auth(admin_token)
        client.post(
            "/api/visits",
            json={"patient_id": patient["id"], "doctor_id": doctor.id, "date": "2024-03-01"},
            headers=headers,
        )

        resp = client.delete("/api/admin/all", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "visits": 1,
            "patients": 1,
            "diagnoses": 6,
            "treatments": 6,
        }
        for path in ("/api/visits", "/api/patients", "/api/diagnoses", "/api/treatments"):
            assert client.get(path, headers=headers).json() == [], path

    def test_bulk_delete_leaves_users_alone(self, client, admin_token, doctor):
        """Doctors are users; wiping data must not remove the people."""
        headers = auth(admin_token)

        client.delete("/api/admin/all", headers=headers)

        users = client.get("/api/users", headers=headers).json()
        assert doctor.id in [u["id"] for u in users]


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


def test_a_hand_created_visit_has_no_imported_doctor_label(client, admin_token, patient, doctor):
    """The label quotes a source document, and a visit typed into the UI has none."""
    headers = auth(admin_token)

    created = client.post(
        "/api/visits",
        json={
            "patient_id": patient["id"],
            "doctor_id": doctor.id,
            "date": "2024-03-01",
            "diagnosis_notes": "Caries d.16",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["imported_doctor_label"] is None


def test_the_imported_doctor_label_cannot_be_set_through_the_api(
    client, admin_token, patient, doctor
):
    """Read-only by omission from VisitBase: returned, never accepted.

    It records what the card claimed, so resolving a flagged visit has to mean
    correcting `doctor_id`. Letting the quote itself be rewritten would destroy
    the only evidence of who the document originally named.
    """
    headers = auth(admin_token)

    created = client.post(
        "/api/visits",
        json={
            "patient_id": patient["id"],
            "doctor_id": doctor.id,
            "date": "2024-03-01",
            "imported_doctor_label": "M",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["imported_doctor_label"] is None

    visit_id = created.json()["id"]
    updated = client.put(
        f"/api/visits/{visit_id}",
        json={"imported_doctor_label": "Z"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["imported_doctor_label"] is None
