from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_helpers import apply_update, ensure_code_available, get_or_404
from app.dependencies import require_permission
from app.models.treatment import Treatment, TreatmentCategory
from app.models.user import User
from app.permissions import Permission
from app.schemas.treatment import TreatmentCreate, TreatmentResponse, TreatmentUpdate

router = APIRouter(prefix="/api/treatments", tags=["treatments"])


@router.get("", response_model=list[TreatmentResponse])
def list_treatments(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_READ))],
    category: TreatmentCategory | None = Query(None),
):
    query = db.query(Treatment)

    if category:
        query = query.filter(Treatment.category == category)

    return query.all()


@router.post("", response_model=TreatmentResponse, status_code=status.HTTP_201_CREATED)
def create_treatment(
    treatment_data: TreatmentCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_CREATE))],
):
    ensure_code_available(db, Treatment, treatment_data.code, "Treatment code already exists")

    treatment = Treatment(**treatment_data.model_dump())
    db.add(treatment)
    db.commit()
    db.refresh(treatment)
    return treatment


@router.get("/{treatment_id}", response_model=TreatmentResponse)
def get_treatment(
    treatment_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_READ))],
):
    return get_or_404(db, Treatment, treatment_id, "Treatment")


@router.put("/{treatment_id}", response_model=TreatmentResponse)
def update_treatment(
    treatment_id: str,
    treatment_data: TreatmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_UPDATE))],
):
    treatment = get_or_404(db, Treatment, treatment_id, "Treatment")

    update_data = treatment_data.model_dump(exclude_unset=True)

    if "code" in update_data:
        ensure_code_available(
            db,
            Treatment,
            update_data["code"],
            "Treatment code already in use",
            exclude_id=treatment_id,
        )

    apply_update(treatment, update_data)
    db.commit()
    db.refresh(treatment)
    return treatment


@router.delete("/{treatment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_treatment(
    treatment_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.TREATMENTS_DELETE))],
):
    treatment = get_or_404(db, Treatment, treatment_id, "Treatment")
    db.delete(treatment)
    db.commit()
