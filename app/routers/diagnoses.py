from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.diagnosis import Diagnosis, DiagnosisCategory
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisUpdate, DiagnosisResponse
from app.dependencies import (
    apply_update,
    ensure_code_available,
    get_or_404,
    require_permission,
)
from app.permissions import Permission

router = APIRouter(prefix="/api/diagnoses", tags=["diagnoses"])


@router.get("", response_model=List[DiagnosisResponse])
def list_diagnoses(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.DIAGNOSES_READ))],
    category: Optional[DiagnosisCategory] = Query(None)
):
    query = db.query(Diagnosis)

    if category:
        query = query.filter(Diagnosis.category == category)

    return query.all()


@router.post("", response_model=DiagnosisResponse, status_code=status.HTTP_201_CREATED)
def create_diagnosis(
    diagnosis_data: DiagnosisCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.DIAGNOSES_CREATE))]
):
    ensure_code_available(
        db, Diagnosis, diagnosis_data.code, "Diagnosis code already exists"
    )

    diagnosis = Diagnosis(**diagnosis_data.model_dump())
    db.add(diagnosis)
    db.commit()
    db.refresh(diagnosis)
    return diagnosis


@router.get("/{diagnosis_id}", response_model=DiagnosisResponse)
def get_diagnosis(
    diagnosis_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.DIAGNOSES_READ))]
):
    return get_or_404(db, Diagnosis, diagnosis_id, "Diagnosis")


@router.put("/{diagnosis_id}", response_model=DiagnosisResponse)
def update_diagnosis(
    diagnosis_id: str,
    diagnosis_data: DiagnosisUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.DIAGNOSES_UPDATE))]
):
    diagnosis = get_or_404(db, Diagnosis, diagnosis_id, "Diagnosis")

    update_data = diagnosis_data.model_dump(exclude_unset=True)

    if "code" in update_data:
        ensure_code_available(
            db,
            Diagnosis,
            update_data["code"],
            "Diagnosis code already in use",
            exclude_id=diagnosis_id,
        )

    apply_update(diagnosis, update_data)
    db.commit()
    db.refresh(diagnosis)
    return diagnosis


@router.delete("/{diagnosis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagnosis(
    diagnosis_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.DIAGNOSES_DELETE))]
):
    diagnosis = get_or_404(db, Diagnosis, diagnosis_id, "Diagnosis")
    db.delete(diagnosis)
    db.commit()
