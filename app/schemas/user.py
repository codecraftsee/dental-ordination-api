from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import Specialization, UserRole


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole = UserRole.NURSE
    phone: Optional[str] = None
    specialization: Optional[Specialization] = None
    license_number: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[UserRole] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    specialization: Optional[Specialization] = None
    license_number: Optional[str] = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
    is_active: bool
    must_set_password: bool
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    # Deliberately `str`, not the Specialization enum, even though UserCreate and
    # UserUpdate validate against the enum. The column is a plain VARCHAR, and a
    # value outside the enum — the staff_profiles migration copied arbitrary text
    # into it — made response validation fail, which 500s the *entire* user list
    # rather than the one bad row. Input stays strict; output reports what is
    # actually stored.
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    permissions: List[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def to_user_response(user, permissions: Optional[List[str]] = None) -> UserResponse:
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
