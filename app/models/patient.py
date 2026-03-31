import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Date, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Gender(str, PyEnum):
    MALE = "male"
    FEMALE = "female"


class ImportStatus(str, PyEnum):
    MANUAL = "manual"
    IMPORTED_OK = "imported_ok"
    IMPORTED_WITH_WARNINGS = "imported_with_warnings"


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    parent_name = Column(String(100), nullable=True)
    gender = Column(Enum(Gender), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    import_status = Column(Enum(ImportStatus), nullable=False, default=ImportStatus.MANUAL)
    import_warnings = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="patient_profile")
    visits = relationship("Visit", back_populates="patient", cascade="all, delete-orphan")
