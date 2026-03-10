from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class VisitBase(BaseModel):
    patient_id: UUID
    doctor_id: UUID
    date: date
    tooth_number: Optional[int] = None
    diagnosis_id: Optional[UUID] = None
    diagnosis_notes: Optional[str] = None
    treatment_id: Optional[UUID] = None
    treatment_notes: Optional[str] = None
    price: Optional[Decimal] = None
    paid: bool = False


class VisitCreate(VisitBase):
    pass


class VisitUpdate(BaseModel):
    patient_id: Optional[UUID] = None
    doctor_id: Optional[UUID] = None
    date: Optional[date] = None
    tooth_number: Optional[int] = None
    diagnosis_id: Optional[UUID] = None
    diagnosis_notes: Optional[str] = None
    treatment_id: Optional[UUID] = None
    treatment_notes: Optional[str] = None
    price: Optional[Decimal] = None
    paid: Optional[bool] = None


class VisitResponse(VisitBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
