## Why

Admins need the ability to reset data in bulk — especially useful during development, testing, and onboarding — without manually deleting records one by one or directly accessing the database.

## What Changes

- Add a new `admin` router with hard-delete endpoints for each major entity
- All endpoints require admin role
- Deletion follows correct cascade order to avoid FK constraint violations

## Capabilities

### New Capabilities
- `admin-bulk-delete`: Hard-delete endpoints for visits, patients, doctors, diagnoses, treatments, and all data at once via `DELETE /api/admin/*`

### Modified Capabilities
<!-- none -->

## Impact

- **New file**: `app/routers/admin.py`
- **Modified**: `app/main.py` — register the new admin router
- **Database**: Destructive operations; no migrations needed (no schema changes)
- **Auth**: All endpoints gated behind `require_admin` dependency
- **Cascade order for `DELETE /api/admin/all`**: visits → patients → doctors → diagnoses → treatments
