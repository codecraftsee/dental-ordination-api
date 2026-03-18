import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Date, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Gender(str, PyEnum):
    MALE = "male"
    FEMALE = "female"


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="patient_profile")
    visits = relationship("Visit", back_populates="patient", cascade="all, delete-orphan")
