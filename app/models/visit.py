import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Date, DateTime, Integer, Numeric, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.patient import ImportStatus


class Visit(Base):
    __tablename__ = "visits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(String(36), ForeignKey("doctors.id"), nullable=False)
    date = Column(Date, nullable=False)
    tooth_number = Column(Integer, nullable=True)
    diagnosis_id = Column(String(36), ForeignKey("diagnoses.id"), nullable=True)
    diagnosis_notes = Column(Text, nullable=True)
    treatment_id = Column(String(36), ForeignKey("treatments.id"), nullable=True)
    treatment_notes = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    paid = Column(Boolean, default=True, nullable=False)
    import_status = Column(Enum(ImportStatus), nullable=False, default=ImportStatus.MANUAL)
    import_warnings = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient", back_populates="visits")
    doctor = relationship("Doctor", back_populates="visits")
    diagnosis = relationship("Diagnosis")
    treatment = relationship("Treatment")
