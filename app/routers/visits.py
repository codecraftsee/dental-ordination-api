from typing import Annotated, List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, UserRole
from app.models.visit import Visit
from app.models.patient import Patient
from app.schemas.visit import VisitCreate, VisitUpdate, VisitResponse
from app.dependencies import get_current_user, require_admin, require_admin_or_doctor, require_staff

router = APIRouter(prefix="/api/visits", tags=["visits"])


@router.get("", response_model=List[VisitResponse])
def list_visits(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    patient_id: Optional[str] = Query(None),
    doctor_id: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    import_incomplete: Optional[bool] = Query(None),
):
    query = db.query(Visit)

    # Patient role can only view their own visits
    if current_user.role == UserRole.PATIENT:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient:
            return []
        query = query.filter(Visit.patient_id == patient.id)
    else:
        if patient_id:
            query = query.filter(Visit.patient_id == patient_id)

    if doctor_id:
        query = query.filter(Visit.doctor_id == doctor_id)

    if date_from:
        query = query.filter(Visit.date >= date_from)

    if date_to:
        query = query.filter(Visit.date <= date_to)

    if import_incomplete is not None:
        query = query.filter(Visit.import_incomplete == import_incomplete)

    return query.order_by(Visit.date.desc()).all()


@router.post("", response_model=VisitResponse, status_code=status.HTTP_201_CREATED)
def create_visit(
    visit_data: VisitCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_staff)]
):
    visit = Visit(**visit_data.model_dump())
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return visit


@router.get("/{visit_id}", response_model=VisitResponse)
def get_visit(
    visit_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )

    # Patient role can only view their own visits
    if current_user.role == UserRole.PATIENT:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or visit.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return visit


@router.put("/{visit_id}", response_model=VisitResponse)
def update_visit(
    visit_id: str,
    visit_data: VisitUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin_or_doctor)]
):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )

    update_data = visit_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(visit, key, value)

    db.commit()
    db.refresh(visit)
    return visit


@router.patch("/{visit_id}/dismiss-warning", response_model=VisitResponse)
def dismiss_import_warning(
    visit_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin_or_doctor)]
):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )
    visit.import_incomplete = False
    db.commit()
    db.refresh(visit)
    return visit


@router.delete("/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visit(
    visit_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )
    db.delete(visit)
    db.commit()
