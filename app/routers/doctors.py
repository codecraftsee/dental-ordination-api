import logging
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.doctor import Doctor, Specialization
from app.models.visit import Visit
from app.schemas.doctor import DoctorCreate, DoctorUpdate, DoctorResponse
from app.dependencies import require_admin, require_staff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


@router.get("", response_model=List[DoctorResponse])
def list_doctors(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_staff)],
    specialization: Optional[Specialization] = Query(None)
):
    query = db.query(Doctor)

    if specialization:
        query = query.filter(Doctor.specialization == specialization)

    return query.all()


@router.post("", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
def create_doctor(
    doctor_data: DoctorCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    doctor = Doctor(**doctor_data.model_dump())
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(
    doctor_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_staff)]
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )
    return doctor


@router.put("/{doctor_id}", response_model=DoctorResponse)
def update_doctor(
    doctor_id: str,
    doctor_data: DoctorUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    update_data = doctor_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(doctor, key, value)

    db.commit()
    db.refresh(doctor)
    return doctor


@router.delete("/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_doctor(
    doctor_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )
    visit_count = db.query(Visit).filter(Visit.doctor_id == doctor_id).count()
    if visit_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete doctor with existing visits. Delete the visits first."
        )
    try:
        db.delete(doctor)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Failed to delete doctor %s", doctor_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error deleting doctor"
        ) from e
