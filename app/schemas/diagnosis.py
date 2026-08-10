from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.diagnosis import DiagnosisCategory


class DiagnosisBase(BaseModel):
    code: str
    name: str
    category: DiagnosisCategory
    description: str | None = None


class DiagnosisCreate(DiagnosisBase):
    pass


class DiagnosisUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    category: DiagnosisCategory | None = None
    description: str | None = None


class DiagnosisResponse(DiagnosisBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
