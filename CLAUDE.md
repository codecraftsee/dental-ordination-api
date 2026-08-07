# Dental Ordination API - Claude Instructions

## Tech Stack
- **Framework**: FastAPI
- **Database**: PostgreSQL everywhere — local dev, tests, and deployed. No SQLite.
- **ORM**: SQLAlchemy 2.x
- **Auth**: JWT (access + refresh tokens) via python-jose, bcrypt via passlib
- **Validation**: Pydantic v2
- **Server**: Uvicorn with --reload for dev

## Start Server
```bash
venv/Scripts/uvicorn.exe app.main:app --reload
```

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
| Role | Description |
|------|-------------|
| `admin` | Full access, user management, all CRUD |
| `doctor` | Manage patients, create/edit visits |
| `assistant` | View patients, create visits under supervision |
| `patient` | View own profile and visits only |

## API Endpoints

### Auth
- `POST /api/auth/login` — login, returns tokens
- `POST /api/auth/refresh` — refresh access token
- `POST /api/auth/logout` — invalidate refresh token
- `GET /api/auth/me` — current user

### Users (Admin only)
- `GET/POST /api/users`
- `GET/PUT/DELETE /api/users/{id}`

### Patients
- `GET/POST /api/patients`
- `GET/PUT/DELETE /api/patients/{id}`
- `GET /api/patients/{id}/dental-card`

### Doctors
- `GET/POST /api/doctors`
- `GET/PUT/DELETE /api/doctors/{id}`

### Visits
- `GET/POST /api/visits`
- `GET/PUT/DELETE /api/visits/{id}`

### Diagnoses & Treatments
- `GET/POST /api/diagnoses`, `PUT/DELETE /api/diagnoses/{id}`
- `GET/POST /api/treatments`, `PUT/DELETE /api/treatments/{id}`

### Admin Bulk Delete
- `DELETE /api/admin/visits|patients|doctors|diagnoses|treatments|all`

### Import
- `POST /api/import/xlsx` — import patient dental cards from XLSX files (admin only)
  - Accepts one or more `multipart/form-data` files (`files` field)
  - Streams **Server-Sent Events** (`text/event-stream`) instead of returning a plain JSON response
  - Event types: `progress` (before each file), `file_done` (after each file), `complete` (final summary)
  - Frontend must consume via `fetch()` + `ReadableStream` (not `EventSource`, which is GET-only)
  - Each file is committed/rolled back independently; errors appear in the event payload, not as HTTP errors

## Key Files
- `app/main.py` — app entry point, startup seeds admin + diagnoses + treatments
- `app/config.py` — settings via pydantic-settings, reads `.env`
- `app/database.py` — SQLAlchemy engine/session
- `app/dependencies.py` — auth dependencies (get_current_user, require_admin, etc.)
- `app/routers/` — one file per resource
- `app/models/` — SQLAlchemy models
- `app/schemas/` — Pydantic request/response schemas
- `app/services/auth.py` — JWT token creation/validation

## Default Admin
- Email: `admin@dentalclinic.com`
- Password: `Test123#` (seeded on first startup if the user doesn't exist — see `app/main.py:230`)

## Environment Variables (.env)
```
DATABASE_URL=postgresql://postgres:password@localhost:5432/dental_ordination
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ALLOWED_ORIGINS=http://localhost:4200
FRONTEND_URL=http://localhost:4200
```

## Known Issues & Fixes
- **passlib + bcrypt 5.x incompatibility**: pin `bcrypt<4.1` in requirements.txt
- **Vestigial SQLite support**: `app/main.py` still carries `if is_postgres: … else:`
  branches (a table-rebuild path, an enum-value update, an FK skip) from when local
  dev used SQLite. Nothing runs on SQLite any more; this code is queued for removal
  along with the startup migrations.

## CORS Allowed Origins
Driven by the `ALLOWED_ORIGINS` env var (comma-separated). The default is
`http://localhost:4200` only — a local-dev fallback.

Every deployed environment **must set `ALLOWED_ORIGINS` explicitly**; if it is
omitted the deployed frontend's requests get blocked. Deployment hostnames are
deliberately not baked into the default, so a retired host can never keep CORS
access by accident.

## Pre-production (Hetzner)
- Deploys from the **`preprod`** branch, never `develop`
- Docker Compose: FastAPI behind Caddy with automatic HTTPS — see [`deploy/README.md`](deploy/README.md)
- Server config lives at `/opt/dental/.env` only; the local `.env` is never used by a deploy
- `GET /health` returns `{"status": "healthy", "env": "..."}` — `env` comes from `APP_ENV`
- Frontend is served as static files from `/opt/dental/www`; it still needs a
  `preprod` build configuration in the Angular repo before it can be deployed

## Production
There is no separate production environment. The Hetzner box above is the only
deployment. Railway (API) and Vercel (frontend) were both retired — do not add
`Procfile`, `railway.json`, or Vercel config back.

Still hosted by Supabase, and unaffected by that move:
- **Database** — PostgreSQL, set via `DATABASE_URL` (pooler host)
- **Storage** — patient document uploads, see `app/services/storage.py`
