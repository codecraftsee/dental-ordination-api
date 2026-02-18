from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.diagnosis import Diagnosis, DiagnosisCategory
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisUpdate, DiagnosisResponse
from app.dependencies import require_admin, require_admin_or_doctor, require_staff

router = APIRouter(prefix="/api/diagnoses", tags=["diagnoses"])


@router.get("", response_model=List[DiagnosisResponse])
def list_diagnoses(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_staff)],
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
    _: Annotated[User, Depends(require_admin_or_doctor)]
):
    existing = db.query(Diagnosis).filter(Diagnosis.code == diagnosis_data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diagnosis code already exists"
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
    _: Annotated[User, Depends(require_staff)]
):
    diagnosis = db.query(Diagnosis).filter(Diagnosis.id == diagnosis_id).first()
    if not diagnosis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnosis not found"
        )
    return diagnosis


@router.put("/{diagnosis_id}", response_model=DiagnosisResponse)
def update_diagnosis(
    diagnosis_id: str,
    diagnosis_data: DiagnosisUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin_or_doctor)]
):
    diagnosis = db.query(Diagnosis).filter(Diagnosis.id == diagnosis_id).first()
    if not diagnosis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnosis not found"
        )

    update_data = diagnosis_data.model_dump(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(Diagnosis).filter(
            Diagnosis.code == update_data["code"],
            Diagnosis.id != diagnosis_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Diagnosis code already in use"
            )

    for key, value in update_data.items():
        setattr(diagnosis, key, value)

    db.commit()
    db.refresh(diagnosis)
    return diagnosis


@router.delete("/{diagnosis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagnosis(
    diagnosis_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    diagnosis = db.query(Diagnosis).filter(Diagnosis.id == diagnosis_id).first()
    if not diagnosis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnosis not found"
        )
    db.delete(diagnosis)
    db.commit()
