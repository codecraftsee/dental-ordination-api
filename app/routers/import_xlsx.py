import json
import logging
import re
import threading
import time
import uuid
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
        # The two causes behind `visits_incomplete`, reported apart because the
        # sum cannot be acted on: a missing price is fixed on the visit, an
        # unidentified doctor is fixed by correcting the attribution, and an
        # operator seeing one number had no way to tell which they were looking
        # at. `visits_unmatched_doctor` counts rows whose "Dr" cell named
        # somebody matching could not resolve, whether or not they were flagged
        # — with an authoritative fallback they are not, and the count is then
        # the only record that the cards disagreed with the nomination.
        "visits_missing_price": 0,
        "visits_unmatched_doctor": 0,
    }


def _format_counts(counts: dict) -> str:
    """The counters as one human-readable clause, shared by the per-file and run lines."""
    return (
        f"patients +{counts['patients_created']} "
        f"({counts['patients_found']} matched, {counts['patients_updated']} filled), "
        f"visits +{counts['visits_created']} ({counts['visits_skipped']} skipped)"
    )


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
    run_id: str,
    filename: str,
    index: int,
    total: int,
    committed: bool,
    counts: dict,
    errors: list[str],
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
            "Import[%s]: %s (%s) FAILED — %s",
            run_id,
            filename,
            where,
            "; ".join(errors) or "unknown error",
        )
        return

    flagged = _format_flagged(
        counts["patients_incomplete"],
        counts["visits_incomplete"],
        counts["visits_missing_price"],
    )

    # Only the clauses that apply, so the line says what is actually wrong
    # rather than trailing a "0 flagged incomplete" behind a parse complaint.
    detail = _format_counts(counts)
    if flagged:
        detail += f", flagged incomplete: {flagged}"

    # Recorded whether or not those rows were flagged. With an authoritative
    # fallback nothing marks them in the database and no error names them, so
    # without this line the fact that the cards named somebody the roster could
    # not resolve leaves no trace anywhere — which is the one thing worth
    # keeping about a run that deliberately silences them.
    unmatched = counts["visits_unmatched_doctor"]
    if unmatched:
        detail += f", {unmatched} visit(s) named an unresolvable doctor"

    if errors:
        detail += f"; {'; '.join(_strip_filename(errors, filename))}"

    # The level stays tied to whether a human is needed. An unmatched row the
    # caller has already answered for is expected, not a problem, so it rides an
    # info line and keeps `journalctl -p warning` the review queue it is.
    if flagged or errors:
        logger.warning("Import[%s]: %s — %s", run_id, where, detail)
    else:
        logger.info("Import[%s]: %s — %s", run_id, where, detail)


class DoctorCandidate(NamedTuple):
    id: str
    first_name: str
    last_name: str


class DoctorIndex(NamedTuple):
    # Active doctors only, in both roles this serves: who a card can be matched
    # against, and who may receive a visit whose doctor is unidentified. A
    # deactivated account is a departed or disabled user, and the clinic does
    # not create accounts for doctors who have left, so nothing here needs them.
    ids: list[str]
    candidates: list[DoctorCandidate]
    # Doctors sharing a first initial, kept rather than discarded. A card that
    # writes only that letter cannot be resolved to either of them, and this is
    # the only explanation for a run that flags most of what it imports —
    # reconstructing it afterwards means querying the user table by hand.
    #
    # Required rather than defaulted: a NamedTuple's defaults are one shared
    # object per field, so an empty default here would be the same dict handed
    # to every index that omitted it.
    ambiguous_initials: dict[str, list[str]]
    unnamed: list[str]


def _doctor_label(doc: User) -> str:
    """A doctor as a log line should name them; the id only if they have no name."""
    return f"{doc.first_name or ''} {doc.last_name or ''}".strip() or doc.id


# "Dr M", "dr. Milena" — an honorific the cards may or may not carry, which is
# not part of anybody's name and must not be matched against one.
_HONORIFIC = re.compile(r"^dr\.?\s*", re.IGNORECASE)


def _normalize_doctor_label(raw: str | None) -> str | None:
    """The card's doctor cell reduced to something comparable with a name.

    The cell is filled in by hand across an archive spanning years, so it may
    say `M`, `M.`, ` Mi `, `Dr M` or `Miodrag`. Only the first of those used to
    match anything: the raw cell was looked up in a dict keyed by single
    uppercase letters, so punctuation or an honorific meant no match and a
    flagged visit, for a card that named its doctor perfectly clearly.
    """
    if not raw:
        return None
    text = _HONORIFIC.sub("", raw.strip())
    text = text.strip(" .,;:-_/\\").strip()
    return text.casefold() or None


def _match_doctor(raw_label: str | None, candidates: list[DoctorCandidate]) -> str | None:
    """The one doctor whose name the card's cell begins, or None.

    One rule covers every form the cell takes, because an initial is just a
    one-character prefix: `Miodrag` and `Mio` identify Miodrag Pavkovic, while
    `Mi` and `M` fit both him and Milena and therefore identify nobody. Refusing
    an ambiguous match is the point — `visits.doctor_id` is NOT NULL, so picking
    one anyway would write a fabricated attribution that reads as fact.

    First and last names both, since it is not yet established whether the cards
    name doctors by one or the other. A doctor matching on both counts once.
    """
    key = _normalize_doctor_label(raw_label)
    if not key:
        return None
    hits = {
        c.id
        for c in candidates
        if (c.first_name or "").casefold().startswith(key)
        or (c.last_name or "").casefold().startswith(key)
    }
    return hits.pop() if len(hits) == 1 else None


def _load_doctor_index() -> DoctorIndex:
    """Load the active doctors a run may match against and attribute to.

    Inactive users are excluded from both. `is_active = False` is what
    `DELETE /api/users/{id}` sets, and the clinic does not create accounts for
    doctors who have left — so a deactivated account is a disabled or test one,
    and neither should receive new clinical attribution.
    """
    db = SessionLocal()
    try:
        doctors = (
            db.query(User)
            .filter(
                User.role == UserRole.DOCTOR,
                User.is_active == True,  # noqa: E712 — SQL comparison, not a Python bool test
            )
            .all()
        )

        candidates = [
            DoctorCandidate(doc.id, doc.first_name or "", doc.last_name or "")
            for doc in doctors
            if (doc.first_name or doc.last_name)
        ]
        unnamed = [_doctor_label(doc) for doc in doctors if not (doc.first_name or doc.last_name)]

        # Reported, not used for matching: a shared initial only defeats a card
        # that writes nothing but that letter, which `_match_doctor` discovers
        # per row. Knowing it up front is what lets one line explain a run.
        grouped: dict[str, list[User]] = {}
        for doc in doctors:
            initial = (doc.first_name or "")[:1].upper()
            if initial:
                grouped.setdefault(initial, []).append(doc)
        ambiguous_initials = {
            i: [_doctor_label(d) for d in docs] for i, docs in grouped.items() if len(docs) > 1
        }

        return DoctorIndex([doc.id for doc in doctors], candidates, ambiguous_initials, unnamed)
    finally:
        db.close()


def _log_doctor_index_health(
    run_id: str, doctors: DoctorIndex, override_doctor_id: str | None
) -> None:
    """Say once per run what attribution will and will not be able to resolve.

    `_import_workbook` already reports a card whose doctor could not be
    identified, so a run against an unhelpful roster writes that symptom once
    per *file* — around 8000 times during the migration this was written for,
    every line saying the same thing. The cause is this single line, and it
    used to be `info`: the quietest thing in the journal, sitting underneath its
    own consequences.

    What it reports is a *prediction*, not a verdict, because ambiguity now
    depends on the cell. `_match_doctor` accepts any prefix of a name, so two
    doctors sharing an initial only defeat a card that writes nothing but that
    letter — `Mio` still resolves where `M` cannot. Naming them up front is what
    lets one line explain a run's worth of flags.

    Silent on an override run: `_resolve_doctor` returns the caller's id without
    consulting any of this, so its health has no bearing on the outcome.
    """
    if override_doctor_id:
        return

    counts = f"{len(doctors.ids)} active doctor(s), {len(doctors.candidates)} matchable"
    problems = []
    if doctors.ambiguous_initials:
        shared = ", ".join(
            f"{initial} ({', '.join(names)})"
            for initial, names in sorted(doctors.ambiguous_initials.items())
        )
        problems.append(f"sharing an initial: {shared}")
    if doctors.unnamed:
        problems.append(f"no name to match on: {', '.join(doctors.unnamed)}")

    if not problems:
        logger.info("Import[%s]: doctor index ready — %s", run_id, counts)
        return

    # Nothing carries a name, so no cell can match anything and every visit is
    # attributed by fallback. Distinguished from the partial case because the
    # remedy differs: this one cannot resolve a single row, however written.
    if not doctors.candidates:
        logger.warning(
            "Import[%s]: doctor index unusable — %s; %s. No card can be matched to anybody, so "
            "every visit is attributed by fallback, counted in visits_unmatched_doctor and "
            "otherwise unmarked.",
            run_id,
            counts,
            "; ".join(problems),
        )
    else:
        logger.warning(
            "Import[%s]: doctor index degraded — %s; %s. A card naming only that letter cannot "
            "be resolved to either of them and goes to the fallback; a longer form such as the "
            "full first name still resolves.",
            run_id,
            counts,
            "; ".join(problems),
        )


class ResolvedDoctor(NamedTuple):
    id: str | None
    # Whether `id` came from the card or from the caller's nominated fallback.
    # No longer flags the visit — the caller answered for these rows — but it is
    # counted in `visits_unmatched_doctor`, which with no flag and no error is
    # the only signal that the card named somebody the roster could not resolve.
    guessed: bool


def _resolve_doctor(
    override_doctor_id: str | None,
    doctor_label: str | None,
    doctors: DoctorIndex,
    fallback_doctor_id: str | None,
) -> ResolvedDoctor:
    """A caller-supplied doctor wins, then a name match, then the fallback.

    The fallback replaces a `random.choice` over every doctor in the system.
    Random attribution was wrong twice over: it invented a clinical fact, and it
    was not even stable — re-importing the same card could attribute it to
    somebody else. A fallback the caller nominated is still not a statement
    about who did the work, but it is at least a decision somebody made, and it
    is the same decision every time the card is read.

    `fallback_doctor_id` is None only when `_import_workbook` is driven directly
    with an empty index; the endpoint refuses such a run before it starts. The
    caller then sees `id is None` and skips the row, as it always did.
    """
    if override_doctor_id:
        return ResolvedDoctor(override_doctor_id, guessed=False)

    if doctor_label:
        matched = _match_doctor(doctor_label, doctors.candidates)
        if matched:
            return ResolvedDoctor(matched, guessed=False)
        # The card names somebody no name begins with, or a prefix two doctors
        # share. Either way it identifies nobody, so the row goes to the
        # fallback the caller nominated for exactly this case. Counted, not
        # flagged.
        return ResolvedDoctor(fallback_doctor_id, guessed=True)

    # The row names nobody, so nothing contradicts the fallback: the caller was
    # asked who should own exactly these rows and answered. Not a guess, and not
    # flagged — that is what keeps the review queue to the rows in real doubt.
    return ResolvedDoctor(fallback_doctor_id, guessed=False)


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
    doctor_label: str | None
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
            doctor_label=cell_str(row[5]) if len(row) > 5 else None,
            tooth_number=extract_tooth_number(diagnosis_notes),
            price=parse_price(row),
        )


def _import_workbook(
    db: Session,
    filename: str,
    content: bytes,
    doctors: DoctorIndex,
    override_doctor_id: str | None,
    fallback_doctor_id: str | None,
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
    visit_rows_seen = 0

    for visit_row in _iter_visit_rows(rows):
        visit_rows_seen += 1
        resolved = _resolve_doctor(
            override_doctor_id, visit_row.doctor_label, doctors, fallback_doctor_id
        )
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

        # A missing price is the only thing that flags a visit. An unidentified
        # doctor used to as well, on the reasoning that the fallback id is a
        # stand-in and must not read as fact — but the caller nominates that
        # fallback explicitly, which is them answering for exactly these rows.
        # Flagging them anyway marked most of a migration written with initials
        # for review, so the queue held everything and meant nothing.
        #
        # The evidence survives without the flag: `imported_doctor_label` keeps
        # what the card said on every visit, and `visits_unmatched_doctor` counts
        # the rows, so a wrong attribution is still findable.
        unmatched_doctor = resolved.guessed
        incomplete = visit_row.price is None

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
                # Kept whatever the outcome, including a clean match: the column
                # then means one thing — what the chart said — and a match that
                # was wrong stays detectable instead of being invisible.
                imported_doctor_label=visit_row.doctor_label,
            )
        )
        counts["visits_created"] += 1
        if incomplete:
            counts["visits_incomplete"] += 1
        if visit_row.price is None:
            counts["visits_missing_price"] += 1
        if unmatched_doctor:
            counts["visits_unmatched_doctor"] += 1

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
    # No error for an unresolved doctor. Nothing is flagged any more, so
    # "flagged them for review" would be false — and the frontend's
    # `classifyFileOutcome` reports any file with a non-empty `errors` as
    # incomplete, so a line here would keep the whole migration looking failed
    # whatever the flag says. The count travels in `visits_unmatched_doctor` and
    # in the journal instead, which is where a reviewer can act on it.


# Who a caller may name to receive visits. DOCTOR is the obvious one; ADMIN is
# here because the clinic's administrator also practises, and `User.role` holds
# a single value, so the alternative was a second account for one person.
# Matching never targets an admin — cards name doctors — but an explicit choice
# may.
ATTRIBUTABLE_ROLES = (UserRole.DOCTOR, UserRole.ADMIN)


def _validate_attributable(user_id: str | None, field: str) -> str | None:
    """Check a caller-named doctor before the response starts streaming.

    Once the StreamingResponse begins the status code is already sent, so a bad
    id has to be rejected here to surface as a real HTTP 400 rather than as an
    error buried in an event the frontend shows in a list.

    Inactive users are refused. They are excluded from matching and from the
    fallback pool, and an explicit id that quietly escaped that rule would make
    "deactivated" mean nothing — `DELETE /api/users/{id}` is a soft delete, so
    this is the same check that stops a deleted account being handed new work.
    """
    if not user_id:
        return None
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(
                User.id == user_id,
                User.role.in_(ATTRIBUTABLE_ROLES),
                User.is_active == True,  # noqa: E712 — SQL comparison, not a Python bool test
            )
            .first()
        )
        if not user:
            raise HTTPException(
                status_code=400,
                detail=f"{field}: no active doctor with id {user_id} found",
            )
        return user.id
    finally:
        db.close()


def _doctor_index_for_run(
    run_id: str, override_doctor_id: str | None, fallback_doctor_id: str | None
) -> tuple[DoctorIndex, str | None]:
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
    fallback = None

    if not override_doctor_id:
        if not doctors.ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No active doctors in the system. Create a user with the DOCTOR role, "
                    "or pass doctor_id, before importing."
                ),
            )

        # A run must know who owns the rows it cannot attribute, before it
        # writes any of them. One active doctor is the only possible answer
        # rather than a choice, so it does not need asking for; more than one
        # does, and guessing is what this whole change exists to stop.
        fallback = fallback_doctor_id or (doctors.ids[0] if len(doctors.ids) == 1 else None)
        if not fallback:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Several doctors exist, so visits whose doctor cannot be identified "
                    "have no owner. Pass fallback_doctor_id to say who should receive them, "
                    "or doctor_id to attribute the whole import to one doctor."
                ),
            )

    # After the rejections, so a run that never starts does not also file a
    # complaint about an index it was never going to use.
    _log_doctor_index_health(run_id, doctors, override_doctor_id)
    return doctors, fallback


@router.post("/xlsx")
async def import_xlsx_files(
    files: list[UploadFile] = File(...),
    doctor_id: str | None = Form(None),
    fallback_doctor_id: str | None = Form(None),
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

    Two form fields decide attribution, and they are alternatives:

    - `doctor_id` assigns that one doctor to every imported visit, skipping the
      cards entirely. Nothing is flagged, because the caller has said who it was.
    - `fallback_doctor_id` keeps per-card matching and says only who receives
      the rows that matching cannot identify.

    With neither, the run needs at least one active doctor, and — if more than
    one exists — a `fallback_doctor_id`, or it is rejected with a 400 before the
    stream opens. A single active doctor is the only possible answer rather than
    a choice, so it is used without being asked for.

    Matching reads the card's "Dr" cell as a name: the normalized text must be a
    prefix of exactly one active doctor's first or last name, so `Miodrag` and
    `Mio` identify him while `M` fits him and Milena both and therefore
    identifies nobody. Whatever the cell said is stored verbatim on the visit as
    `imported_doctor_label`, on every row, so a flagged visit can be resolved
    later rather than only dismissed.

    A row the card named but matching could not identify goes to the fallback and
    is **not** flagged. The caller nominated that fallback for exactly these
    rows, so the id is an answer rather than a stand-in. It is still counted in
    `visits_unmatched_doctor` and still carries `imported_doctor_label`, so a
    wrong attribution stays findable — but nothing in the database marks it, and
    no error names it. That is deliberate: flagging them put most of a migration
    written with initials into a review queue nobody could work through, and the
    frontend reports any file with a non-empty `errors` as incomplete.

    A missing price is therefore the only thing that flags a visit, and
    `visits_missing_price` reports it beside `visits_incomplete`.

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
    # One token per request, prefixed on every line this request writes. The
    # frontend sends 50 files per batch, so a migration is ~160 requests whose
    # per-file lines all say "file 12/50" — identical strings that only their
    # timestamps separate. This makes one batch greppable, and it is per request
    # rather than per run because the server never learns that batches belong
    # together; giving a run one id means the client sending it.
    run_id = uuid.uuid4().hex[:6]
    override_doctor_id = _validate_attributable(doctor_id, "doctor_id")
    run_fallback_id = _validate_attributable(fallback_doctor_id, "fallback_doctor_id")
    doctors, run_fallback_id = _doctor_index_for_run(run_id, override_doctor_id, run_fallback_id)

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
            logger.info("Import[%s]: starting, %d file(s)", run_id, total)

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
                try:
                    _import_workbook(
                        db,
                        filename,
                        content,
                        doctors,
                        override_doctor_id,
                        run_fallback_id,
                        file_counts,
                        file_errors,
                    )
                    db.commit()
                    committed = True
                except Exception as e:
                    db.rollback()
                    file_errors.append(f"{filename}: {str(e)}")
                    # Nothing was persisted, and that includes the log-only
                    # counters, which now travel in this same dict.
                    file_counts = _empty_counts()
                finally:
                    db.close()

                if committed:
                    for key, value in file_counts.items():
                        summary[key] += value
                summary["errors"].extend(file_errors)
                summary["files_processed"] += 1
                run_state["files_done"] = summary["files_processed"]

                _log_file_result(
                    run_id, filename, i + 1, total, committed, file_counts, file_errors
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
                "Import[%s]: run totals over %d file(s) — %s, flagged incomplete: %s, "
                "%d visit(s) named an unresolvable doctor, %d error(s)",
                run_id,
                summary["files_processed"],
                _format_counts(summary),
                _format_flagged(
                    summary["patients_incomplete"],
                    summary["visits_incomplete"],
                    summary["visits_missing_price"],
                )
                or "none",
                summary["visits_unmatched_doctor"],
                len(summary["errors"]),
            )
            yield _sse({"type": "complete", "summary": summary})

        except Exception as e:
            # Previously this vanished into the summary's errors and was never
            # logged, so a run that died mid-way left the server silent.
            logger.exception(
                "Import[%s]: fatal error after %d file(s)", run_id, summary["files_processed"]
            )
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
            logger.info("Import[%s]: finished, %d file(s)", run_id, run_state["files_done"])
        else:
            logger.warning(
                "Import[%s]: client disconnected after %d of %d file(s); the rest never started",
                run_id,
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
