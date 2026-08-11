import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utcnow


class PatientDocument(Base):
    __tablename__ = "patient_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(
        String(36),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(512), nullable=False, unique=True)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    description = Column(String(500), nullable=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow, nullable=False)

    patient = relationship("Patient", back_populates="documents")
    uploaded_by = relationship("User")
