import re
import json
import logging
from io import BytesIO
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, List

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook

from app.database import SessionLocal
from app.dependencies import require_admin
from app.models.user import User
from app.models.patient import Patient, Gender
from app.models.doctor import Doctor
from app.models.visit import Visit

router = APIRouter(prefix="/api/import", tags=["import"])

TOOTH_REGEX = re.compile(r'd\.?\s?(\d+)', re.IGNORECASE)


def parse_date(value) -> date | None:
    """Parse 'dd.mm.yyyy.' format to date object."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip('.')
    try:
        return datetime.strptime(cleaned, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_gender(value) -> Gender | None:
    """Map m/M -> MALE, z/Z -> FEMALE."""
    if not value:
        return None
    v = str(value).strip().lower()
    logging.warning(f"parse_gender: raw={value!r}, normalized={v!r}")
    if v == 'm':
        return Gender.MALE
    if v in ('z', 'ž'):
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
            raw = re.sub(r'[A-Za-z.]+$', '', raw).strip()
            if not raw:
                continue
            # Determine format by looking at last separator
            # "4.000,00" -> European (dot=thousands, comma=decimal)
            # "4,000.00" -> US (comma=thousands, dot=decimal)
            # "4000,00"  -> European no thousands sep
            # "4000.00"  -> US no thousands sep
            last_dot = raw.rfind('.')
            last_comma = raw.rfind(',')
            if last_comma > last_dot:
                # European: dots are thousands, comma is decimal
                raw = raw.replace('.', '').replace(',', '.')
            elif last_dot > last_comma:
                # US: commas are thousands, dot is decimal
                raw = raw.replace(',', '')
            else:
                # No separators or only one type — try as-is
                raw = raw.replace(',', '.')
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


@router.post("/xlsx")
async def import_xlsx_files(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_admin),
):
    """Import one or more XLSX dental card files, streaming progress via SSE.

    Each file creates/updates a patient and imports their visit history.
    Requires admin role.

    Streams three event types:
    - progress: emitted before each file starts processing
    - file_done: emitted after each file completes (success or per-file error)
    - complete: emitted once after all files are processed, with the full summary
    """
    # Read all file contents eagerly before returning StreamingResponse.
    # UploadFile handles are closed by FastAPI once the endpoint returns,
    # so they cannot be awaited inside the generator.
    file_data: list[tuple[str, bytes]] = []
    for upload_file in files:
        content = await upload_file.read()
        file_data.append((upload_file.filename or "unknown", content))

    def generate():
        summary = {
            "patients_created": 0,
            "patients_found": 0,
            "visits_created": 0,
            "visits_skipped": 0,
            "files_processed": 0,
            "errors": [],
        }

        try:
            total = len(file_data)

            # Pre-load doctors for initial matching using a short-lived session
            db = SessionLocal()
            try:
                doctors = db.query(Doctor).all()
                doctor_map: dict[str, str] = {}  # initial letter -> doctor id
                for doc in doctors:
                    initial = doc.first_name[0].upper() if doc.first_name else ""
                    if initial and initial not in doctor_map:
                        doctor_map[initial] = doc.id
                default_doctor_id = doctors[0].id if doctors else None
            finally:
                db.close()

            for i, (filename, content) in enumerate(file_data):

                yield _sse({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "file": filename,
                    "status": "processing",
                })

                file_errors: list[str] = []
                file_result = {
                    "patients_created": 0,
                    "patients_found": 0,
                    "visits_created": 0,
                    "visits_skipped": 0,
                }
                committed = False

                db = SessionLocal()
                try:
                    wb = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
                    ws = wb.active

                    # Read all rows as lists of values
                    rows = []
                    for row in ws.iter_rows(values_only=True):
                        rows.append(list(row))
                    wb.close()

                    if len(rows) < 14:
                        file_errors.append(f"{filename}: File too short, expected at least 14 rows")
                    else:
                        # --- Parse patient header (rows 2-10, column C = index 2) ---
                        gender_raw = cell_str(rows[2][2]) if len(rows[2]) > 2 else None
                        last_name = cell_str(rows[3][2]) if len(rows[3]) > 2 else None
                        first_name = cell_str(rows[4][2]) if len(rows[4]) > 2 else None
                        parent_name = cell_str(rows[5][2]) if len(rows[5]) > 2 else None
                        dob_raw = rows[6][2] if len(rows[6]) > 2 else None
                        address = cell_str(rows[7][2]) if len(rows[7]) > 2 else None
                        city = cell_str(rows[8][2]) if len(rows[8]) > 2 else None
                        phone = cell_str(rows[9][2]) if len(rows[9]) > 2 else None
                        email = cell_str(rows[10][2]) if len(rows[10]) > 2 else None

                        if not first_name or not last_name:
                            file_errors.append(f"{filename}: Missing patient name")
                        else:
                            gender = parse_gender(gender_raw)
                            if not gender:
                                file_errors.append(
                                    f"{filename}: Invalid gender '{gender_raw}', defaulting to male"
                                )
                                gender = Gender.MALE

                            # Handle date_of_birth - could be string or datetime from Excel
                            date_of_birth = None
                            if isinstance(dob_raw, datetime):
                                date_of_birth = dob_raw.date()
                            elif isinstance(dob_raw, date):
                                date_of_birth = dob_raw
                            else:
                                date_of_birth = parse_date(str(dob_raw) if dob_raw else None)

                            if not date_of_birth:
                                file_errors.append(
                                    f"{filename}: Invalid DOB '{dob_raw}', using 1900-01-01"
                                )
                                date_of_birth = date(1900, 1, 1)

                            # --- Find or create patient ---
                            patient = db.query(Patient).filter(
                                Patient.first_name.ilike(first_name),
                                Patient.last_name.ilike(last_name),
                                Patient.date_of_birth == date_of_birth,
                            ).first()

                            if patient:
                                file_result["patients_found"] += 1
                            else:
                                patient = Patient(
                                    first_name=first_name,
                                    last_name=last_name,
                                    parent_name=parent_name,
                                    gender=gender,
                                    date_of_birth=date_of_birth,
                                    address=address,
                                    city=city,
                                    phone=phone,
                                    email=email,
                                )
                                db.add(patient)
                                db.flush()  # get patient.id before visit inserts
                                file_result["patients_created"] += 1

                            # --- Parse visit rows (row 14+) ---
                            visit_count = 0
                            skipped_count = 0
                            current_date = None  # tracks last valid date seen

                            for row_idx in range(14, len(rows)):
                                row = rows[row_idx]
                                if not row or len(row) < 1:
                                    continue

                                # Try to parse a date from this row
                                raw_date = row[0]
                                parsed_date = None
                                if isinstance(raw_date, datetime):
                                    parsed_date = raw_date.date()
                                elif isinstance(raw_date, date):
                                    parsed_date = raw_date
                                elif isinstance(raw_date, str) and raw_date.strip():
                                    parsed_date = parse_date(raw_date)

                                # Update current_date only when a new date is found
                                if parsed_date:
                                    current_date = parsed_date

                                # Skip row if we haven't encountered any date yet
                                if not current_date:
                                    continue

                                visit_date = current_date

                                diagnosis_notes = cell_str(row[2]) if len(row) > 2 else None
                                treatment_notes = cell_str(row[4]) if len(row) > 4 else None
                                doctor_initial = cell_str(row[5]) if len(row) > 5 else None
                                tooth_number = extract_tooth_number(diagnosis_notes)
                                price = parse_price(row)

                                # Skip rows with no meaningful content
                                if not diagnosis_notes and not treatment_notes:
                                    continue

                                # Resolve doctor
                                doctor_id = default_doctor_id
                                if doctor_initial:
                                    mapped = doctor_map.get(doctor_initial.upper())
                                    if mapped:
                                        doctor_id = mapped

                                if not doctor_id:
                                    file_errors.append(
                                        f"{filename} row {row_idx + 1}: No doctor found for initial '{doctor_initial}', skipping"
                                    )
                                    continue

                                exists = db.query(Visit).filter(
                                    Visit.patient_id == patient.id,
                                    Visit.date == visit_date,
                                    Visit.diagnosis_notes == diagnosis_notes,
                                    Visit.treatment_notes == treatment_notes,
                                ).first()

                                if exists:
                                    skipped_count += 1
                                    continue

                                visit = Visit(
                                    patient_id=patient.id,
                                    doctor_id=doctor_id,
                                    date=visit_date,
                                    tooth_number=tooth_number,
                                    diagnosis_notes=diagnosis_notes,
                                    treatment_notes=treatment_notes,
                                    price=price,
                                    paid=True,
                                )
                                db.add(visit)
                                visit_count += 1

                            file_result["visits_created"] = visit_count
                            file_result["visits_skipped"] = skipped_count

                    db.commit()
                    committed = True

                except Exception as e:
                    db.rollback()
                    file_errors.append(f"{filename}: {str(e)}")
                    # Reset counts — nothing was persisted for this file
                    file_result = {
                        "patients_created": 0,
                        "patients_found": 0,
                        "visits_created": 0,
                        "visits_skipped": 0,
                    }
                finally:
                    db.close()

                # Only accumulate counts from successfully committed files
                if committed:
                    for key in file_result:
                        summary[key] += file_result[key]
                summary["errors"].extend(file_errors)
                summary["files_processed"] += 1

                yield _sse({
                    "type": "file_done",
                    "current": i + 1,
                    "total": total,
                    "file": filename,
                    **file_result,
                    "errors": file_errors,
                })

            yield _sse({"type": "complete", "summary": summary})

        except Exception as e:
            summary["errors"].append(f"Fatal error: {str(e)}")
            yield _sse({"type": "complete", "summary": summary})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
