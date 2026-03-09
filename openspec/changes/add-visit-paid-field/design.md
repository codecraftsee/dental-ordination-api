## Context

The Visit model currently tracks patient, doctor, date, tooth, diagnosis, treatment, and price. The frontend has added a "Mark as paid" toggle on the visit detail page and a paid slide toggle on the visit form, but the backend has no `paid` column to persist this state.

The app uses SQLAlchemy with `create_all` for schema management (no Alembic migrations). SQLite is used locally, PostgreSQL in production on Render.

## Goals / Non-Goals

**Goals:**
- Add a `paid` boolean field to visits with a sensible default (`False`)
- Expose it through all visit API endpoints (list, get, create, update)
- Ensure existing visits default to unpaid

**Non-Goals:**
- Payment processing or payment method tracking
- Payment history or audit trail
- Filtering visits by paid status (can be added later if needed)
- Alembic migration infrastructure

## Decisions

**1. Column type: `Boolean` with `server_default="0"` and `default=False`**

SQLAlchemy `Boolean` maps to INTEGER in SQLite and BOOLEAN in PostgreSQL. Using `server_default="0"` ensures existing rows get `False` when the column is added via `create_all` on SQLite. On PostgreSQL (Render), the column will need a one-time `ALTER TABLE` since `create_all` only adds new tables, not new columns to existing ones.

Alternative considered: Using `server_default=text("false")` — works for PostgreSQL but not SQLite. `"0"` is compatible with both.

**2. Field placement: Add `paid` to `VisitBase` with `default=False`**

Since `VisitCreate` and `VisitResponse` extend `VisitBase`, adding it there covers create and response. `VisitUpdate` gets its own `Optional[bool] = None` to allow partial updates. Default `False` means the frontend doesn't need to send `paid` on every create request.

**3. No migration tool — manual ALTER TABLE for production**

The project doesn't use Alembic. For production PostgreSQL, a one-time SQL command is needed:
```sql
ALTER TABLE visits ADD COLUMN paid BOOLEAN NOT NULL DEFAULT FALSE;
```
This is safe to run on an existing table — all rows get `False`.

## Risks / Trade-offs

**[SQLite `create_all` won't add column to existing table]** → On local dev, if the `visits` table already exists, `create_all` won't add the new column. Fix: delete `dental_ordination.db` and restart, or run `ALTER TABLE visits ADD COLUMN paid BOOLEAN DEFAULT 0;` manually.

**[Production requires manual DDL]** → Since there's no migration framework, the `ALTER TABLE` must be run manually on the Render PostgreSQL instance before deploying. If the deploy happens first, the API will error on `paid` column access. Mitigation: run the ALTER TABLE before deploying the code update.
