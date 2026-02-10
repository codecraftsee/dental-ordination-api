import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, DateTime, Enum
from app.database import Base


class DiagnosisCategory(str, PyEnum):
    CARIES = "Caries"
    PERIODONTAL = "Periodontal"
    PULPAL = "Pulpal"
    ORTHODONTIC = "Orthodontic"
    TRAUMATIC_INJURY = "TraumaticInjury"
    OTHER = "Other"


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(Enum(DiagnosisCategory), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
