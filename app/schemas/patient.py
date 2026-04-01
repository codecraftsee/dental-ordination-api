from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr
from app.models.patient import Gender


class PatientBase(BaseModel):
    first_name: str
    last_name: str
    parent_name: Optional[str] = None
    gender: Gender
    date_of_birth: date
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None


class PatientCreate(PatientBase):
    user_id: Optional[UUID] = None


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    parent_name: Optional[str] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[date] = None
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None


class PatientResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    parent_name: Optional[str] = None
    gender: Gender
    date_of_birth: date
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    user_id: Optional[UUID] = None
    import_incomplete: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
