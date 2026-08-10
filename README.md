# Dental Ordination API

FastAPI backend for the Dental Ordination clinic management system.

PostgreSQL everywhere — local development, tests and deployment. There is no
SQLite anywhere in this project.

## Setup

### 1. Virtual environment

```bash
python -m venv venv
source venv/bin/activate          # macOS / Linux
venv\Scripts\activate             # Windows
```

Python 3.12 — see `.python-version`.

### 2. Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configuration

```bash
cp .env.example .env
```

`SECRET_KEY` is the one that matters. Any environment where `APP_ENV` is not
`local` refuses to start unless it is set to something other than the built-in
default — a deployed instance signing tokens with a key that is public in this
repository would let anyone forge an admin token. Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 4. Database

```sql
CREATE DATABASE dental_ordination;
```

Tables and seed data are created automatically on first start.

### 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

- API — <http://localhost:8000>
- Swagger — <http://localhost:8000/docs>
- ReDoc — <http://localhost:8000/redoc>
- Health — <http://localhost:8000/health>

A default admin is seeded on first start. The credentials are in `CLAUDE.md`;
change the password immediately on any deployed environment.

## Tests

The suite runs against a real PostgreSQL instance, never SQLite, so it exercises
the same engine as production.

```bash
docker compose -f docker-compose.test.yml up -d    # test db on port 55432
pytest
docker compose -f docker-compose.test.yml down -v  # when finished
```

Each session drops and recreates the `public` schema, so `create_all()` and the
startup migrations run from scratch. A guard refuses to run unless the database
name contains `test`.

## Linting and formatting

```bash
ruff check app tests        # lint
ruff check app tests --fix  # apply the automatic fixes
ruff format app tests       # format
```

Configuration is in `pyproject.toml`.

## Patient data

Never commit real patient records. `/specs/` is gitignored for this reason — it
previously held real dental cards, and those files remain in git history.
Anything with a real name, date of birth, address or phone number belongs
outside this repository.

## Further documentation

This file covers getting the project running. Detail lives in one place each,
so it cannot drift:

| Topic | Where |
|---|---|
| Architecture, roles and permissions, every endpoint, key files | [`CLAUDE.md`](CLAUDE.md) |
| Pre-production deployment on Hetzner | [`deploy/README.md`](deploy/README.md) |
| Feature specifications and change proposals | [`openspec/`](openspec/) |
