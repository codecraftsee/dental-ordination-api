from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.patient import Gender


class PatientBase(BaseModel):
    first_name: str
    last_name: str
    parent_name: str | None = None
    gender: Gender
    date_of_birth: date
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class PatientCreate(PatientBase):
    user_id: UUID | None = None


class PatientUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    parent_name: str | None = None
    gender: Gender | None = None
    date_of_birth: date | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class PatientResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    parent_name: str | None = None
    gender: Gender
    date_of_birth: date
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    user_id: UUID | None = None
    import_incomplete: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
