import logging
import re
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.patient import Patient
from app.models.patient_document import PatientDocument
from app.models.user import User
from app.permissions import Permission
from app.schemas.patient_document import PatientDocumentResponse
from app.services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients/{patient_id}/documents", tags=["patient-documents"])

MAX_SIZE_BYTES = 25 * 1024 * 1024
MAX_FILENAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 500
ALLOWED_CONTENT_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
})

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_storage_name(name: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("_", name).strip("._") or "file"
    return cleaned[:200]


def _validate_upload(
    content_type: str,
    size: int,
    filename: str,
    description: Optional[str],
) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if size > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_SIZE_BYTES // (1024 * 1024)} MB limit",
        )
    if len(filename) > MAX_FILENAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Filename exceeds {MAX_FILENAME_LENGTH} characters",
        )
    if description is not None and len(description) > MAX_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters",
        )


def _to_response(doc: PatientDocument) -> PatientDocumentResponse:
    return PatientDocumentResponse(
        id=doc.id,
        patient_id=doc.patient_id,
        filename=doc.filename,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        description=doc.description,
        uploaded_by_user_id=doc.uploaded_by_user_id,
        uploaded_at=doc.uploaded_at,
        signed_url=storage.create_signed_url(doc.storage_path),
    )


def _get_patient_or_404(db: Session, patient_id: str) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return patient


@router.get("", response_model=List[PatientDocumentResponse])
def list_documents(
    patient_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENT_DOCUMENTS_READ))],
):
    _get_patient_or_404(db, patient_id)
    docs = (
        db.query(PatientDocument)
        .filter(PatientDocument.patient_id == patient_id)
        .order_by(PatientDocument.uploaded_at.desc())
        .all()
    )
    return [_to_response(d) for d in docs]


@router.post("", response_model=PatientDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    patient_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.PATIENT_DOCUMENTS_CREATE))],
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
):
    _get_patient_or_404(db, patient_id)

    content_type = (file.content_type or "").lower()
    data = await file.read()
    original_name = file.filename or "file"

    _validate_upload(content_type, len(data), original_name, description)

    storage_path = f"patients/{patient_id}/{uuid.uuid4()}_{_safe_storage_name(original_name)}"
    storage.upload_bytes(storage_path, data, content_type)

    doc = PatientDocument(
        patient_id=patient_id,
        filename=original_name,
        storage_path=storage_path,
        content_type=content_type,
        size_bytes=len(data),
        description=description,
        uploaded_by_user_id=current_user.id,
    )
    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception:
        db.rollback()
        try:
            storage.delete(storage_path)
        except Exception:
            logger.exception(
                "Failed to clean up orphaned storage object after DB failure: %s",
                storage_path,
            )
        raise

    return _to_response(doc)


@router.get("/{document_id}", response_model=PatientDocumentResponse)
def get_document(
    patient_id: str,
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENT_DOCUMENTS_READ))],
):
    _get_patient_or_404(db, patient_id)
    doc = (
        db.query(PatientDocument)
        .filter(
            PatientDocument.id == document_id,
            PatientDocument.patient_id == patient_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return _to_response(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    patient_id: str,
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENT_DOCUMENTS_DELETE))],
):
    _get_patient_or_404(db, patient_id)
    doc = (
        db.query(PatientDocument)
        .filter(
            PatientDocument.id == document_id,
            PatientDocument.patient_id == patient_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    storage.delete(doc.storage_path)
    db.delete(doc)
    db.commit()
