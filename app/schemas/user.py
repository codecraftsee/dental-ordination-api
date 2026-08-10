from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import Specialization, UserRole


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole = UserRole.NURSE
    phone: str | None = None
    specialization: Specialization | None = None
    license_number: str | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: UserRole | None = None
    phone: str | None = None
    is_active: bool | None = None
    specialization: Specialization | None = None
    license_number: str | None = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
    is_active: bool
    must_set_password: bool
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    # Deliberately `str`, not the Specialization enum, even though UserCreate and
    # UserUpdate validate against the enum. The column is a plain VARCHAR, and a
    # value outside the enum — the staff_profiles migration copied arbitrary text
    # into it — made response validation fail, which 500s the *entire* user list
    # rather than the one bad row. Input stays strict; output reports what is
    # actually stored.
    specialization: str | None = None
    license_number: str | None = None
    permissions: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def to_user_response(user, permissions: list[str] | None = None) -> UserResponse:
    """Build a UserResponse from a User row.

    `permissions` is populated only for /api/auth/me. The user-management
    endpoints deliberately leave it empty — the frontend drives its menu off the
    logged-in user's own permissions, not other people's.
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        must_set_password=user.must_set_password,
        permissions=permissions or [],
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        specialization=user.specialization,
        license_number=user.license_number,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
