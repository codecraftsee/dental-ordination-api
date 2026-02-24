## 1. Router Setup

- [x] 1.1 Create `app/routers/admin.py` with `APIRouter(prefix="/admin", tags=["admin"])`
- [x] 1.2 Register the admin router in `app/main.py`

## 2. Delete Endpoints

- [x] 2.1 Implement `DELETE /admin/visits` — bulk delete all visits, return `{ "deleted": count }`
- [x] 2.2 Implement `DELETE /admin/patients` — bulk delete all patients (visits cascade), return `{ "deleted": count }`
- [x] 2.3 Implement `DELETE /admin/doctors` — bulk delete all doctors, return `{ "deleted": count }`
- [x] 2.4 Implement `DELETE /admin/diagnoses` — bulk delete all diagnoses, return `{ "deleted": count }`
- [x] 2.5 Implement `DELETE /admin/treatments` — bulk delete all treatments, return `{ "deleted": count }`

## 3. Delete All Endpoint

- [x] 3.1 Implement `DELETE /admin/all` — delete in cascade order: visits → patients → doctors → diagnoses → treatments
- [x] 3.2 Wrap `DELETE /admin/all` in a single transaction with rollback on error
- [x] 3.3 Return per-entity counts: `{ "visits": N, "patients": N, "doctors": N, "diagnoses": N, "treatments": N }`

## 4. Auth & Validation

- [x] 4.1 Gate all endpoints with `require_admin` dependency
- [x] 4.2 Verify `401`/`403` is returned for unauthenticated/non-admin requests
