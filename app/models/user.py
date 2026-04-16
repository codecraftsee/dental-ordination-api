import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Boolean, DateTime, Enum
from app.database import Base


class UserRole(str, PyEnum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"
    NURSE = "NURSE"


class Specialization(str, PyEnum):
    GENERAL_DENTISTRY = "GeneralDentistry"
    ORTHODONTICS = "Orthodontics"
    ENDODONTICS = "Endodontics"
    PERIODONTICS = "Periodontics"
    ORAL_SURGERY = "OralSurgery"
    PEDIATRIC_DENTISTRY = "PediatricDentistry"
    PROSTHODONTICS = "Prosthodontics"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.NURSE)
    is_active = Column(Boolean, default=True)
    must_set_password = Column(Boolean, default=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    specialization = Column(String(50), nullable=True)
    license_number = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
