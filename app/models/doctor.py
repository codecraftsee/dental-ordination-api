import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Specialization(str, PyEnum):
    GENERAL_DENTISTRY = "GeneralDentistry"
    ORTHODONTICS = "Orthodontics"
    ENDODONTICS = "Endodontics"
    PERIODONTICS = "Periodontics"
    ORAL_SURGERY = "OralSurgery"
    PEDIATRIC_DENTISTRY = "PediatricDentistry"
    PROSTHODONTICS = "Prosthodontics"


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    specialization = Column(Enum(Specialization), nullable=False)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    license_number = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="doctor_profile")
    visits = relationship("Visit", back_populates="doctor")
