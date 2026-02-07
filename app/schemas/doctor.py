from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr
from app.models.doctor import Specialization


class DoctorBase(BaseModel):
    first_name: str
    last_name: str
    specialization: Specialization
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    license_number: Optional[str] = None


class DoctorCreate(DoctorBase):
    user_id: Optional[UUID] = None


class DoctorUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    specialization: Optional[Specialization] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    license_number: Optional[str] = None


class DoctorResponse(DoctorBase):
    id: UUID
    user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
