import json
import logging
import random
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Iterator, List, NamedTuple, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dependencies import require_permission
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.models.visit import Visit
from app.permissions import Permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["import"])

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


def _resolve_doctor(
    override_doctor_id: Optional[str],
    doctor_initial: Optional[str],
    doctors: DoctorIndex,
) -> Optional[str]:
    """A caller-supplied doctor wins, then an initial match, then any doctor."""
    if override_doctor_id:
        return override_doctor_id
    if doctor_initial:
        matched = doctors.by_initial.get(doctor_initial.upper())
        if matched:
            return matched
    return random.choice(doctors.ids) if doctors.ids else None


class PatientHeader(NamedTuple):
    fields: dict
    incomplete: bool


def _parse_patient_header(rows: list, filename: str, errors: list[str]) -> Optional[PatientHeader]:
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
    diagnosis_notes: Optional[str]
    treatment_notes: Optional[str]
    doctor_initial: Optional[str]
    tooth_number: Optional[int]
    price: Optional[Decimal]


def _iter_visit_rows(rows: list) -> Iterator[VisitRow]:
    """Yield the meaningful visit rows, carrying the last seen date forward.

    These cards are filled in by hand: a blank date column means "same day as
    the row above". Rows before the first date, and rows with neither a
    diagnosis nor a treatment, are skipped silently.
    """
    current_date: Optional[date] = None

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
    override_doctor_id: Optional[str],
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

    for visit_row in _iter_visit_rows(rows):
        doctor_id = _resolve_doctor(override_doctor_id, visit_row.doctor_initial, doctors)
        if not doctor_id:
            errors.append(f"{filename} row {visit_row.row_number}: No doctors in system, skipping")
            continue

        already_imported = (
            db.query(Visit)
            .filter(
                Visit.patient_id == patient.id,
                Visit.date == visit_row.visit_date,
                Visit.diagnosis_notes == visit_row.diagnosis_notes,
                Visit.treatment_notes == visit_row.treatment_notes,
            )
            .first()
        )
        if already_imported:
            counts["visits_skipped"] += 1
            continue

        db.add(
            Visit(
                patient_id=patient.id,
                doctor_id=doctor_id,
                date=visit_row.visit_date,
                tooth_number=visit_row.tooth_number,
                diagnosis_notes=visit_row.diagnosis_notes,
                treatment_notes=visit_row.treatment_notes,
                price=visit_row.price,
                paid=True,
                import_incomplete=visit_row.price is None,
            )
        )
        counts["visits_created"] += 1
        if visit_row.price is None:
            counts["visits_incomplete"] += 1


def _validate_override_doctor(doctor_id: Optional[str]) -> Optional[str]:
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


@router.post("/xlsx")
async def import_xlsx_files(
    files: List[UploadFile] = File(...),
    doctor_id: Optional[str] = Form(None),
    current_user: User = Depends(require_permission(Permission.ADMIN_IMPORT)),
):
    """Import one or more XLSX dental card files, streaming progress via SSE.

    Each file creates/updates a patient and imports their visit history.
    Requires admin role.

    If `doctor_id` is provided, that doctor is assigned to every imported visit,
    overriding per-row initial matching and the random fallback. If omitted, the
    original behaviour applies (match by first-name initial, fall back to random).

    Streams three event types:
    - progress: emitted before each file starts processing
    - file_done: emitted after each file completes (success or per-file error)
    - complete: emitted once after all files are processed, with the full summary
    """
    override_doctor_id = _validate_override_doctor(doctor_id)

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
