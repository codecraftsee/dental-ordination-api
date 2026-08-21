"""Characterization tests for POST /api/import/xlsx.

The endpoint streams Server-Sent Events rather than returning JSON, and the
frontend parses that stream by hand. These tests pin the event sequence and the
payload keys, which is the contract that must survive the import refactor.
"""

import json
from io import BytesIO

from openpyxl import Workbook

from tests.conftest import auth

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_xlsx(rows: list[list]) -> bytes:
    """Write a sheet from a list of row-lists (None leaves the cell empty)."""
    wb = Workbook()
    ws = wb.active
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            if value is not None:
                ws.cell(row=r, column=c, value=value)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _dental_card(
    visit_rows: list[list],
    *,
    gender: str = "m",
    dob: str = "01.02.1990.",
    first_name: str = "Marko",
    last_name: str = "Petrovic",
    parent_name: str | None = "Jovan",
    address: str | None = "Glavna 1",
    city: str | None = "Novi Sad",
    phone: str | None = "0601234567",
    email: str | None = "marko@dental-test.com",
) -> bytes:
    """A dental card in the layout the importer expects.

    Patient details sit in column C of rows 3-11 (indices 2-10), and visit rows
    start at index 14. The contact fields are overridable — `None` leaves the
    cell empty, which is how a card that simply does not record one looks.
    """
    rows: list[list] = [[] for _ in range(14)]
    rows[2] = [None, "Pol", gender]
    rows[3] = [None, "Prezime", last_name]
    rows[4] = [None, "Ime", first_name]
    rows[5] = [None, "Roditelj", parent_name]
    rows[6] = [None, "Datum rodjenja", dob]
    rows[7] = [None, "Adresa", address]
    rows[8] = [None, "Grad", city]
    rows[9] = [None, "Telefon", phone]
    rows[10] = [None, "Email", email]
    rows[13] = ["Datum", None, "Dijagnoza", None, "Terapija", "Dr", "Cena"]
    return _build_xlsx(rows + visit_rows)


VISIT_ROW = ["01.03.2024.", None, "Caries d.16", None, "Composite filling", "M", "4.000,00 din"]


def _post(client, token, content: bytes, filename: str = "card.xlsx", **data):
    return client.post(
        "/api/import/xlsx",
        files=[("files", (filename, content, XLSX_MIME))],
        data=data,
        headers=auth(token),
    )


def _events(response) -> list[dict]:
    return [
        json.loads(chunk[len("data: ") :])
        for chunk in response.text.strip().split("\n\n")
        if chunk.startswith("data: ")
    ]


def test_import_streams_progress_then_file_done_then_complete(client, admin_token, doctor):
    resp = _post(client, admin_token, _dental_card([VISIT_ROW]))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _events(resp)
    assert [e["type"] for e in events] == ["progress", "file_done", "complete"]

    progress, file_done, complete = events
    assert progress == {
        "type": "progress",
        "current": 1,
        "total": 1,
        "file": "card.xlsx",
        "status": "processing",
    }
    assert file_done["file"] == "card.xlsx"
    assert file_done["patients_created"] == 1
    assert file_done["visits_created"] == 1
    assert file_done["errors"] == []

    summary = complete["summary"]
    assert summary["files_processed"] == 1
    assert summary["patients_created"] == 1
    assert summary["visits_created"] == 1
    assert summary["errors"] == []


def test_import_persists_the_patient_and_visit(client, admin_token, doctor):
    _post(client, admin_token, _dental_card([VISIT_ROW]))
    headers = auth(admin_token)

    patients = client.get("/api/patients", headers=headers).json()
    assert len(patients) == 1
    assert patients[0]["first_name"] == "Marko"
    assert patients[0]["last_name"] == "Petrovic"
    assert patients[0]["gender"] == "male"
    assert patients[0]["date_of_birth"] == "1990-02-01"

    visits = client.get("/api/visits", headers=headers).json()
    assert len(visits) == 1
    assert visits[0]["date"] == "2024-03-01"
    assert visits[0]["tooth_number"] == 16
    assert visits[0]["diagnosis_notes"] == "Caries d.16"
    # "4.000,00 din" is European notation: dot groups thousands, comma decimals.
    assert float(visits[0]["price"]) == 4000.00
    assert visits[0]["paid"] is True
    assert visits[0]["import_incomplete"] is False


def test_reimporting_the_same_file_skips_duplicate_visits(client, admin_token, doctor):
    card = _dental_card([VISIT_ROW])
    _post(client, admin_token, card)

    summary = _events(_post(client, admin_token, card))[-1]["summary"]
    assert summary["patients_found"] == 1
    assert summary["patients_created"] == 0
    assert summary["visits_created"] == 0
    assert summary["visits_skipped"] == 1


def test_a_row_without_a_price_is_flagged_incomplete(client, admin_token, doctor):
    row = ["01.03.2024.", None, "Caries d.24", None, "Extraction", "M", None]
    summary = _events(_post(client, admin_token, _dental_card([row])))[-1]["summary"]

    assert summary["visits_created"] == 1
    assert summary["visits_incomplete"] == 1

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["import_incomplete"] is True
    assert visits[0]["price"] is None


def test_an_unreadable_gender_flags_the_patient_and_reports_it(client, admin_token, doctor):
    card = _dental_card([VISIT_ROW], gender="?")
    summary = _events(_post(client, admin_token, card))[-1]["summary"]

    assert summary["patients_created"] == 1
    assert summary["patients_incomplete"] == 1
    assert any("Invalid gender" in e for e in summary["errors"])

    patients = client.get("/api/patients", headers=auth(admin_token)).json()
    assert patients[0]["gender"] == "male"
    assert patients[0]["import_incomplete"] is True


def test_a_missing_patient_name_reports_an_error_and_imports_nothing(client, admin_token, doctor):
    card = _dental_card([VISIT_ROW], first_name="", last_name="")
    summary = _events(_post(client, admin_token, card))[-1]["summary"]

    assert summary["patients_created"] == 0
    assert summary["visits_created"] == 0
    assert any("Missing patient name" in e for e in summary["errors"])
    assert client.get("/api/patients", headers=auth(admin_token)).json() == []


def test_a_corrupt_file_fails_alone_without_killing_the_stream(client, admin_token, doctor):
    resp = client.post(
        "/api/import/xlsx",
        files=[
            ("files", ("broken.xlsx", b"definitely not a workbook", XLSX_MIME)),
            ("files", ("good.xlsx", _dental_card([VISIT_ROW]), XLSX_MIME)),
        ],
        headers=auth(admin_token),
    )

    events = _events(resp)
    assert [e["type"] for e in events] == [
        "progress",
        "file_done",
        "progress",
        "file_done",
        "complete",
    ]

    broken, good = events[1], events[3]
    assert broken["errors"], "the corrupt file should report an error"
    assert broken["patients_created"] == 0
    # The second file is committed independently of the first one's failure.
    assert good["patients_created"] == 1
    assert good["errors"] == []

    summary = events[-1]["summary"]
    assert summary["files_processed"] == 2
    assert summary["patients_created"] == 1


def test_doctor_id_form_field_overrides_row_initials(client, admin_token, doctor, make_user):
    from app.models.user import UserRole

    other = make_user(role=UserRole.DOCTOR, first_name="Zoran")

    # The row says "M" (Milan), but the explicit doctor_id must win.
    _post(client, admin_token, _dental_card([VISIT_ROW]), doctor_id=other.id)

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] == other.id


def test_a_file_with_too_few_rows_is_reported(client, admin_token, doctor):
    short = _build_xlsx([["Dental card"], [], ["only three rows"]])
    summary = _events(_post(client, admin_token, short))[-1]["summary"]

    assert summary["patients_created"] == 0
    assert any("File too short" in e for e in summary["errors"])


def test_a_later_card_fills_a_blank_field_on_a_matched_patient(client, admin_token, doctor):
    """The first card had no phone; the second supplies one."""
    _post(client, admin_token, _dental_card([VISIT_ROW], phone=None))
    resp = _post(client, admin_token, _dental_card([VISIT_ROW], phone="0605555555"))
    summary = _events(resp)[-1]["summary"]

    assert summary["patients_found"] == 1
    assert summary["patients_created"] == 0
    assert summary["patients_updated"] == 1

    patients = client.get("/api/patients", headers=auth(admin_token)).json()
    assert len(patients) == 1
    assert patients[0]["phone"] == "0605555555"


def test_a_later_card_never_overwrites_a_field_that_has_a_value(client, admin_token, doctor):
    """Fill-only. The first value wins, so a re-import cannot undo a correction."""
    _post(client, admin_token, _dental_card([VISIT_ROW], phone="0601111111"))
    resp = _post(client, admin_token, _dental_card([VISIT_ROW], phone="0602222222"))
    summary = _events(resp)[-1]["summary"]

    assert summary["patients_found"] == 1
    assert summary["patients_updated"] == 0

    patients = client.get("/api/patients", headers=auth(admin_token)).json()
    assert patients[0]["phone"] == "0601111111"


def test_re_importing_an_identical_card_reports_no_update(client, admin_token, doctor):
    """patients_updated counts writes, not matches — nothing changed here."""
    card = _dental_card([VISIT_ROW])
    _post(client, admin_token, card)
    summary = _events(_post(client, admin_token, card))[-1]["summary"]

    assert summary["patients_found"] == 1
    assert summary["patients_updated"] == 0


def test_filling_blanks_leaves_the_match_key_and_gender_alone(client, admin_token, doctor):
    """A card differing only in gender must not rewrite the stored patient."""
    _post(client, admin_token, _dental_card([VISIT_ROW], gender="m"))
    _post(client, admin_token, _dental_card([VISIT_ROW], gender="z"))

    patients = client.get("/api/patients", headers=auth(admin_token)).json()
    assert len(patients) == 1
    assert patients[0]["gender"] == "male"


def test_a_card_with_no_visit_rows_is_reported(client, admin_token, doctor):
    """The patient parses, the visit table does not — previously silent success."""
    summary = _events(_post(client, admin_token, _dental_card([])))[-1]["summary"]

    assert summary["patients_created"] == 1
    assert summary["visits_created"] == 0
    assert any("No visit rows found" in e for e in summary["errors"])


def test_a_reimported_card_is_not_mistaken_for_an_empty_one(client, admin_token, doctor):
    """Its rows are seen and skipped as duplicates, which is not 'none found'."""
    card = _dental_card([VISIT_ROW])
    _post(client, admin_token, card)
    summary = _events(_post(client, admin_token, card))[-1]["summary"]

    assert summary["visits_skipped"] == 1
    assert not any("No visit rows found" in e for e in summary["errors"])


def test_a_tooth_number_outside_fdi_notation_is_discarded(client, admin_token, doctor):
    """'d. 2000' is a year or a price, not a tooth. The note text still lands."""
    row = ["01.03.2024.", None, "Kontrola d. 2000", None, "Filling", "M", "4000"]
    _post(client, admin_token, _dental_card([row]))

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["tooth_number"] is None
    assert visits[0]["diagnosis_notes"] == "Kontrola d. 2000"


def test_a_valid_fdi_tooth_number_is_kept(client, admin_token, doctor):
    _post(client, admin_token, _dental_card([VISIT_ROW]))

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["tooth_number"] == 16


def test_a_row_without_a_date_inherits_the_one_above(client, admin_token, doctor):
    """These cards are hand-written; a blank date means 'same day'."""
    rows = [
        ["01.03.2024.", None, "Caries d.16", None, "Filling", "M", "4000"],
        [None, None, "Caries d.17", None, "Filling", "M", "4000"],
    ]
    summary = _events(_post(client, admin_token, _dental_card(rows)))[-1]["summary"]
    assert summary["visits_created"] == 2

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert {v["date"] for v in visits} == {"2024-03-01"}


def test_rows_before_the_first_date_are_skipped(client, admin_token, doctor):
    rows = [
        [None, None, "Orphan row with no date yet", None, "Something", "M", "1000"],
        ["05.04.2024.", None, "Caries d.21", None, "Filling", "M", "2000"],
    ]
    summary = _events(_post(client, admin_token, _dental_card(rows)))[-1]["summary"]
    assert summary["visits_created"] == 1

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["date"] == "2024-04-05"


def test_an_ambiguous_initial_falls_back_and_flags_the_visit(client, admin_token, make_user):
    """Two doctors share the initial 'M', so it must not resolve to either by name.

    The fallback still assigns somebody — `visits.doctor_id` is NOT NULL — but
    that id is a stand-in, not an identification, so the row is flagged for
    review and reported rather than passing as fact.
    """
    from app.models.user import UserRole

    milan = make_user(role=UserRole.DOCTOR, first_name="Milan")
    marko = make_user(role=UserRole.DOCTOR, first_name="Marko")

    summary = _events(_post(client, admin_token, _dental_card([VISIT_ROW])))[-1]["summary"]

    assert summary["visits_incomplete"] == 1
    assert any("Could not identify the doctor" in e for e in summary["errors"])

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] in {milan.id, marko.id}
    assert visits[0]["import_incomplete"] is True


def test_a_matched_initial_is_not_flagged(client, admin_token, doctor):
    """The 'M' in VISIT_ROW resolves to Milan, so nothing is guessed."""
    summary = _events(_post(client, admin_token, _dental_card([VISIT_ROW])))[-1]["summary"]

    assert summary["visits_created"] == 1
    assert summary["visits_incomplete"] == 0
    assert summary["errors"] == []

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] == doctor.id
    assert visits[0]["import_incomplete"] is False


def test_a_row_with_no_initial_and_one_doctor_is_not_a_guess(client, admin_token, doctor):
    """With a single doctor there is no choice to get wrong, so no flag."""
    row = ["01.03.2024.", None, "Caries d.16", None, "Composite filling", None, "4.000,00 din"]
    summary = _events(_post(client, admin_token, _dental_card([row])))[-1]["summary"]

    assert summary["visits_created"] == 1
    assert summary["visits_incomplete"] == 0
    assert summary["errors"] == []

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] == doctor.id
    assert visits[0]["import_incomplete"] is False


def test_a_row_with_no_initial_and_several_doctors_is_flagged(client, admin_token, make_user):
    """Two candidates and nothing on the card to choose between them."""
    from app.models.user import UserRole

    milan = make_user(role=UserRole.DOCTOR, first_name="Milan")
    zoran = make_user(role=UserRole.DOCTOR, first_name="Zoran")

    row = ["01.03.2024.", None, "Caries d.16", None, "Composite filling", None, "4.000,00 din"]
    summary = _events(_post(client, admin_token, _dental_card([row])))[-1]["summary"]

    assert summary["visits_incomplete"] == 1
    assert any("Could not identify the doctor" in e for e in summary["errors"])

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] in {milan.id, zoran.id}
    assert visits[0]["import_incomplete"] is True


def test_an_explicit_doctor_id_is_never_a_guess(client, admin_token, make_user):
    """The caller stated who it was, so the row is taken at its word."""
    from app.models.user import UserRole

    # 'M' would resolve to Milan on its own; the override must win *and* not flag.
    make_user(role=UserRole.DOCTOR, first_name="Milan")
    zoran = make_user(role=UserRole.DOCTOR, first_name="Zoran")

    resp = _post(client, admin_token, _dental_card([VISIT_ROW]), doctor_id=zoran.id)
    summary = _events(resp)[-1]["summary"]

    assert summary["visits_incomplete"] == 0
    assert summary["errors"] == []

    visits = client.get("/api/visits", headers=auth(admin_token)).json()
    assert visits[0]["doctor_id"] == zoran.id
    assert visits[0]["import_incomplete"] is False


def test_import_with_no_doctors_in_the_system_is_rejected_before_streaming(client, admin_token):
    """No `doctor` fixture here: there is nobody to assign visits to.

    This used to stream a 200, create the patient, and drop every visit row with
    an error buried in the summary. On preprod that imported ~2500 patients with
    no visit history at all before anyone noticed, so the run is now refused
    outright — and the patient must not land either.
    """
    resp = _post(client, admin_token, _dental_card([VISIT_ROW]))

    assert resp.status_code == 400
    assert "No doctors in the system" in resp.json()["detail"]
    assert client.get("/api/patients", headers=auth(admin_token)).json() == []


def test_an_explicit_doctor_id_still_imports_when_it_is_the_only_doctor(
    client, admin_token, make_user
):
    """The guard defers to an override: that id is what visits get attributed to."""
    from app.models.user import UserRole

    only = make_user(role=UserRole.DOCTOR, first_name="Filip")
    resp = _post(client, admin_token, _dental_card([VISIT_ROW]), doctor_id=only.id)

    assert resp.status_code == 200
    assert _events(resp)[-1]["summary"]["visits_created"] == 1


def test_rows_with_no_resolvable_doctor_collapse_to_one_error_per_file(client):
    """The skipped-row error is counted per file, not appended per row.

    Unreachable through the endpoint now that the guard rejects an empty index,
    so this drives `_import_workbook` directly. It fired once per visit row
    before, which turned a 200-file batch into thousands of identical lines
    crossing the SSE stream and being concatenated across batches by the client.
    """
    from app.database import SessionLocal
    from app.routers.import_xlsx import DoctorIndex, _empty_counts, _import_workbook

    three_rows = [
        VISIT_ROW,
        ["02.03.2024.", None, "Caries d.17", None, "Extraction", "M", "5.000,00 din"],
        ["03.03.2024.", None, "Caries d.18", None, "Cleaning", "M", "6.000,00 din"],
    ]

    errors: list[str] = []
    db = SessionLocal()
    try:
        _import_workbook(
            db,
            "card.xlsx",
            _dental_card(three_rows),
            DoctorIndex([], {}),
            None,
            _empty_counts(),
            errors,
        )
    finally:
        db.rollback()
        db.close()

    assert errors == ["card.xlsx: No doctors in system, skipped 3 visit row(s)"]


def test_a_second_import_is_refused_while_one_is_running(client, admin_token, doctor):
    """One import at a time: every file in a request stays in memory for the run.

    The status is 429 and must stay 429. The frontend retries a batch on status
    0, 5xx, 408 and 429 only (`isRetryableBatchError`), and records the batch's
    files as permanently failed on any other 4xx. Busy is transient — and
    reachable from its own Cancel/Resume, which can land while the cancelled run
    is still unwinding — so a non-retryable status here would turn a race into a
    dead run.
    """
    from app.routers.import_xlsx import _IMPORT_SLOT

    held = _IMPORT_SLOT.acquire()
    assert held is not None
    try:
        resp = _post(client, admin_token, _dental_card([VISIT_ROW]))
        assert resp.status_code == 429
        assert "already running" in resp.json()["detail"]
    finally:
        _IMPORT_SLOT.release(held)


def test_the_response_carries_a_background_slot_release(client, admin_token, doctor):
    """A client disconnect is only covered by the response's `BackgroundTask`.

    Asserted structurally, on purpose. A mid-stream disconnect cannot be
    reproduced through `TestClient`: it drives the app in-process and finalises
    the generator promptly, so closing its stream early releases the slot even
    with the background task removed — a behavioural test here passes either way
    and would be worse than none.

    The real behaviour was measured against a live uvicorn with a client that
    hard-closes the socket. Before this task existed, a cancelled run held the
    slot for ~80 seconds: nothing closes a suspended generator promptly, so its
    `finally` waited on the garbage collector. The frontend retries a batch three
    times over about three seconds, so Cancel then Resume failed every time.
    """
    import asyncio
    from io import BytesIO

    from fastapi import UploadFile

    from app.routers.import_xlsx import _IMPORT_SLOT, import_xlsx_files

    upload = UploadFile(file=BytesIO(_dental_card([VISIT_ROW])), filename="bg.xlsx")
    resp = asyncio.run(import_xlsx_files(files=[upload], doctor_id=None, _=None))
    try:
        assert resp.background is not None, "no BackgroundTask: a cancel would strand the slot"
        assert resp.background.func == _IMPORT_SLOT.release
    finally:
        # The call above claimed the slot and the generator is never iterated,
        # so nothing else would ever give it back.
        resp.background.func(*resp.background.args)


def test_the_slot_is_free_again_after_an_import_finishes(client, admin_token, doctor):
    """A leaked slot would wedge the endpoint until the container restarted."""
    assert _post(client, admin_token, _dental_card([VISIT_ROW])).status_code == 200

    from app.routers.import_xlsx import _IMPORT_SLOT

    token = _IMPORT_SLOT.acquire()
    assert token is not None
    _IMPORT_SLOT.release(token)


def test_a_rejected_request_does_not_consume_the_slot(client, admin_token, doctor):
    """The slot is claimed after validation, so a 400 leaves it free."""
    bad = _post(
        client,
        admin_token,
        _dental_card([VISIT_ROW]),
        doctor_id="00000000-0000-0000-0000-000000000000",
    )
    assert bad.status_code == 400

    assert _post(client, admin_token, _dental_card([VISIT_ROW])).status_code == 200


def test_a_stale_slot_is_taken_over_and_the_old_holder_cannot_free_it():
    """Staleness covers a generator that never ran its finally; fencing keeps
    the displaced holder from releasing its successor's claim."""
    from app.routers import import_xlsx

    slot = import_xlsx._ImportSlot()

    abandoned = slot.acquire()
    assert slot.acquire() is None  # still live, so no takeover

    slot._last_activity -= import_xlsx.IMPORT_STALE_AFTER_SECONDS + 1
    successor = slot.acquire()
    assert successor is not None and successor != abandoned

    # The abandoned run finally unwinds and releases — its token is stale, so
    # the slot must stay held by the successor.
    slot.release(abandoned)
    assert slot.acquire() is None

    slot.release(successor)
    assert slot.acquire() is not None


def test_an_unknown_doctor_id_is_rejected_before_streaming(client, admin_token):
    resp = _post(
        client,
        admin_token,
        _dental_card([VISIT_ROW]),
        doctor_id="00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]
