import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Date, DateTime, Integer, Numeric, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Visit(Base):
    __tablename__ = "visits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    tooth_number = Column(Integer, nullable=True)
    diagnosis_id = Column(String(36), ForeignKey("diagnoses.id"), nullable=True)
    diagnosis_notes = Column(Text, nullable=True)
    treatment_id = Column(String(36), ForeignKey("treatments.id"), nullable=True)
    treatment_notes = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    paid = Column(Boolean, default=True, nullable=False)
    import_incomplete = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient", back_populates="visits")
    doctor = relationship("User", backref="visits")
    diagnosis = relationship("Diagnosis")
    treatment = relationship("Treatment")
