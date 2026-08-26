import json
import logging
import random
import re
import threading
import time
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
from starlette.background import BackgroundTask

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
# A backstop against a non-browser caller, NOT a supported request size. The
# frontend sends 50 files per request (MAX_FILES_PER_REQUEST, see the endpoint
# docstring), so the real client is two orders of magnitude below this and the
# number exists only so a scripted caller meets an honest error instead of the
# silent hang described above.
#
# Kept at 5000 rather than lowered to something nearer the real traffic, for two
# reasons. Caddy's `request_body max_size 100MB` already bounds the memory a
# request can cost regardless of how the files divide up, so this only guards
# against a pathological *count* of tiny files — where 5000 is cheap. And
# anything below Starlette's own 1000 would make `_RaisedFileLimitRoute` tighten
# the default rather than raise it, which is the opposite of what it exists for.
MAX_IMPORT_FILES = 5000

# How long the slot below may go untouched before another request may take it.
# Every file refreshes it, and a card takes well under a second, so a live
# import cannot look stale — this only ever fires on a holder that is gone.
IMPORT_STALE_AFTER_SECONDS = 300


class _ImportSlot:
    """Single-occupancy slot: one import runs at a time, per process.

    Every file in a request is held in memory for the whole run, so a second
    concurrent import multiplies the peak — against one uvicorn worker
    (`--workers 1`) and `pool_size=5` to a remote pooler, neither of which has
    headroom for it. `acquire` refuses rather than waits: a queued import would
    sit holding its entire request body in memory, which is the thing being
    rationed in the first place.

    In-process deliberately. It is exactly as wide as the process it protects,
    which is right at one worker, and it means a crash or a restart clears it
    instead of stranding a lock nobody owns. Adding workers would make this
    silently stop guarding anything; the replacement is a Postgres advisory
    lock, which has to be held on one dedicated connection for the whole run
    rather than the per-file sessions used here.

    Released three ways, in descending order of promptness:

    1. The response's `BackgroundTask`, which Starlette awaits once the response
       task group exits — on a client disconnect as much as on a completed body.
       This is the one that matters for the frontend's Cancel button.
    2. The generator's own `finally`, for exhaustion and errors.
    3. The staleness takeover below, for the case where the generator never runs
       at all: Starlette builds the response before it iterates the body, so a
       client that disappears in *that* window leaves a generator collected
       without its `finally` ever running.

    (1) was added after measuring: with only (2) and (3), a cancelled run held
    the slot for ~80 seconds — nothing closes a suspended generator promptly, so
    it waited on the garbage collector. The frontend retries a batch three times
    over about three seconds, so Cancel then Resume failed every time.

    Each acquisition gets a token, and `touch`/`release` are no-ops unless they
    present the current one. That fencing stops a holder declared stale and taken
    over from releasing the slot out from under its successor, and makes the
    double release from (1) and (2) harmless.
    """

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._held = False
        self._token = 0
        self._last_activity = 0.0

    def acquire(self) -> int | None:
        """Claim the slot, returning a token, or None if somebody live holds it."""
        with self._mutex:
            if self._held and time.monotonic() - self._last_activity < IMPORT_STALE_AFTER_SECONDS:
                return None
            if self._held:
                logger.warning(
                    "Import: taking over a slot idle for >%ds", IMPORT_STALE_AFTER_SECONDS
                )
            self._token += 1
            self._held = True
            self._last_activity = time.monotonic()
            return self._token

    def touch(self, token: int) -> None:
        with self._mutex:
            if token == self._token:
                self._last_activity = time.monotonic()

    def release(self, token: int) -> None:
        with self._mutex:
            if token == self._token:
                self._held = False


_IMPORT_SLOT = _ImportSlot()


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

# FDI notation: a quadrant digit (1-4 permanent, 5-8 deciduous) followed by the
# tooth's position within it (1-8 permanent, 1-5 deciduous). TOOTH_REGEX matches
# any run of digits after "d.", so without this "d. 2000" — a price that landed
# in the diagnosis column, or a year in a note — is stored as tooth 2000.
# Checked against the real cards before narrowing this: every tooth number in
# them falls inside the set, so nothing legitimate is turned away.
FDI_TEETH = frozenset(
    {
        *range(11, 19),
        *range(21, 29),
        *range(31, 39),
        *range(41, 49),
        *range(51, 56),
        *range(61, 66),
        *range(71, 76),
        *range(81, 86),
    }
)

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
    """Extract an FDI tooth number from diagnosis text, or None.

    Anything outside `FDI_TEETH` is discarded rather than stored: the digits
    after "d." are not necessarily a tooth. The diagnosis text itself is kept
    verbatim in `diagnosis_notes` either way, so nothing is lost by declining to
    interpret it.
    """
    if not diagnosis_text:
        return None
    match = TOOTH_REGEX.search(diagnosis_text)
    if not match:
        return None
    tooth = int(match.group(1))
    return tooth if tooth in FDI_TEETH else None


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
        "patients_updated": 0,
        "visits_created": 0,
        "visits_skipped": 0,
        "patients_incomplete": 0,
        "visits_incomplete": 0,
    }


def _format_counts(counts: dict) -> str:
    """The counters as one human-readable clause, shared by the per-file and run lines."""
    return (
        f"patients +{counts['patients_created']} "
        f"({counts['patients_found']} matched, {counts['patients_updated']} filled), "
        f"visits +{counts['visits_created']} ({counts['visits_skipped']} skipped)"
    )


class FileLogDetail(NamedTuple):
    """Per-file facts that belong in the journal but not in the SSE payload.

    `counts` is spread into the `file_done` event verbatim (`**file_counts`), so
    a counter added there joins the contract the Angular app parses and the
    characterization tests pin. A missing price is worth explaining in a log
    line and is not worth a frontend change, so it travels here instead.
    """

    visits_missing_price: int = 0


def _format_flagged(patients: int, visits: int, missing_price: int = 0) -> str:
    """Which records were flagged, split by kind.

    Summed, the number cannot distinguish one flagged patient from twelve
    flagged visits, which are different problems with different remedies.
    """
    parts = []
    if patients:
        parts.append(f"{patients} patient(s)")
    if visits:
        visits_part = f"{visits} visit(s)"
        # Every other cause of a flag appends an error string that the caller
        # prints alongside this clause. A missing price is the only one that
        # does not, so without naming it here a price-flagged file reports a
        # count and no reason at all.
        if missing_price:
            visits_part += f", {missing_price} of them for a missing price"
        parts.append(visits_part)
    return ", ".join(parts)


def _strip_filename(errors: list[str], filename: str) -> list[str]:
    """Drop the `{filename}: ` prefix every error string is built with.

    Without this the sanitising below achieves nothing: the line would omit the
    filename from its own prefix and then print it again inside the first error.
    Left intact on any string that does not carry the prefix, which today is
    none of them — every `errors.append` in this module uses it.
    """
    prefix = f"{filename}: "
    return [e[len(prefix) :] if e.startswith(prefix) else e for e in errors]


def _log_file_result(
    filename: str,
    index: int,
    total: int,
    committed: bool,
    counts: dict,
    errors: list[str],
    log_detail: FileLogDetail,
) -> None:
    """Write one durable line per file.

    These numbers are already computed for the `file_done` SSE event, but that
    event only ever reaches the browser tab that started the run and is gone
    when it closes. Nothing on the server recorded which file failed, or which
    one produced records that need review, so a migration could only be audited
    while somebody was watching it happen.

    Levels are chosen so `journalctl -p warning` is the review queue: anything
    needing a human — a failed file, a flagged record, a card that parsed but
    complained — is a warning, and a clean file is info.

    The filename is a patient's name, and since the container switched to the
    journald driver these lines outlive deploys by months — outside the
    database, outside the app's roles, and untouched by deleting the patient
    through the API. So it is written only where nothing else records it: a
    failed file rolled its transaction back and left no row anywhere, making
    this line the sole evidence it was ever read. A flagged file is the
    opposite — its records are in the database carrying `import_incomplete`, so
    they can be listed from there whenever somebody wants them, and the position
    is enough to say how far along the run it happened.
    """
    where = f"file {index}/{total}"

    if not committed:
        logger.warning(
            "Import: %s (%s) FAILED — %s", filename, where, "; ".join(errors) or "unknown error"
        )
        return

    flagged = _format_flagged(
        counts["patients_incomplete"],
        counts["visits_incomplete"],
        log_detail.visits_missing_price,
    )
    if not flagged and not errors:
        logger.info("Import: %s — %s", where, _format_counts(counts))
        return

    # Only the clauses that apply, so the line says what is actually wrong
    # rather than trailing a "0 flagged incomplete" behind a parse complaint.
    detail = _format_counts(counts)
    if flagged:
        detail += f", flagged incomplete: {flagged}"
    if errors:
        detail += f"; {'; '.join(_strip_filename(errors, filename))}"
    logger.warning("Import: %s — %s", where, detail)


class DoctorIndex(NamedTuple):
    ids: list[str]
    by_initial: dict[str, str]
    # Why an initial is *not* in `by_initial`, kept rather than discarded. These
    # are the only explanation for a run that flags every visit it imports, and
    # reconstructing them afterwards means querying the user table by hand — so
    # `_log_doctor_index_health` writes them down while the run still has them.
    #
    # Required rather than defaulted: a NamedTuple's defaults are one shared
    # object per field, so an empty default here would be the same dict handed
    # to every index that omitted it.
    ambiguous: dict[str, list[str]]
    no_initial: list[str]


def _doctor_label(doc: User) -> str:
    """A doctor as a log line should name them; the id only if they have no name."""
    return f"{doc.first_name or ''} {doc.last_name or ''}".strip() or doc.id


def _load_doctor_index() -> DoctorIndex:
    """Map each *unambiguous* first-name initial to a doctor id.

    An initial shared by two doctors is dropped rather than guessed at, and a
    doctor with no first name contributes no initial at all. Both cases leave a
    doctor who is still eligible for attribution — they stay in `ids`, which is
    what `_resolve_doctor` falls back to — but who can never be *matched*, so
    they are recorded for the health line rather than dropped on the floor.
    """
    db = SessionLocal()
    try:
        doctors = db.query(User).filter(User.role == UserRole.DOCTOR).all()

        # Grouping first, then deciding, says the rule in one place: an initial
        # belongs to exactly one doctor or to nobody.
        grouped: dict[str, list[User]] = {}
        no_initial: list[str] = []
        for doc in doctors:
            initial = (doc.first_name or "")[:1].upper()
            if not initial:
                no_initial.append(_doctor_label(doc))
                continue
            grouped.setdefault(initial, []).append(doc)

        by_initial = {i: docs[0].id for i, docs in grouped.items() if len(docs) == 1}
        ambiguous = {
            i: [_doctor_label(d) for d in docs] for i, docs in grouped.items() if len(docs) > 1
        }
        return DoctorIndex([doc.id for doc in doctors], by_initial, ambiguous, no_initial)
    finally:
        db.close()


def _log_doctor_index_health(doctors: DoctorIndex, override_doctor_id: str | None) -> None:
    """Say once per run whether attribution can work, at a level that shows.

    `_import_workbook` already reports a card whose doctor could not be
    identified, so a run against a collided index writes that symptom once per
    *file* — around 8000 times during the migration this was written for, one
    per card, every line saying the same thing. The cause is this single line,
    and it used to be `info`: the quietest thing in the journal, sitting
    underneath its own consequences, while the only actionable fact in the run
    was which initials collapsed and who collapsed them.

    So the level follows the index's health rather than being fixed. A run that
    cannot identify anybody is precisely the case somebody has to see, and it
    names the collisions, because the fix is never in this code — two doctors
    really do share an initial and the card really does carry only one letter.
    That is a roster decision or a `doctor_id`, and neither is reachable from
    here.

    Silent on an override run: `_resolve_doctor` returns the caller's id without
    ever consulting the index, so its health has no bearing on the outcome and a
    warning about it would be noise.
    """
    if override_doctor_id:
        return

    counts = f"{len(doctors.ids)} doctor(s), {len(doctors.by_initial)} usable initial(s)"
    problems = []
    if doctors.ambiguous:
        shared = ", ".join(
            f"{initial} ({', '.join(names)})"
            for initial, names in sorted(doctors.ambiguous.items())
        )
        problems.append(f"shared: {shared}")
    if doctors.no_initial:
        problems.append(f"no first name: {', '.join(doctors.no_initial)}")

    if not problems:
        logger.info("Import: doctor index ready — %s", counts)
        return

    # Nothing left to match on: every row naming an initial is guessed, so the
    # whole run gets flagged. Distinguished from the partial case because the
    # remedy differs — this one cannot import anything trustworthy at all.
    if not doctors.by_initial:
        logger.warning(
            "Import: doctor index unusable — %s; %s. Every visit row naming a doctor gets an "
            "arbitrary one and is flagged import_incomplete; pass doctor_id to attribute the "
            "run explicitly.",
            counts,
            "; ".join(problems),
        )
    else:
        logger.warning(
            "Import: doctor index degraded — %s; %s. Visit rows naming those get an arbitrary "
            "doctor and are flagged import_incomplete.",
            counts,
            "; ".join(problems),
        )


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

    # Nobody to attribute to. `_doctor_index_for_run` refuses an empty index
    # before the run starts, and the run then carries that same index all the
    # way through, so this is unreachable in practice — it exists so the type
    # stays honest rather than as a live branch.
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


# The contact columns a later card may supply that an earlier one left empty.
# The rest of the header is deliberately absent: first_name, last_name and
# date_of_birth are the match key, so a difference there means a different
# patient rather than a blank to fill; gender is NOT NULL and falls back to a
# documented default, so it is never blank either — a card that corrects a
# defaulted gender is an overwrite, which this is not.
PATIENT_FILLABLE_FIELDS = ("parent_name", "address", "city", "phone", "email")


def _fill_patient_blanks(patient: Patient, fields: dict) -> bool:
    """Copy card values into columns the stored patient leaves empty.

    Fill-only, never overwrite. Whichever card supplied a value first keeps it,
    which is what makes this safe to run across an existing database: a
    re-import cannot rewrite a phone number somebody has since corrected in the
    UI, and no card has to be judged newer than another — a question these
    hand-filled cards carry nothing to answer.

    Returns whether anything changed, so the summary can distinguish a patient
    that was merely matched from one that was actually written to.
    """
    filled = False
    for name in PATIENT_FILLABLE_FIELDS:
        if getattr(patient, name) is None and fields.get(name) is not None:
            setattr(patient, name, fields[name])
            filled = True
    return filled


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
) -> FileLogDetail:
    """Import one card into `db`, updating `counts` and `errors` in place.

    Does not commit — the caller owns the transaction so that a file either
    lands whole or not at all.

    Returns the log-only detail described on `FileLogDetail`; the counts the
    caller reports to the browser keep travelling in `counts`.
    """
    wb = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
    try:
        rows = [list(row) for row in wb.active.iter_rows(values_only=True)]
    finally:
        wb.close()

    if len(rows) < MIN_ROWS:
        errors.append(f"{filename}: File too short, expected at least {MIN_ROWS} rows")
        return FileLogDetail()

    header = _parse_patient_header(rows, filename, errors)
    if header is None:
        return FileLogDetail()

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
        if _fill_patient_blanks(patient, header.fields):
            counts["patients_updated"] += 1
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

    # Counted, not appended per row. `_doctor_index_for_run` refuses an empty
    # index before the run starts and the run reuses that index throughout, so
    # this branch no longer fires at all — but when it did, it produced one error
    # string per visit row per file. A whole batch turned into thousands of
    # near-identical lines, all of which cross the SSE stream and are
    # concatenated across every batch of a run by the frontend. One line per
    # file says the same thing.
    rows_without_doctor = 0
    rows_with_guessed_doctor = 0
    visits_missing_price = 0
    visit_rows_seen = 0

    for visit_row in _iter_visit_rows(rows):
        visit_rows_seen += 1
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
        if visit_row.price is None:
            visits_missing_price += 1
        if resolved.guessed:
            rows_with_guessed_doctor += 1

    # A card whose visit table is not where the parser expects it produces a
    # patient and nothing else, and used to report clean success — the one
    # failure mode the summary could not distinguish from an empty card. Counted
    # on the iterator, not on `visits_created`, so a re-import of an already
    # imported card stays silent: its rows are seen and then skipped as
    # duplicates, which is a different thing from never finding any.
    if visit_rows_seen == 0:
        errors.append(f"{filename}: No visit rows found — check the file layout")

    if rows_without_doctor:
        errors.append(
            f"{filename}: No doctors in system, skipped {rows_without_doctor} visit row(s)"
        )
    if rows_with_guessed_doctor:
        errors.append(
            f"{filename}: Could not identify the doctor for {rows_with_guessed_doctor} "
            "visit row(s); assigned an arbitrary one and flagged them for review"
        )

    return FileLogDetail(visits_missing_price=visits_missing_price)


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


def _doctor_index_for_run(override_doctor_id: str | None) -> DoctorIndex:
    """Load the index the whole run will use, refusing the run if it is unusable.

    `visits.doctor_id` is NOT NULL, so with an empty `DoctorIndex` every visit
    row hits the `no doctor` branch in `_import_workbook` and is dropped — while
    the patient header around it commits normally. That failure is invisible at
    a glance: the import reports success, patient counts climb, and the visit
    history is silently discarded card after card. It happened on preprod for
    ~2500 files before anybody noticed, because the database was seeded with the
    default admin only and `app/seeds.py` never creates a doctor.

    Rejecting here, before the stream opens, is what makes it an error the user
    reads instead of an empty `visits_created`. A `doctor_id` override stands in
    for the index entirely — `_resolve_doctor` returns it without consulting the
    index — so an empty index is only fatal without one.

    Loading here rather than inside the generator does two things. It halves the
    queries this endpoint makes before streaming, which matters now the frontend
    sends 50 files per request and a migration is ~160 of them. And it closes the
    gap between checking and using: the index that was found non-empty is the
    same object the run attributes visits with, so deleting the last doctor
    mid-request can no longer turn a passing check into a run that drops every
    visit it reads.
    """
    doctors = _load_doctor_index()
    if not override_doctor_id and not doctors.ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "No doctors in the system. Create a user with the DOCTOR role, "
                "or pass doctor_id, before importing."
            ),
        )
    # After the rejection, so the one run that never starts does not also file a
    # complaint about an index it was never going to use.
    _log_doctor_index_health(doctors, override_doctor_id)
    return doctors


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

    A card matching an existing patient fills that patient's *empty* contact
    columns and never overwrites one that already holds a value, so re-importing
    cannot undo a correction made in the UI. `patients_updated` counts the ones
    actually written to, as a subset of `patients_found`.

    Only one import runs at a time. A request arriving while another is in
    progress is refused with a **429** rather than queued — waiting would mean
    holding a second request's whole body in memory, which is what the limit
    exists to prevent. 429 specifically, because the frontend retries that and
    not a 409; see the comment at the raise. Note that the frontend's batched run
    is many requests, so the slot is claimed and released per batch, not for the
    run as a whole.

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

    Callers should send **at most 50 files per request** and repeat the call per
    batch — the frontend's `MAX_FILES_PER_REQUEST`, which is 50 as of its
    `import-run-control` change (it was 200 before). That number is no longer
    only about what this endpoint can take: it also bounds how much work a user's
    Cancel throws away, how much a Resume has to re-send, and how long the
    progress bar sits still while a batch uploads, since `fetch` cannot report
    upload progress and nothing streams back until the whole body has arrived.

    Every file in a request is buffered in memory for the whole run, and a
    dropped connection abandons everything still queued behind the file in
    flight. Batching bounds both. Re-sending a batch is safe — patients are
    matched on name plus date of birth and visits on their content, so an
    already-imported file lands as `visits_skipped`, not as duplicates.
    `MAX_IMPORT_FILES` above is a backstop against a non-browser caller, not a
    supported request size.
    """
    override_doctor_id = _validate_override_doctor(doctor_id)
    doctors = _doctor_index_for_run(override_doctor_id)

    # Claimed after validation, so a rejected request never occupies the slot,
    # and before the file reads, so a second import cannot buffer its copy of
    # the bodies alongside the first.
    slot_token = _IMPORT_SLOT.acquire()
    if slot_token is None:
        # 429, not 409, and the difference is load-bearing. The frontend retries
        # a batch only on status 0, 5xx, 408 and 429 (`isRetryableBatchError` in
        # patient-import.service.ts) and records the batch's files as
        # permanently failed on any other 4xx. This condition is the most
        # transient one the endpoint has — "someone is mid-import, try shortly"
        # — and it stays reachable from the client's own Cancel/Resume even with
        # the background release in place: the slot is not freed until the file
        # in flight finishes, so a Resume sent inside that window still lands
        # here. It just has to be a status the client will try again.
        # 409 also says "conflict with the resource's state", which this is not;
        # nothing about the request is wrong and the same bytes work moments on.
        raise HTTPException(
            status_code=429,
            detail="An import is already running. Wait for it to finish and try again.",
        )

    try:
        # Read all file contents eagerly before returning StreamingResponse.
        # UploadFile handles are closed by FastAPI once the endpoint returns,
        # so they cannot be awaited inside the generator.
        file_data: list[tuple[str, bytes]] = []
        for upload_file in files:
            content = await upload_file.read()
            file_data.append((upload_file.filename or "unknown", content))
    except BaseException:
        # Nothing downstream will run its `finally` if this fails here.
        _IMPORT_SLOT.release(slot_token)
        raise

    # Visible to the background task below, which is the only place that runs on
    # every ending this request can have — including the client hanging up.
    run_state = {"files_done": 0, "reached_end": False}

    def generate():
        summary = {**_empty_counts(), "files_processed": 0, "errors": []}

        try:
            total = len(file_data)
            logger.info("Import: starting, %d file(s)", total)

            for i, (filename, content) in enumerate(file_data):
                # Proof of life for the slot's staleness check.
                _IMPORT_SLOT.touch(slot_token)

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
                log_detail = FileLogDetail()
                try:
                    log_detail = _import_workbook(
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
                    log_detail = FileLogDetail()  # nor is there anything to explain
                finally:
                    db.close()

                if committed:
                    for key, value in file_counts.items():
                        summary[key] += value
                summary["errors"].extend(file_errors)
                summary["files_processed"] += 1
                run_state["files_done"] = summary["files_processed"]

                _log_file_result(
                    filename, i + 1, total, committed, file_counts, file_errors, log_detail
                )

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

            run_state["reached_end"] = True
            # The rollup the `complete` event carries, written down as well. A
            # run's outcome is otherwise only reconstructable by re-reading
            # every per-file line above.
            logger.info(
                "Import: run totals over %d file(s) — %s, flagged incomplete: %s, %d error(s)",
                summary["files_processed"],
                _format_counts(summary),
                _format_flagged(summary["patients_incomplete"], summary["visits_incomplete"])
                or "none",
                len(summary["errors"]),
            )
            yield _sse({"type": "complete", "summary": summary})

        except Exception as e:
            # Previously this vanished into the summary's errors and was never
            # logged, so a run that died mid-way left the server silent.
            logger.exception("Import: fatal error after %d file(s)", summary["files_processed"])
            run_state["reached_end"] = True
            summary["errors"].append(f"Fatal error: {str(e)}")
            yield _sse({"type": "complete", "summary": summary})

        finally:
            # Covers exhaustion and errors. It does NOT reliably cover a client
            # disconnect: measured, a cancelled run held the slot for ~80s,
            # because nothing closes this generator promptly — the suspended
            # frame is only finalised when the garbage collector gets to it. The
            # background task below is what makes the disconnect case
            # deterministic; releasing twice is safe, since the token is stale
            # after the first one.
            _IMPORT_SLOT.release(slot_token)

    def _finish_run() -> None:
        """Release the slot and record how the run ended.

        This is the only place that runs on *every* ending this request has:
        completion, a fatal error, and the client hanging up. Catching
        `GeneratorExit` around the loop would not do it — that exception is not
        delivered promptly, which is the same reason the release lives here.

        Before this, an abandoned import left no server-side trace at all. A
        cancel and a network drop are indistinguishable from here, and during a
        migration either is worth seeing, so both log at warning.
        """
        _IMPORT_SLOT.release(slot_token)
        if run_state["reached_end"]:
            logger.info("Import: finished, %d file(s)", run_state["files_done"])
        else:
            logger.warning(
                "Import: client disconnected after %d of %d file(s); the rest never started",
                run_state["files_done"],
                len(file_data),
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        # Starlette awaits `background` after the response's task group exits,
        # and that group exits on `listen_for_disconnect` firing just as much as
        # on the body being fully sent (starlette/responses.py, StreamingResponse
        # .__call__). So this is the one hook that runs on *both* paths, and it
        # is what frees the slot the moment a client hits Cancel.
        #
        # Without it the frontend's Cancel -> Resume is broken: it retries a
        # batch 3 times over ~3s (MAX_BATCH_ATTEMPTS/RETRY_BASE_MS), against a
        # slot that stayed held for ~80s, so every attempt got a 429 and the
        # resumed run was recorded as failed.
        background=BackgroundTask(_finish_run),
    )
