# Dental Ordination API - Claude Instructions

## Tech Stack
- **Framework**: FastAPI
- **Database**: PostgreSQL everywhere — local dev, tests, and deployed. No SQLite.
- **ORM**: SQLAlchemy 2.x
- **Auth**: JWT (access + refresh tokens) via python-jose, bcrypt via passlib
- **Validation**: Pydantic v2
- **Server**: Uvicorn with --reload for dev
- **Lint/format**: ruff, configured in `pyproject.toml`

## Start Server
```bash
venv/bin/uvicorn app.main:app --reload            # macOS / Linux
venv\Scripts\uvicorn.exe app.main:app --reload    # Windows
```

## Lint and Format
```bash
venv/bin/ruff check app tests        # lint
venv/bin/ruff format app tests       # format
```

Rules are `E`, `F`, `I`, `B`, `UP` at line-length 100. The exclusions are all in
`pyproject.toml` with their reasoning; do not drop any of them while
"tidying" the config:

- `B008` is neutralised via `extend-immutable-calls`. A function call in an
  argument default is FastAPI's dependency-injection mechanism, not the bug the
  rule is looking for.
- `ARG` and `ERA` are **not** enabled. They produced 37 findings and none were
  actionable — pytest fixture parameters that force setup ordering, FastAPI's
  mandated `lifespan(app)` signature, and `# Nurse: read-only` reported as
  commented-out code. Worst case was `import_xlsx.py`'s permission dependency,
  reported as an unused argument while being the only thing keeping that
  endpoint admin-only.
- `UP042` is ignored. It rewrites `class UserRole(str, Enum)` into `StrEnum`,
  which changes what `str()` and f-strings produce — `"UserRole.ADMIN"` against
  `"ADMIN"`. These enums reach the API through Pydantic and the database through
  SQLAlchemy. Nothing stringifies them bare today, which is why the change would
  pass the suite and surface later.
- `UP047` is ignored: PEP 695 generics instead of the `ModelT` TypeVar, no
  autofix, a style preference.
- `E501` is ignored. The formatter owns line length and wraps everything it can;
  what remains are string literals it cannot split, so leaving the rule on made
  `ruff check` and `ruff format` permanently disagree.

## Tests
Tests run against **real PostgreSQL**, never SQLite — same engine as production.

```bash
docker compose -f docker-compose.test.yml up -d   # test db on port 55432
pytest
docker compose -f docker-compose.test.yml down    # when finished
```

- `tests/conftest.py` points the whole process at the test database *before*
  importing `app.*`, because `app/database.py` builds its engine at import time
  and `app/routers/import_xlsx.py` bypasses the `get_db` dependency.
- Each session drops and recreates the `public` schema, so `create_all()` plus
  the startup migrations in `app/main.py` run from scratch. A guard refuses to
  start unless the database name contains `test`.
- The suite is characterization-style: it pins current status codes and
  `detail` strings so refactors can't silently change the API contract.

## User Roles
`UserRole` has exactly three values. Permissions are defined in
`app/permissions.py` and returned by `GET /api/auth/me` for the logged-in user.

| Role | Description |
|------|-------------|
| `ADMIN` | Everything: user management, bulk delete, XLSX import, all CRUD |
| `DOCTOR` | Create/update patients, visits, diagnoses, treatments; full access to patient documents; read-only on users. **Cannot delete** patients, visits, diagnoses or treatments |
| `NURSE` | Read-only on everything |

There is no `assistant` or `patient` role — the docs used to claim otherwise.
`nurse` is the assistant-equivalent role.

## API Endpoints

### Auth
- `POST /api/auth/login` — login, returns tokens
- `POST /api/auth/refresh` — refresh access token
- `POST /api/auth/set-password` — set initial password from an invite token
- `PUT /api/auth/change-password` — change own password
- `GET /api/auth/me` — current user, including their permission list

### Users (Admin only, except `GET` which any role may call)
- `GET/POST /api/users`
- `GET/PUT/DELETE /api/users/{id}` — `DELETE` is a **soft delete** (`is_active = False`)
- `POST /api/users/{id}/resend-invite`

Doctors are users with `role=DOCTOR`; there is no separate `/api/doctors`
resource. The `doctors` table was merged into `users` and dropped.

### Patients
- `GET/POST /api/patients`
- `GET/PUT/DELETE /api/patients/{id}`
- `PATCH /api/patients/{id}/dismiss-warning` — clear `import_incomplete`

### Patient Documents
- `GET/POST /api/patients/{id}/documents`
- `GET/DELETE /api/patients/{id}/documents/{document_id}`
- Files live in Supabase Storage; responses carry a short-lived `signed_url`

### Visits
- `GET/POST /api/visits`
- `GET/PUT/DELETE /api/visits/{id}`
- `PATCH /api/visits/{id}/dismiss-warning` — clear `import_incomplete`

### Diagnoses & Treatments
- `GET/POST /api/diagnoses`, `PUT/DELETE /api/diagnoses/{id}`
- `GET/POST /api/treatments`, `PUT/DELETE /api/treatments/{id}`

### Admin Bulk Delete
- `DELETE /api/admin/visits|patients|diagnoses|treatments|all`

### Import
- `POST /api/import/xlsx` — import patient dental cards from XLSX files (admin only)
  - Accepts one or more `multipart/form-data` files (`files` field)
  - Streams **Server-Sent Events** (`text/event-stream`) instead of returning a plain JSON response
  - Event types: `progress` (before each file), `file_done` (after each file), `complete` (final summary)
  - Frontend must consume via `fetch()` + `ReadableStream` (not `EventSource`, which is GET-only)
  - Each file is committed/rolled back independently; per-file errors appear in
    the event payload, not as HTTP errors. Validation that applies to the *whole
    run* is the exception and happens before the stream opens, because once the
    first byte is written the `200` is committed and a status code can no longer
    be changed — an unknown `doctor_id` and the doctor check below both `400`
    there.
  - **Requires at least one *active* `DOCTOR` user unless `doctor_id` is passed.**
    `visits.doctor_id` is `NOT NULL` and `_resolve_doctor` returns `None` only
    when no doctor exists at all, so an empty doctor table meant every visit row
    was dropped while the patient header around it committed normally — a
    reported-successful import that created patients with no visit history. That
    ran on preprod for ~2500 files before anyone noticed, because `app/seeds.py`
    seeds the default admin and never a doctor. `_doctor_index_for_run()` now
    rejects the request with a `400` instead. Recovery is a re-import once a
    doctor exists: patients match on name plus date of birth and are found, not
    duplicated, and their empty visit histories fill in.
  - **Attribution: two form fields, and they are alternatives** (a third,
    `fallback_is_authoritative`, modifies the second rather than competing with
    them). `doctor_id`
    assigns one doctor to every visit and skips the cards entirely — nothing is
    flagged, the caller has said who it was. `fallback_doctor_id` keeps per-card
    matching and names only the owner of the rows matching cannot identify.
    With neither, a run needs at least one active doctor and — if more than one
    exists — a fallback, or it is refused with a `400` before the stream opens.
    One active doctor is the only possible answer rather than a choice, so it is
    used without being asked for. Both fields accept `ADMIN` as well as
    `DOCTOR`, because `User.role` holds a single value and the administrator
    also practises; matching itself never selects an admin. Both refuse an
    inactive user, or an explicit id would escape the rule below.
    A `fallback_is_authoritative` bool briefly existed to make the flagging below
    opt-out; it was removed before merge in favour of never flagging at all. Do
    not reintroduce it without reading the next-but-one bullet.
  - **Matching reads the "Dr" cell as a name, not as an initial.** The
    normalized text must be a prefix of exactly one active doctor's first *or*
    last name, so `Miodrag` and `Mio` identify him while `Mi` and `M` fit
    Milena too and therefore identify nobody. An initial is just a
    one-character prefix, which is why there is one rule rather than two. This
    replaced a dict keyed by single uppercase letters that the *whole cell* was
    looked up in — so `M` matched and `M.`, ` m `, `Dr M` and `Miodrag` all
    matched nothing, flagging cards that named their doctor perfectly clearly.
    Normalization strips a leading `Dr`/`Dr.`, surrounding punctuation and
    whitespace. Ambiguity is refused rather than guessed at: `visits.doctor_id`
    is `NOT NULL`, so a pick would be a fabricated attribution reading as fact.
  - **Inactive users are excluded from matching and from the fallback.**
    `DELETE /api/users/{id}` is a soft delete, and the clinic does not create
    accounts for doctors who have left — so a deactivated account is a disabled
    or test one, and must not receive new clinical attribution.
  - **A visit whose doctor could not be identified is counted, not flagged.**
    The row gets the fallback doctor, because `visits.doctor_id` is `NOT NULL`,
    and imports clean. It is counted in `visits_unmatched_doctor` and carries
    `imported_doctor_label`; nothing else marks it and **no error names it**.
    This is deliberate and was arrived at the hard way:
    - It used to be flagged `import_incomplete` and reported as an error, the
      reasoning being that a stand-in id must not read as fact. But the caller
      *nominates* that fallback for exactly these rows, so it is an answer, not a
      guess. On the real cards — written with initials this roster cannot
      resolve — that flagged 3 to 12 rows in almost every file.
    - The error string was the worse half. `classifyFileOutcome` in the Angular
      app reports **any file with a non-empty `errors` as `incomplete`**,
      independent of the counters, so a completely successful import came back
      with every card labelled incomplete. Suppressing the flag alone does not
      fix that; the error has to go too. Anything appended to `errors` for a
      normal, expected outcome will resurface this.
    - The fallback replaced a `random.choice` over every doctor, which invented a
      clinical fact *and* was unstable — the same card could land on two
      different doctors. That is the problem worth solving here; flagging was
      not.
    A missing price is now the only thing that flags a visit. Unreadable gender
    or DOB still flags the *patient* and still appends an error, which is correct
    — nothing has answered for those.
  - **`visits.imported_doctor_label` keeps what the card said, verbatim.**
    Written on every visit, not only unresolved ones, so the column means one
    thing and a *wrong* match stays detectable. Without it the letter the chart
    was written with is discarded at parse time, and a flagged visit can only be
    dismissed, never resolved. Read-only through the API: present on
    `VisitResponse`, absent from `VisitBase`. Resolving a flag means correcting
    `doctor_id`; rewriting the quote would destroy the evidence.
  - **Capped at `MAX_IMPORT_FILES` (5000) files per request.** Starlette's
    multipart parser defaults to 1000 and FastAPI calls `request.form()` with no
    arguments, so file 1001 used to be rejected with a JSON `400` raised *before*
    this router ran — no log line, and no `text/event-stream` for the frontend's
    SSE reader. `_RaisedFileLimitRoute` pre-parses the body to raise that limit.
  - The frontend sends **50 files per request** and repeats per batch
    (`MAX_FILES_PER_REQUEST` in the `dental-ordination` repo's
    `import-batch.ts`) — it was 200 before that repo's `import-run-control`
    change. The number is no longer only about what this endpoint can take: it
    also bounds how much work a Cancel throws away, how much a Resume re-sends,
    and how long the progress bar sits still during upload, since `fetch` cannot
    report upload progress. An 8,000-file migration is therefore ~160 requests.
    `MAX_IMPORT_FILES` stays at 5000 as a backstop against a non-browser caller,
    not as a supported size — Caddy's 100MB body limit already bounds the memory
    a request can cost, and anything under Starlette's own 1000 would make
    `_RaisedFileLimitRoute` tighten the default instead of raising it.
    Re-sending a batch is safe — patients match on name plus date of birth and
    visits on their content, so an already-imported file counts as
    `visits_skipped`, not a duplicate.
  - **A cancelled run stops at the file in flight.** Verified against a live
    uvicorn with a client that hard-closes the socket: the file being parsed
    when the connection drops commits, and every file queued behind it is never
    started. The client therefore sees one fewer `file_done` than the number of
    files that actually committed — harmless, since re-sending the in-flight
    file comes back as `visits_skipped`, but the frontend's resume manifest is
    off by one at the abort point. Runs log their ending: `info` on completion,
    `warning` naming how far it got on a disconnect. Before that, an abandoned
    import left no server-side trace at all.
  - **One import at a time.** A request arriving while another is in progress is
    refused with a **`429`**, not queued — waiting would mean a second request
    sitting on its whole body in memory, which is the thing being rationed. The
    status must stay `429`: the frontend retries a batch on status 0, 5xx, 408
    and 429 only (`isRetryableBatchError` in `patient-import.service.ts`) and
    records the files as permanently failed on any other 4xx. Busy is transient
    and is reachable from the client's own Cancel/Resume, so a `409` here — which
    is what this originally returned — turns a race into a dead run. The
    slot is in-process (`_ImportSlot`), which is exactly as wide as the process
    it protects at `--workers 1`, and means a crash clears it rather than
    stranding a lock. **Adding workers silently stops this guarding anything**;
    the replacement is a Postgres advisory lock held on one dedicated connection
    for the whole run, not the per-file sessions used today. Acquisitions are
    fenced with a token so a displaced holder cannot release its successor's
    claim, and so the overlapping releases below are harmless.
    - **The slot is released three ways**, and the first one is load-bearing:
      the response's `BackgroundTask`, which Starlette awaits once the response
      task group exits — on a client disconnect just as much as on a fully sent
      body; the generator's own `finally`, for exhaustion and errors; and the
      `IMPORT_STALE_AFTER_SECONDS` (300) takeover, for the case where the
      generator never runs at all, since Starlette builds the response before it
      iterates the body.
    - **Do not remove the `BackgroundTask`.** Measured against a live uvicorn
      with a client that hard-closes the socket: without it a cancelled run held
      the slot for **~80 seconds**, because nothing closes a suspended generator
      promptly — its `finally` waits on the garbage collector — and the
      staleness takeover is far too slow to help. The frontend retries a batch
      three times over ~3 seconds, so Cancel then Resume failed every time. With
      it, the slot frees in **~0.3s**, the residual being the in-flight file
      finishing. A `TestClient` test cannot catch a regression here (it
      finalises the generator in-process), so the guard is the structural
      assertion in `test_the_response_carries_a_background_slot_release`.
    - Caveat: the frontend's batched run is *many* requests, so the slot is held
      per batch, not per run. Two people importing at once will not corrupt
      anything, but they can interleave between batches and both get a `429`
      part-way. The client retries it three times with backoff, so a brief
      overlap usually resolves itself; a sustained one does not. Fixing that
      properly means a run id sent with every batch and a slot keyed to it — a
      frontend change, deliberately not done yet.
  - **A matched patient's empty contact columns are filled in, never
    overwritten.** `parent_name`, `address`, `city`, `phone` and `email` are
    copied from the card only where the stored patient holds `NULL`, so the
    first card to supply a value keeps it and a re-import cannot undo a
    correction made in the UI. That also avoids having to decide which of two
    hand-filled cards is newer — they carry nothing to answer it with.
    `first_name`, `last_name` and `date_of_birth` are the match key, and
    `gender` is `NOT NULL` with a documented default, so none of them is
    fillable; a card that would correct a defaulted gender is an overwrite and
    is left to the UI. `patients_updated` in the summary counts patients
    actually written to, a subset of `patients_found`.
  - **A card that yields no visit rows is reported**, not counted as a clean
    import. A patient whose visit table is not where the parser expects it used
    to produce a patient and silence — the one failure the summary could not
    tell apart from an empty card. The count is taken on the row iterator, so a
    re-import whose rows are all skipped as duplicates stays quiet. This also
    covers `MIN_ROWS` (14) accepting a file that `FIRST_VISIT_ROW` (14, a
    zero-based index) then finds nothing in.
  - **Tooth numbers are validated against FDI notation** — `11-18`, `21-28`,
    `31-38`, `41-48` permanent and `51-55`, `61-65`, `71-75`, `81-85` deciduous.
    `TOOTH_REGEX` matches any digits after `d.`, so `"d. 2000"` used to be
    stored as tooth 2000. Anything outside the set becomes `NULL`; the text is
    kept verbatim in `diagnosis_notes` regardless, so declining to interpret it
    loses nothing. Verified against the real cards first — every tooth number in
    them is already inside the set.
  - Duplicate visit rows *within a single card* are still imported twice. The
    session sets `autoflush=False`, so the duplicate check only ever saw rows
    already committed. Longstanding behaviour, left alone deliberately.
  - **What a run writes to the journal.** Every line of one request is prefixed
    `Import[<token>]`, the token being per *request* — the server never learns
    that the frontend's ~160 batches belong to one migration, so a true run id
    would have to come from the Angular app. Levels make `journalctl -p warning`
    the review queue: a clean file is `info`, and anything wanting a human is a
    `warning`. Three traps, each of which looks like tidying:
    - **A card's filename is a patient's name**, and since the journald switch
      these lines outlive deploys by months — outside the database, outside its
      roles, and untouched by deleting that patient through the API. So the name
      is written *only* for a file that **failed**: its transaction rolled back,
      leaving this line as the sole evidence the file was read, and a position
      cannot identify it afterwards. A flagged file logs `file N/M` instead,
      because its records are in the database wearing `import_incomplete` and can
      be listed from there. Error strings are prefix-stripped for the same
      reason — every one is built as `f"{filename}: ..."`, so printing them raw
      would put the name straight back on a line that just omitted it.
    - **The doctor-index line's level tracks whether attribution can work.** An
      index with no usable initials means every visit naming a doctor gets an
      arbitrary one, so it warns and names the colliding doctors. It was `info`,
      which put the one line explaining a whole bad run underneath the ~8000
      per-file lines it caused. It stays silent when `doctor_id` was passed,
      since `_resolve_doctor` never consults the index then.
    - **Anything in `counts` is API contract.** The counts dict is spread into
      the `file_done` SSE event verbatim, so a counter added there joins what the
      Angular app parses — add one deliberately or not at all. `errors` is not a
      way round it either: the frontend concatenates those across every batch and
      shows them to whoever is importing. There used to be a `FileLogDetail`
      NamedTuple carrying `visits_missing_price` as a journal-only fact for
      exactly this reason; it is gone, because that number turned out to be one
      the operator needs. See the next bullet.
    - **`visits_missing_price` and `visits_unmatched_doctor` are both in
      `counts`.** `visits_missing_price` explains `visits_incomplete`, which it
      is now the only cause of. `visits_unmatched_doctor` reports something
      nothing else does at all: those rows are not flagged and raise no error, so
      this counter and `imported_doctor_label` are the entire audit trail for an
      attribution the cards disagreed with. Do not drop it to tidy up, and do not
      convert it into an `errors` entry — see the flagging bullet above for why
      that breaks the frontend's file status.

## Planned — not implemented
Documented here so nobody assumes these already work.

- **`POST /api/auth/logout`** — there is currently **no server-side logout and no
  refresh-token revocation**. A refresh token stays valid for its full
  `REFRESH_TOKEN_EXPIRE_DAYS` (7) even after the user "logs out"; the frontend
  only discards it locally. Implementing this needs somewhere to record revoked
  tokens (a `jti` claim plus a denylist table, or short-lived refresh tokens
  rotated on every use).
  - Deactivating a user *does* take effect immediately — `get_current_user`
    checks `is_active` on every request — so disabling an account is the
    current way to cut someone off.

## Key Files
- `app/main.py` — app entry point, CORS, routers, and `run_startup_migrations()`
- `app/seeds.py` — the default admin plus the diagnosis/treatment catalogues,
  called by `run_startup_migrations()`
- `app/config.py` — settings via pydantic-settings, reads `.env`
- `app/database.py` — SQLAlchemy engine/session
- `app/dependencies.py` — auth dependencies only: `get_current_user`,
  `require_permission`, `oauth2_scheme`. Everything here is for `Depends()`
- `app/db_helpers.py` — row helpers the route bodies call directly:
  `get_or_404`, `apply_update`, `ensure_code_available`
- `app/routers/` — one file per resource
- `app/models/` — SQLAlchemy models
- `app/schemas/` — Pydantic request/response schemas
- `app/services/auth.py` — JWT token creation/validation

## Default Admin
- Email: `admin@dentalclinic.com`
- Password: `Test123#` (seeded on first startup if the user doesn't exist — see
  `run_startup_migrations()` in `app/main.py`)
- **This admin is the only user seeded — no doctor is created.** A fresh
  database therefore cannot import XLSX cards until somebody creates a `DOCTOR`
  user, which the import endpoint now enforces rather than discovering
  mid-import. Doctor matching reads the card's "Dr" cell as a prefix of a
  doctor's first or last name, so the roster's names have to correspond to what
  the cards actually write.

## Environment Variables (.env)

`SECRET_KEY` below is the built-in default **verbatim**, and that is deliberate:
`app/config.py` recognises this exact string and refuses to boot whenever
`APP_ENV` is anything other than `local`. Do not "improve" it into a different
placeholder — a value the guard does not recognise lets a deployed instance
start while signing JWTs with a key that is public in this repository. Generate
a real one with `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`.

```
APP_ENV=local
DATABASE_URL=postgresql://postgres:password@localhost:5432/dental_ordination
SECRET_KEY=your-super-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ALLOWED_ORIGINS=http://localhost:4200
FRONTEND_URL=http://localhost:4200
```

## Known Issues & Fixes
- **passlib + bcrypt 5.x incompatibility**: `bcrypt` must stay below 4.1, which
  moved `__about__` — passlib reads it at import. Pinned exactly (`==4.0.1`)
  rather than as a `<4.1` ceiling so a CI build and a server build resolve the
  same wheel. `resend` is pinned exactly for the same reason.
- **Startup migrations still run on every boot**: `run_startup_migrations()` in
  `app/main.py` re-executes its PostgreSQL DDL against the live database at every
  start (`DROP TABLE staff_profiles`, `DROP TABLE doctors`, `ALTER ... DROP NOT
  NULL`, an enum rename). The dead SQLite branches are gone. The two
  `CREATE INDEX IF NOT EXISTS` statements at the end are there for the same
  reason and are *not* redundant with the `Index()` entries on the models:
  `create_all()` skips tables that already exist, indexes included, so the model
  definitions only ever reach a fresh database. Names match on both sides. Retiring the rest
  means setting up alembic — it is pinned in `requirements.txt` but there is no
  `alembic/` directory — and stamping the current schema as a baseline first.
  This is also the ceiling on CD: a deploy can be rolled back, but the schema it
  changed on the way up cannot, and the image is stuck at `--workers 1`.
- **`specs/` is gitignored and must stay that way**: it held four real patient
  dental cards, committed 2026-02-07 and untracked on 2026-08-10. They are still
  present in git history; removing them from past commits needs `git-filter-repo`
  and a force-push, which was deliberately deferred. Never commit patient data.

## CORS Allowed Origins
Driven by the `ALLOWED_ORIGINS` env var (comma-separated). The default is
`http://localhost:4200` only — a local-dev fallback.

Every deployed environment **must set `ALLOWED_ORIGINS` explicitly**; if it is
omitted the deployed frontend's requests get blocked. Deployment hostnames are
deliberately not baked into the default, so a retired host can never keep CORS
access by accident.

## Branches

The promotion path is **`develop` → `preprod` → `master`**, in that order.

- **`develop`** — the default branch and the target for pull requests. Day-to-day
  work branches off it and merges back into it. May run ahead of the other two.
- **`preprod`** — what the Hetzner box deploys from; see below.
- **`master`** — the production branch. It only ever receives merges from
  `preprod`, never straight from `develop`, so it can only contain code that has
  actually run on a real server. Nothing deploys from it yet — production does
  not exist.

Cut a build with `--no-ff`:

```bash
git checkout preprod && git pull
git merge --no-ff develop -m "preprod: cut build $(date +%F)"
git push
```

`--no-ff` matters once `preprod` is a strict ancestor of `develop`: a plain merge
fast-forwards and leaves no commit marking which build was cut, which is what
makes "what changed between the last two builds" answerable.

All three branches are covered by a GitHub ruleset that restricts deletions and
blocks force pushes. Repository admins are on the bypass list, so a direct push
is still possible when it has to be — the guards exist to catch accidents, not to
gate you.

A **separate** ruleset (`develop CI`) requires the CI checks, and targets
`develop` only. That separation is deliberate: required status checks also apply
to direct pushes, so putting them on `preprod` or `master` would reject the
merge-and-push commands above — the commit has no checks at the moment it is
pushed.

## Release tags

Tags live on **`master` only**. Preprod builds are identified by commit SHA (see
the image tags below), because preprod moves too often for tags to mean anything.

- Annotated tags (`git tag -a`), semver `vMAJOR.MINOR.PATCH`
- **MAJOR** — an API contract break that forces the Angular app to ship
  simultaneously; **MINOR** — backward-compatible feature; **PATCH** — fix
- First release will be `v1.0.0`, matching the version already declared in
  `app/main.py`. There are no tags yet.
- Tags are immutable. A wrong tag means a new patch tag, never a moved one —
  something may already be running that version.
- Bump `version=` in `app/main.py` as part of the release commit.
  `deploy-prod.yml` asserts the tag matches it and fails the release otherwise.

## CI/CD

Three workflows in `.github/workflows/`:

- **`ci.yml`** — lint (`ruff check`, `ruff format --check`), the test suite
  against a PostgreSQL 16 service container, and a Docker image build. Runs on
  PRs into all three branches and on pushes to `develop`/`master`. `preprod` is
  absent from the push triggers on purpose: `deploy-preprod.yml` calls this
  workflow via `workflow_call`, so a push there would otherwise run the suite
  twice for one commit.
- **`deploy-preprod.yml`** — on pushes to `preprod` and via `workflow_dispatch`.
  Runs `ci.yml` first, then waits for approval on the `preprod` GitHub
  Environment, then runs `deploy/deploy-api.sh` **unchanged**. There is one
  implementation of "deploy"; the manual script stays a working escape hatch and
  cannot drift from what CI does. Concurrency queues rather than cancels —
  cancelling a deploy can leave the server mid-`docker compose up --build`.
- **`deploy-prod.yml`** — a deliberate stub with **no push trigger**. See
  Production below.

Secrets (`DENTAL_SSH_KEY`, `DENTAL_KNOWN_HOSTS`, `DENTAL_SERVER`) live on the
`preprod` *Environment*, not on the repository, so only a job that declares that
environment — and therefore passes through the approval gate — can read them.

## Pre-production (Hetzner)
- `https://preprod.api.smiletimeclinic.rs` (API) and
  `https://preprod.admin.smiletimeclinic.rs` (admin app), both A records on a
  Loopia-registered domain. The `preprod.` prefix leaves the bare `api.` /
  `admin.` names free for production. Hostnames come from `/opt/dental/.env`;
  the Angular bundle bakes its copy in at build time, so changing one is a
  server edit *and* a frontend redeploy — see [`deploy/README.md`](deploy/README.md)
- Deploys from the **`preprod`** branch, never `develop`
- Docker Compose: FastAPI behind Caddy with automatic HTTPS — see [`deploy/README.md`](deploy/README.md)
- Server config lives at `/opt/dental/.env` only; the local `.env` is never used by a deploy
- `GET /health` returns `{"status": "healthy", "env": "...", "version": "..."}` —
  `env` comes from `APP_ENV`, `version` from the FastAPI app declaration. It is
  what the deploy scripts poll, so treat its shape as a contract; a
  characterization test asserts it exactly.
- Frontend is served as static files from `/opt/dental/www`, deployed from the
  `dental-ordination` repository by its own `deploy/deploy-web.sh` and
  `deploy-preprod.yml`. That repo has the same CI/CD setup as this one: a `CI`
  workflow gating `develop`, and a `preprod` Environment holding its own copies
  of the three secrets

Deploys happen automatically on a push to `preprod`, gated by approval — see
CI/CD above. `./deploy/deploy-api.sh` still works by hand and is the escape
hatch when Actions is unavailable.

Each deploy tags its image `dental-api:<short-sha>` and the newest five are kept
on the server, so a rollback reuses an image already on disk:

```bash
export DENTAL_SERVER=deploy@<SERVER_IP>
./deploy/rollback-api.sh              # list what is available
./deploy/rollback-api.sh <short-sha>  # switch, no rebuild
```

Two limits, both intentional: rolling back does not move the server's git clone,
so the next deploy rebuilds from the branch and undoes it; and it does not touch
the database, which matters while schema changes still ride along in startup DDL.

## Production
There is no production environment yet. The Hetzner pre-prod box above is the
only deployment. Railway (API) and Vercel (frontend) were both retired — do not
add `Procfile`, `railway.json`, or Vercel config back.

`.github/workflows/deploy-prod.yml` exists as a **stub**: `workflow_dispatch`
only, taking a release tag, against an empty `production` Environment. It fails
at its secrets check rather than deploying anywhere, and it records the release
rules while they are fresh — the tag must be an ancestor of `master`, and must
match the version in `app/main.py`. Adding a push trigger is the deliberate act
of going live; do not add one as a side effect of something else.

Wiring it up needs, none of which is code: the second Hetzner box bootstrapped
(the user owns a two-server package and server 2 is reserved for this), a
separate Supabase project, a freshly generated `SECRET_KEY`, prod hostnames for
`API_HOST`/`ADMIN_HOST`/`ALLOWED_ORIGINS`/`FRONTEND_URL`, and a verified Resend
domain. The domain itself is no longer a blocker: `smiletimeclinic.rs` is
registered at Loopia and pre-prod sits under `preprod.api.` / `preprod.admin.`
precisely so production can take the bare `api.` / `admin.` names on the same
domain. One code gap too: `deploy-api.sh` resolves `origin/$BRANCH`, so it
cannot check out a tag yet — see the comment in `deploy-prod.yml`.

Still hosted by Supabase, and unaffected by that move:
- **Database** — PostgreSQL, set via `DATABASE_URL` (pooler host)
- **Storage** — patient document uploads, see `app/services/storage.py`
