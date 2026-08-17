import uuid
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utcnow


class Gender(str, PyEnum):
    MALE = "male"
    FEMALE = "female"


class Patient(Base):
    __tablename__ = "patients"

    # The XLSX importer looks a patient up once per file by name plus date of
    # birth. The name halves use ILIKE, which btree cannot serve, but the date
    # is a plain equality and selective enough on its own — Postgres narrows on
    # it and case-insensitively compares the handful of rows that come back.
    __table_args__ = (Index("ix_patients_date_of_birth", "date_of_birth"),)

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
    import_incomplete = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", backref="patient_profile")
    visits = relationship("Visit", back_populates="patient", cascade="all, delete-orphan")
    documents = relationship(
        "PatientDocument",
        back_populates="patient",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
