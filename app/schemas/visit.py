from datetime import date, datetime
from decimal import Decimal
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
    tooth_number: int | None = None
    diagnosis_id: UUID | None = None
    diagnosis_notes: str | None = None
    treatment_id: UUID | None = None
    treatment_notes: str | None = None
    price: Decimal | None = None
    paid: bool = True


class VisitCreate(VisitBase):
    pass


class VisitUpdate(BaseModel):
    patient_id: UUID | None = None
    doctor_id: UUID | None = None
    date: DateType | None = None
    tooth_number: int | None = None
    diagnosis_id: UUID | None = None
    diagnosis_notes: str | None = None
    treatment_id: UUID | None = None
    treatment_notes: str | None = None
    price: Decimal | None = None
    paid: bool | None = None


class DoctorBrief(BaseModel):
    id: UUID
    first_name: str | None = None
    last_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class VisitResponse(VisitBase):
    id: UUID
    import_incomplete: bool
    created_at: datetime
    updated_at: datetime
    doctor: DoctorBrief | None = None

    model_config = ConfigDict(from_attributes=True)
