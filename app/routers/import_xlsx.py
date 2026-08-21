import json
import logging
import random
import re
from collections.abc import Awaitable, Callable, Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import NamedTuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dependencies import require_permission
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.models.visit import Visit
from app.permissions import Permission

logger = logging.getLogger(__name__)

# Starlette's multipart parser defaults to max_files=1000 (starlette/requests.py
# `_get_form`), and FastAPI calls `await request.form()` with no arguments, so a
# 1001-file import is rejected with a plain JSON 400 *before* this module runs —
# no log line, and no `text/event-stream` for the frontend's SSE reader to
# parse, which makes it look like a silent hang rather than an error.
#
# This is a safety net, not the intended path: the frontend batches uploads (see
# MAX_FILES_PER_REQUEST in the docstring below). It stays finite because every
# file in a request is held in memory twice — once in Starlette's spooled form,
# once in `file_data` below. Caddy's `request_body max_size 100MB` is the real
# ceiling; this only stops a pathological file *count* from getting that far.
MAX_IMPORT_FILES = 5000


class _RaisedFileLimitRoute(APIRoute):
    """Parse multipart bodies with `MAX_IMPORT_FILES` instead of Starlette's 1000.

    `Request._get_form` memoises into `self._form` and re-parses only when it is
    None, so parsing here first means FastAPI's own `await request.form()` is a
    cache hit and inherits these limits. Nothing else about the request changes.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            content_type = request.headers.get("content-type", "")
            if content_type.startswith("multipart/form-data"):
                # Still raises HTTPException(400) past the limit — same failure
                # shape as before, just a much higher threshold.
                await request.form(max_files=MAX_IMPORT_FILES)
            return await original_route_handler(request)

        return custom_route_handler


router = APIRouter(prefix="/api/import", tags=["import"], route_class=_RaisedFileLimitRoute)

TOOTH_REGEX = re.compile(r"d\.?\s?(\d+)", re.IGNORECASE)

# Layout of a dental card: patient details sit in column C (index 2) of rows
# 3-11, and the visit table starts at row 15.
PATIENT_COLUMN = 2
FIRST_VISIT_ROW = 14
MIN_ROWS = 14


def parse_date(value) -> date | None:
    """Parse 'dd.mm.yyyy.' format to date object."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip(".")
    try:
        return datetime.strptime(cleaned, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_gender(value) -> Gender | None:
    """Map m/M -> MALE, z/Z -> FEMALE."""
    if not value:
        return None
    v = str(value).strip().lower()
    logger.debug("parse_gender: raw=%r, normalized=%r", value, v)
    if v == "m":
        return Gender.MALE
    if v in ("z", "ž"):
        return Gender.FEMALE
    return None


def extract_tooth_number(diagnosis_text: str) -> int | None:
    """Extract tooth number from diagnosis text using regex."""
    if not diagnosis_text:
        return None
    match = TOOTH_REGEX.search(diagnosis_text)
    return int(match.group(1)) if match else None


def parse_price(row: list, price_idx: int = 6, fallback_idx: int = 7) -> Decimal | None:
    """Extract price from row, with fallback column.

    Handles formats like: 4000, 4000.00, 4,000.00 Din., 4.000,00 din
    """
    for idx in [price_idx, fallback_idx]:
        if idx < len(row) and row[idx] is not None:
            raw = str(row[idx]).strip()
            # Remove currency suffix (e.g. "Din.", "din", "RSD")
            raw = re.sub(r"[A-Za-z.]+$", "", raw).strip()
            if not raw:
                continue
            # Determine format by looking at last separator
            # "4.000,00" -> European (dot=thousands, comma=decimal)
            # "4,000.00" -> US (comma=thousands, dot=decimal)
            # "4000,00"  -> European no thousands sep
            # "4000.00"  -> US no thousands sep
            last_dot = raw.rfind(".")
            last_comma = raw.rfind(",")
            if last_comma > last_dot:
                # European: dots are thousands, comma is decimal
                raw = raw.replace(".", "").replace(",", ".")
            elif last_dot > last_comma:
                # US: commas are thousands, dot is decimal
                raw = raw.replace(",", "")
            else:
                # No separators or only one type — try as-is
                raw = raw.replace(",", ".")
            try:
                return Decimal(raw)
            except (InvalidOperation, ValueError):
                continue
    return None


def cell_str(value) -> str | None:
    """Safely convert cell value to stripped string or None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _empty_counts() -> dict:
    """The per-file counters, also used as the base of the run summary."""
    return {
        "patients_created": 0,
        "patients_found": 0,
        "visits_created": 0,
        "visits_skipped": 0,
        "patients_incomplete": 0,
        "visits_incomplete": 0,
    }


class DoctorIndex(NamedTuple):
    ids: list[str]
    by_initial: dict[str, str]


def _load_doctor_index() -> DoctorIndex:
    """Map each *unambiguous* first-name initial to a doctor id.

    An initial shared by two doctors is dropped rather than guessed at.
    """
    db = SessionLocal()
    try:
        doctors = db.query(User).filter(User.role == UserRole.DOCTOR).all()
        by_initial: dict[str, str] = {}
        ambiguous: set[str] = set()
        for doc in doctors:
            initial = (doc.first_name or "")[:1].upper()
            if not initial or initial in ambiguous:
                continue
            if initial in by_initial:
                del by_initial[initial]
                ambiguous.add(initial)
            else:
                by_initial[initial] = doc.id
        logger.info(
            "Import: found %d doctors, %d unique initials",
            len(doctors),
            len(by_initial),
        )
        return DoctorIndex([doc.id for doc in doctors], by_initial)
    finally:
        db.close()


class ResolvedDoctor(NamedTuple):
    id: str | None
    # Whether `id` identifies the doctor who actually did the work, or is only
    # a stand-in that satisfies `visits.doctor_id`'s NOT NULL. A guessed id is
    # fabricated clinical attribution, so the visit carrying it is flagged
    # `import_incomplete` and reported — it must not read as fact.
    guessed: bool


def _resolve_doctor(
    override_doctor_id: str | None,
    doctor_initial: str | None,
    doctors: DoctorIndex,
) -> ResolvedDoctor:
    """A caller-supplied doctor wins, then an initial match, then any doctor."""
    if override_doctor_id:
        return ResolvedDoctor(override_doctor_id, guessed=False)

    # Nobody to attribute to. `_require_any_doctor` rejects the run before it
    # starts, so this is only reachable if every doctor is deleted mid-run.
    if not doctors.ids:
        return ResolvedDoctor(None, guessed=False)

    if doctor_initial:
        matched = doctors.by_initial.get(doctor_initial.upper())
        if matched:
            return ResolvedDoctor(matched, guessed=False)
        # The card names somebody the index cannot identify: either no doctor
        # has that initial, or two share it and `_load_doctor_index` dropped it
        # rather than guess. Picking anyone here contradicts what the card says.
        return ResolvedDoctor(random.choice(doctors.ids), guessed=True)

    # The row names nobody. A single doctor in the system is the only possible
    # answer rather than a choice between candidates, so it is not a guess.
    if len(doctors.ids) == 1:
        return ResolvedDoctor(doctors.ids[0], guessed=False)
    return ResolvedDoctor(random.choice(doctors.ids), guessed=True)


class PatientHeader(NamedTuple):
    fields: dict
    incomplete: bool


def _parse_patient_header(rows: list, filename: str, errors: list[str]) -> PatientHeader | None:
    """Read the patient block. Returns None when the name is unusable.

    Unreadable gender and date-of-birth are not fatal: the card is imported
    with a documented default and flagged `import_incomplete` so somebody can
    fix it in the UI later.
    """

    def cell(row_idx: int):
        row = rows[row_idx]
        return row[PATIENT_COLUMN] if len(row) > PATIENT_COLUMN else None

    first_name = cell_str(cell(4))
    last_name = cell_str(cell(3))
    if not first_name or not last_name:
        errors.append(f"{filename}: Missing patient name")
        return None

    incomplete = False

    gender_raw = cell_str(cell(2))
    gender = parse_gender(gender_raw)
    if not gender:
        incomplete = True
        errors.append(f"{filename}: Invalid gender '{gender_raw}', defaulting to male")
        gender = Gender.MALE

    # Excel hands back a datetime for real date cells and a string otherwise.
    dob_raw = cell(6)
    if isinstance(dob_raw, datetime):
        date_of_birth = dob_raw.date()
    elif isinstance(dob_raw, date):
        date_of_birth = dob_raw
    else:
        date_of_birth = parse_date(str(dob_raw) if dob_raw else None)

    if not date_of_birth:
        incomplete = True
        errors.append(f"{filename}: Invalid DOB '{dob_raw}', using 1900-01-01")
        date_of_birth = date(1900, 1, 1)

    return PatientHeader(
        fields={
            "first_name": first_name,
            "last_name": last_name,
            "parent_name": cell_str(cell(5)),
            "gender": gender,
            "date_of_birth": date_of_birth,
            "address": cell_str(cell(7)),
            "city": cell_str(cell(8)),
            "phone": cell_str(cell(9)),
            "email": cell_str(cell(10)),
        },
        incomplete=incomplete,
    )


class VisitRow(NamedTuple):
    row_number: int
    visit_date: date
    diagnosis_notes: str | None
    treatment_notes: str | None
    doctor_initial: str | None
    tooth_number: int | None
    price: Decimal | None


def _iter_visit_rows(rows: list) -> Iterator[VisitRow]:
    """Yield the meaningful visit rows, carrying the last seen date forward.

    These cards are filled in by hand: a blank date column means "same day as
    the row above". Rows before the first date, and rows with neither a
    diagnosis nor a treatment, are skipped silently.
    """
    current_date: date | None = None

    for row_idx in range(FIRST_VISIT_ROW, len(rows)):
        row = rows[row_idx]
        if not row or len(row) < 1:
            continue

        raw_date = row[0]
        parsed_date = None
        if isinstance(raw_date, datetime):
            parsed_date = raw_date.date()
        elif isinstance(raw_date, date):
            parsed_date = raw_date
        elif isinstance(raw_date, str) and raw_date.strip():
            parsed_date = parse_date(raw_date)

        if parsed_date:
            current_date = parsed_date
        if not current_date:
            continue

        diagnosis_notes = cell_str(row[2]) if len(row) > 2 else None
        treatment_notes = cell_str(row[4]) if len(row) > 4 else None
        if not diagnosis_notes and not treatment_notes:
            continue

        yield VisitRow(
            row_number=row_idx + 1,
            visit_date=current_date,
            diagnosis_notes=diagnosis_notes,
            treatment_notes=treatment_notes,
            doctor_initial=cell_str(row[5]) if len(row) > 5 else None,
            tooth_number=extract_tooth_number(diagnosis_notes),
            price=parse_price(row),
        )


def _import_workbook(
    db: Session,
    filename: str,
    content: bytes,
    doctors: DoctorIndex,
    override_doctor_id: str | None,
    counts: dict,
    errors: list[str],
) -> None:
    """Import one card into `db`, updating `counts` and `errors` in place.

    Does not commit — the caller owns the transaction so that a file either
    lands whole or not at all.
    """
    wb = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
    try:
        rows = [list(row) for row in wb.active.iter_rows(values_only=True)]
    finally:
        wb.close()

    if len(rows) < MIN_ROWS:
        errors.append(f"{filename}: File too short, expected at least {MIN_ROWS} rows")
        return

    header = _parse_patient_header(rows, filename, errors)
    if header is None:
        return

    patient = (
        db.query(Patient)
        .filter(
            Patient.first_name.ilike(header.fields["first_name"]),
            Patient.last_name.ilike(header.fields["last_name"]),
            Patient.date_of_birth == header.fields["date_of_birth"],
        )
        .first()
    )

    if patient:
        counts["patients_found"] += 1
    else:
        patient = Patient(**header.fields, import_incomplete=header.incomplete)
        db.add(patient)
        db.flush()  # need patient.id before inserting visits
        counts["patients_created"] += 1
        if header.incomplete:
            counts["patients_incomplete"] += 1

    # Every visit row used to run its own duplicate-check SELECT. That is one
    # network round trip per row against a remote pooler, so a card with fifty
    # visits paid fifty latencies before inserting anything — the cost an index
    # cannot remove. One query per file loads the same information.
    #
    # A patient created moments ago has no visits, so skip even that query.
    #
    # Only columns are selected, not entities: this comparison set must not put
    # the patient's whole visit history into the session's identity map, which
    # would then be flushed and dirty-checked on commit.
    existing_visits: set[tuple] = set()
    if counts["patients_found"]:
        existing_visits = {
            row
            for row in db.query(Visit.date, Visit.diagnosis_notes, Visit.treatment_notes).filter(
                Visit.patient_id == patient.id
            )
        }

    # Counted, not appended per row. `_require_any_doctor` makes this branch
    # unreachable except in a race — every doctor deleted after the run started
    # — but when it did fire it produced one error string per visit row per
    # file. A 200-file batch turned into thousands of near-identical lines, all
    # of which cross the SSE stream and are concatenated across batches by the
    # frontend. One line per file says the same thing.
    rows_without_doctor = 0
    rows_with_guessed_doctor = 0

    for visit_row in _iter_visit_rows(rows):
        resolved = _resolve_doctor(override_doctor_id, visit_row.doctor_initial, doctors)
        if not resolved.id:
            rows_without_doctor += 1
            continue

        # Deliberately not adding inserted rows to this set. The session sets
        # autoflush=False, so the old per-row query could not see visits added
        # earlier in this same file either, and a card that repeats a row still
        # imports it twice. Preserved as-is: changing it would silently move
        # numbers in the summary, and it is a separate decision from this one.
        if (
            visit_row.visit_date,
            visit_row.diagnosis_notes,
            visit_row.treatment_notes,
        ) in existing_visits:
            counts["visits_skipped"] += 1
            continue

        # One flag, two causes: a missing price and an unidentified doctor both
        # mean "a human needs to look at this row". `import_incomplete` is
        # already what the UI's warning and PATCH .../dismiss-warning act on, so
        # a guessed doctor rides the same path rather than inventing a second.
        incomplete = visit_row.price is None or resolved.guessed

        db.add(
            Visit(
                patient_id=patient.id,
                doctor_id=resolved.id,
                date=visit_row.visit_date,
                tooth_number=visit_row.tooth_number,
                diagnosis_notes=visit_row.diagnosis_notes,
                treatment_notes=visit_row.treatment_notes,
                price=visit_row.price,
                paid=True,
                import_incomplete=incomplete,
            )
        )
        counts["visits_created"] += 1
        if incomplete:
            counts["visits_incomplete"] += 1
        if resolved.guessed:
            rows_with_guessed_doctor += 1

    if rows_without_doctor:
        errors.append(
            f"{filename}: No doctors in system, skipped {rows_without_doctor} visit row(s)"
        )
    if rows_with_guessed_doctor:
        errors.append(
            f"{filename}: Could not identify the doctor for {rows_with_guessed_doctor} "
            "visit row(s); assigned an arbitrary one and flagged them for review"
        )


def _validate_override_doctor(doctor_id: str | None) -> str | None:
    """Check a caller-supplied doctor_id before the response starts streaming.

    Once the StreamingResponse begins, the status code is already sent — so a
    bad id has to be rejected here to surface as a real HTTP 400.
    """
    if not doctor_id:
        return None
    db = SessionLocal()
    try:
        doctor = db.query(User).filter(User.id == doctor_id, User.role == UserRole.DOCTOR).first()
        if not doctor:
            raise HTTPException(
                status_code=400,
                detail=f"Doctor with id {doctor_id} not found",
            )
        return doctor.id
    finally:
        db.close()


def _require_any_doctor() -> None:
    """Refuse the whole run when no doctor exists to attribute visits to.

    `visits.doctor_id` is NOT NULL, so with an empty `DoctorIndex` every visit
    row hits the `no doctor` branch in `_import_workbook` and is dropped — while
    the patient header around it commits normally. That failure is invisible at
    a glance: the import reports success, patient counts climb, and the visit
    history is silently discarded card after card. It happened on preprod for
    ~2500 files before anybody noticed, because the database was seeded with the
    default admin only and `app/seeds.py` never creates a doctor.

    Rejecting here, before the stream opens, is what makes it an error the user
    reads instead of an empty `visits_created`. Only reachable when no
    `doctor_id` override was supplied — that override is checked above and stands
    in for the index entirely.
    """
    db = SessionLocal()
    try:
        if db.query(User.id).filter(User.role == UserRole.DOCTOR).first() is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No doctors in the system. Create a user with the DOCTOR role, "
                    "or pass doctor_id, before importing."
                ),
            )
    finally:
        db.close()


@router.post("/xlsx")
async def import_xlsx_files(
    files: list[UploadFile] = File(...),
    doctor_id: str | None = Form(None),
    # Named `_` like every other router: the value is never read, but the
    # dependency is what makes this endpoint admin-only. Deleting it because a
    # linter calls the argument unused would open patient-data import to every
    # role. Covered by tests/test_permissions.py.
    _: User = Depends(require_permission(Permission.ADMIN_IMPORT)),
):
    """Import one or more XLSX dental card files, streaming progress via SSE.

    Each file creates/updates a patient and imports their visit history.
    Requires admin role.

    If `doctor_id` is provided, that doctor is assigned to every imported visit,
    overriding per-row initial matching and the random fallback. If omitted, the
    original behaviour applies (match by first-name initial, fall back to random)
    and the system must contain at least one DOCTOR user — otherwise the request
    is rejected with a 400 rather than importing patients whose visits would all
    be dropped for want of anyone to attribute them to. A visit that falls back
    to an arbitrary doctor is flagged `import_incomplete` and counted in the
    summary's errors, so a fabricated attribution never reads as fact.

    Streams three event types:
    - progress: emitted before each file starts processing
    - file_done: emitted after each file completes (success or per-file error)
    - complete: emitted once after all files are processed, with the full summary

    Callers should send **at most 200 files per request** and repeat the call
    per batch (the frontend's MAX_FILES_PER_REQUEST). A request is all-or-nothing
    at the transport level: every file is buffered in memory for the whole run,
    and a dropped connection loses the progress stream for everything still
    queued behind it. Batching bounds both, and re-sending a batch is safe —
    patients are matched on name plus date of birth and visits on their content,
    so an already-imported file lands as `visits_skipped`, not as duplicates.
    `MAX_IMPORT_FILES` above is the hard backstop, not the recommended size.
    """
    override_doctor_id = _validate_override_doctor(doctor_id)
    if not override_doctor_id:
        _require_any_doctor()

    # Read all file contents eagerly before returning StreamingResponse.
    # UploadFile handles are closed by FastAPI once the endpoint returns,
    # so they cannot be awaited inside the generator.
    file_data: list[tuple[str, bytes]] = []
    for upload_file in files:
        content = await upload_file.read()
        file_data.append((upload_file.filename or "unknown", content))

    def generate():
        summary = {**_empty_counts(), "files_processed": 0, "errors": []}

        try:
            total = len(file_data)
            doctors = _load_doctor_index()

            for i, (filename, content) in enumerate(file_data):
                yield _sse(
                    {
                        "type": "progress",
                        "current": i + 1,
                        "total": total,
                        "file": filename,
                        "status": "processing",
                    }
                )

                file_errors: list[str] = []
                file_counts = _empty_counts()
                committed = False

                # One session and one transaction per file, so a bad file
                # cannot roll back the ones already imported.
                db = SessionLocal()
                try:
                    _import_workbook(
                        db,
                        filename,
                        content,
                        doctors,
                        override_doctor_id,
                        file_counts,
                        file_errors,
                    )
                    db.commit()
                    committed = True
                except Exception as e:
                    db.rollback()
                    file_errors.append(f"{filename}: {str(e)}")
                    file_counts = _empty_counts()  # nothing was persisted
                finally:
                    db.close()

                if committed:
                    for key, value in file_counts.items():
                        summary[key] += value
                summary["errors"].extend(file_errors)
                summary["files_processed"] += 1

                yield _sse(
                    {
                        "type": "file_done",
                        "current": i + 1,
                        "total": total,
                        "file": filename,
                        **file_counts,
                        "errors": file_errors,
                    }
                )

            yield _sse({"type": "complete", "summary": summary})

        except Exception as e:
            summary["errors"].append(f"Fatal error: {str(e)}")
            yield _sse({"type": "complete", "summary": summary})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
