# Dental Ordination API - Claude Instructions

## Tech Stack
- **Framework**: FastAPI
- **Database**: PostgreSQL (prod) / SQLite (local dev)
- **ORM**: SQLAlchemy 2.x
- **Auth**: JWT (access + refresh tokens) via python-jose, bcrypt via passlib
- **Validation**: Pydantic v2
- **Server**: Uvicorn with --reload for dev

## Start Server
```bash
venv/Scripts/uvicorn.exe app.main:app --reload
```

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
- Password: `p5zTCyUJ^B#^Juvy^%bj` (seeded on first startup if user doesn't exist)

## Environment Variables (.env)
```
DATABASE_URL=sqlite:///./dental_ordination.db
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ALLOWED_ORIGINS=http://localhost:4200,https://codecraftsee.github.io
FRONTEND_URL=http://localhost:4200
```

## Known Issues & Fixes
- **passlib + bcrypt 5.x incompatibility**: pin `bcrypt<4.1` in requirements.txt
- **SQLite local / PostgreSQL prod**: `DATABASE_URL` in `.env` controls which is used

## CORS Allowed Origins
Driven by `ALLOWED_ORIGINS` env var (comma-separated). Defaults:
- `http://localhost:4200`
- `https://codecraftsee.github.io`

## Production (Railway + Supabase)
- **API**: Railway (free tier) — auto-deploys from `develop` branch
- **Database**: Supabase PostgreSQL (free tier) — connection string set via `DATABASE_URL` env var
- **Frontend**: Vercel (free) — Angular static site
- **Procfile**: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Railway env vars: `DATABASE_URL`, `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `ALLOWED_ORIGINS`, `FRONTEND_URL`
