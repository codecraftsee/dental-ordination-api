import uuid
from app.utils import utcnow
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, DateTime, Enum, Numeric
from app.database import Base


class TreatmentCategory(str, PyEnum):
    PREVENTIVE = "Preventive"
    RESTORATIVE = "Restorative"
    ENDODONTIC = "Endodontic"
    PERIODONTAL = "Periodontal"
    SURGICAL = "Surgical"
    PROSTHETIC = "Prosthetic"
    ORTHODONTIC = "Orthodontic"


class Treatment(Base):
    __tablename__ = "treatments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(Enum(TreatmentCategory), nullable=False)
    description = Column(Text, nullable=True)
    default_price = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, default=utcnow)
