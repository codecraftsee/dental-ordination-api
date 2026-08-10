from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Aliased purely so `VisitUpdate` can annotate its `date` field.
#
# PEP 526 makes a class-body annotated assignment bind the name *before* it
# evaluates the annotation. So inside `class VisitUpdate`, by the time
# `date: ... = None` is annotated, the bare name `date` already refers to that
# field's own default of None rather than to datetime.date. Spelled
# `Optional[date]` this resolved silently to `Optional[None]`, and the field
# rejected every real date with a 422. This alias is a name the field cannot
# shadow. Do not inline it.
DateType = date


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
    paid: bool = True


class VisitCreate(VisitBase):
    pass


class VisitUpdate(BaseModel):
    patient_id: Optional[UUID] = None
    doctor_id: Optional[UUID] = None
    date: Optional[DateType] = None
    tooth_number: Optional[int] = None
    diagnosis_id: Optional[UUID] = None
    diagnosis_notes: Optional[str] = None
    treatment_id: Optional[UUID] = None
    treatment_notes: Optional[str] = None
    price: Optional[Decimal] = None
    paid: Optional[bool] = None


class DoctorBrief(BaseModel):
    id: UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VisitResponse(VisitBase):
    id: UUID
    import_incomplete: bool
    created_at: datetime
    updated_at: datetime
    doctor: Optional[DoctorBrief] = None

    model_config = ConfigDict(from_attributes=True)
