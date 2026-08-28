import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utcnow


class Visit(Base):
    __tablename__ = "visits"

    # The XLSX importer checks every row against the existing visits for that
    # patient before inserting (app/routers/import_xlsx.py). Without this the
    # check sequentially scans the whole table once per imported row, so the
    # cost of an import grows with the square of the visits already stored.
    #
    # diagnosis_notes/treatment_notes are deliberately not part of the index
    # even though the query filters on them: they are Text, and btree rejects
    # entries over ~2704 bytes, which would turn a long note into a failed
    # INSERT. Narrowing to one patient-day leaves few enough rows that
    # comparing the notes directly costs nothing.
    __table_args__ = (Index("ix_visits_patient_id_date", "patient_id", "date"),)

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

    # What the imported card's "Dr" cell actually said, kept verbatim.
    #
    # `doctor_id` is NOT NULL, so a card naming somebody the system cannot
    # identify still has to be attributed to *a* user — and that attribution is
    # a stand-in, which is what `import_incomplete` above marks. Without this
    # column the one true fact in that record, the letter the chart was written
    # with, is discarded at parse time: a flagged visit can then only be
    # dismissed, never resolved, because nothing remembers who was claimed.
    #
    # Nullable because every visit that predates the import, and every visit
    # created by hand in the UI, genuinely has no source document to quote.
    # 100 matches `users.first_name`, so a card carrying a full name rather than
    # a single initial still fits.
    imported_doctor_label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    patient = relationship("Patient", back_populates="visits")
    doctor = relationship("User", backref="visits")
    diagnosis = relationship("Diagnosis")
    treatment = relationship("Treatment")
