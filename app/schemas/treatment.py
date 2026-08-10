from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.treatment import TreatmentCategory


class TreatmentBase(BaseModel):
    code: str
    name: str
    category: TreatmentCategory
    description: Optional[str] = None
    default_price: Optional[Decimal] = None


class TreatmentCreate(TreatmentBase):
    pass


class TreatmentUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[TreatmentCategory] = None
    description: Optional[str] = None
    default_price: Optional[Decimal] = None


class TreatmentResponse(TreatmentBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
