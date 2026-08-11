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
  - Each file is committed/rolled back independently; errors appear in the event payload, not as HTTP errors

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
  NULL`, an enum rename). The dead SQLite branches are gone. Retiring the rest
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
- Deploys from the **`preprod`** branch, never `develop`
- Docker Compose: FastAPI behind Caddy with automatic HTTPS — see [`deploy/README.md`](deploy/README.md)
- Server config lives at `/opt/dental/.env` only; the local `.env` is never used by a deploy
- `GET /health` returns `{"status": "healthy", "env": "...", "version": "..."}` —
  `env` comes from `APP_ENV`, `version` from the FastAPI app declaration. It is
  what the deploy scripts poll, so treat its shape as a contract; a
  characterization test asserts it exactly.
- Frontend is served as static files from `/opt/dental/www`; it still needs a
  `preprod` build configuration in the Angular repo before it can be deployed

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
separate Supabase project, a freshly generated `SECRET_KEY`, the real domain for
`API_HOST`/`ADMIN_HOST`/`ALLOWED_ORIGINS`/`FRONTEND_URL`, and a verified Resend
domain. One code gap too: `deploy-api.sh` resolves `origin/$BRANCH`, so it
cannot check out a tag yet — see the comment in `deploy-prod.yml`.

Still hosted by Supabase, and unaffected by that move:
- **Database** — PostgreSQL, set via `DATABASE_URL` (pooler host)
- **Storage** — patient document uploads, see `app/services/storage.py`
