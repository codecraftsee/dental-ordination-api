from enum import Enum as PyEnum
from app.models.user import UserRole


class Permission(str, PyEnum):
    # Patients
    PATIENTS_READ = "patients:read"
    PATIENTS_CREATE = "patients:create"
    PATIENTS_UPDATE = "patients:update"
    PATIENTS_DELETE = "patients:delete"

    # Visits
    VISITS_READ = "visits:read"
    VISITS_CREATE = "visits:create"
    VISITS_UPDATE = "visits:update"
    VISITS_DELETE = "visits:delete"

    # Diagnoses
    DIAGNOSES_READ = "diagnoses:read"
    DIAGNOSES_CREATE = "diagnoses:create"
    DIAGNOSES_UPDATE = "diagnoses:update"
    DIAGNOSES_DELETE = "diagnoses:delete"

    # Treatments
    TREATMENTS_READ = "treatments:read"
    TREATMENTS_CREATE = "treatments:create"
    TREATMENTS_UPDATE = "treatments:update"
    TREATMENTS_DELETE = "treatments:delete"

    # Users
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"

    # Admin
    ADMIN_IMPORT = "admin:import"
    ADMIN_BULK_DELETE = "admin:bulk_delete"


# Admin gets everything
_ALL = frozenset(Permission)

# Doctor: read all, create/update patients/visits/diagnoses/treatments
_DOCTOR = frozenset({
    Permission.PATIENTS_READ,
    Permission.PATIENTS_CREATE,
    Permission.PATIENTS_UPDATE,
    Permission.VISITS_READ,
    Permission.VISITS_CREATE,
    Permission.VISITS_UPDATE,
    Permission.DIAGNOSES_READ,
    Permission.DIAGNOSES_CREATE,
    Permission.DIAGNOSES_UPDATE,
    Permission.TREATMENTS_READ,
    Permission.TREATMENTS_CREATE,
    Permission.TREATMENTS_UPDATE,
    Permission.USERS_READ,
})

# Nurse: read-only
_NURSE = frozenset({
    Permission.PATIENTS_READ,
    Permission.VISITS_READ,
    Permission.DIAGNOSES_READ,
    Permission.TREATMENTS_READ,
    Permission.USERS_READ,
})

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: _ALL,
    UserRole.DOCTOR: _DOCTOR,
    UserRole.NURSE: _NURSE,
}


def get_permissions_for_role(role: UserRole) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS.get(role, frozenset()))
