from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.treatment import TreatmentCategory


class TreatmentBase(BaseModel):
    code: str
    name: str
    category: TreatmentCategory
    description: str | None = None
    default_price: Decimal | None = None


class TreatmentCreate(TreatmentBase):
    pass


class TreatmentUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    category: TreatmentCategory | None = None
    description: str | None = None
    default_price: Decimal | None = None


class TreatmentResponse(TreatmentBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
