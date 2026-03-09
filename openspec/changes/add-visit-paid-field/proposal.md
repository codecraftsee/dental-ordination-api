## Why

The frontend needs to track whether a visit has been paid for. Currently there is no `paid` field on visits, so the UI cannot distinguish paid from unpaid visits. This blocks the "Mark as paid" feature on the visit detail page and the paid toggle on the visit form.

## What Changes

- Add a `paid` boolean column to the `visits` table, defaulting to `False`
- Expose `paid` in the Visit Pydantic schemas (create, update, response)
- Existing visits in the database will default to `paid=False` when the column is added

## Capabilities

### New Capabilities
- `visit-paid-status`: Boolean paid/unpaid tracking on visits, exposed via the existing visits REST API

### Modified Capabilities

## Impact

- **Model**: `app/models/visit.py` — new `Boolean` column
- **Schemas**: `app/schemas/visit.py` — add `paid` field to `VisitBase`, `VisitUpdate`, and `VisitResponse`
- **Database**: SQLite (dev) and PostgreSQL (prod) — new column added via SQLAlchemy `create_all`; existing rows get `False`
- **API**: `GET/POST/PUT /api/visits` responses will include `paid`; `POST` and `PUT` accept optional `paid` field
