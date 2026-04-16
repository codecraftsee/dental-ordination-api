from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.treatment import Treatment, TreatmentCategory
from app.schemas.treatment import TreatmentCreate, TreatmentUpdate, TreatmentResponse
from app.dependencies import require_permission
from app.permissions import Permission

router = APIRouter(prefix="/api/treatments", tags=["treatments"])


@router.get("", response_model=List[TreatmentResponse])
def list_treatments(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_READ))],
    category: Optional[TreatmentCategory] = Query(None)
):
    query = db.query(Treatment)

    if category:
        query = query.filter(Treatment.category == category)

    return query.all()


@router.post("", response_model=TreatmentResponse, status_code=status.HTTP_201_CREATED)
def create_treatment(
    treatment_data: TreatmentCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_CREATE))]
):
    existing = db.query(Treatment).filter(Treatment.code == treatment_data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Treatment code already exists"
        )

    treatment = Treatment(**treatment_data.model_dump())
    db.add(treatment)
    db.commit()
    db.refresh(treatment)
    return treatment


@router.get("/{treatment_id}", response_model=TreatmentResponse)
def get_treatment(
    treatment_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_READ))]
):
    treatment = db.query(Treatment).filter(Treatment.id == treatment_id).first()
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Treatment not found"
        )
    return treatment


@router.put("/{treatment_id}", response_model=TreatmentResponse)
def update_treatment(
    treatment_id: str,
    treatment_data: TreatmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_UPDATE))]
):
    treatment = db.query(Treatment).filter(Treatment.id == treatment_id).first()
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Treatment not found"
        )

    update_data = treatment_data.model_dump(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(Treatment).filter(
            Treatment.code == update_data["code"],
            Treatment.id != treatment_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Treatment code already in use"
            )

    for key, value in update_data.items():
        setattr(treatment, key, value)

    db.commit()
    db.refresh(treatment)
    return treatment


@router.delete("/{treatment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_treatment(
    treatment_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_DELETE))]
):
    treatment = db.query(Treatment).filter(Treatment.id == treatment_id).first()
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Treatment not found"
        )
    db.delete(treatment)
    db.commit()
