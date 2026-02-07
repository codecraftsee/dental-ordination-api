from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
from app.models.diagnosis import DiagnosisCategory


class DiagnosisBase(BaseModel):
    code: str
    name: str
    category: DiagnosisCategory
    description: Optional[str] = None


class DiagnosisCreate(DiagnosisBase):
    pass


class DiagnosisUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[DiagnosisCategory] = None
    description: Optional[str] = None


class DiagnosisResponse(DiagnosisBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
