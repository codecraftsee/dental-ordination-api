## Context

The app currently has no bulk data management endpoints. Admins must delete records individually or access the database directly. A dedicated `admin` router will provide hard-delete endpoints for each entity and a combined endpoint that deletes all data in safe cascade order.

## Goals / Non-Goals

**Goals:**
- Provide `DELETE /api/admin/{entity}` endpoints for visits, patients, doctors, diagnoses, treatments
- Provide `DELETE /api/admin/all` that deletes everything in FK-safe order
- Gate all endpoints behind `require_admin`
- Return counts of deleted records in the response

**Non-Goals:**
- Soft deletes or archiving
- Per-record deletion (existing individual endpoints handle that)
- Audit logging of deletions

## Decisions

**Single new router file (`app/routers/admin.py`)**
All admin bulk-delete endpoints live in one file under prefix `/admin`. Keeps the admin surface area isolated and easy to find.

**Hard delete via SQLAlchemy `db.query().delete()`**
Uses SQLAlchemy's bulk delete rather than ORM object iteration — faster for large datasets. `synchronize_session=False` is used since we don't need the session to reflect the deletions.

**Cascade order for `DELETE /api/admin/all`**
FK constraints require this order:
1. visits (references patients, doctors, diagnoses, treatments)
2. patients
3. doctors
4. diagnoses
5. treatments

**Response format**
Each endpoint returns `{ "deleted": <count> }`. The `DELETE /api/admin/all` endpoint returns counts per entity: `{ "visits": N, "patients": N, "doctors": N, "diagnoses": N, "treatments": N }`.

## Risks / Trade-offs

- [Irreversible] Hard deletes cannot be undone → Mitigation: endpoints require admin role; consider adding a confirmation mechanism in the frontend
- [FK violations on PostgreSQL] SQLAlchemy bulk delete may not cascade on PostgreSQL if FK constraints don't have `ON DELETE CASCADE` → Mitigation: delete in explicit safe order; wrap in a single transaction

## Migration Plan

No schema changes. Deploy by pushing to the target branch — Render auto-deploys.
