import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Date, DateTime, Integer, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Visit(Base):
    __tablename__ = "visits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=False)
    date = Column(Date, nullable=False)
    tooth_number = Column(Integer, nullable=True)
    diagnosis_id = Column(UUID(as_uuid=True), ForeignKey("diagnoses.id"), nullable=True)
    diagnosis_notes = Column(Text, nullable=True)
    treatment_id = Column(UUID(as_uuid=True), ForeignKey("treatments.id"), nullable=True)
    treatment_notes = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient", back_populates="visits")
    doctor = relationship("Doctor", back_populates="visits")
    diagnosis = relationship("Diagnosis")
    treatment = relationship("Treatment")
