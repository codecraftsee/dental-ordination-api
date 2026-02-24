from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models.user import User
from app.models.visit import Visit
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.diagnosis import Diagnosis
from app.models.treatment import Treatment

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.delete("/visits")
def delete_all_visits(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    count = db.query(Visit).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/patients")
def delete_all_patients(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    db.query(Visit).delete(synchronize_session=False)
    count = db.query(Patient).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/doctors")
def delete_all_doctors(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    count = db.query(Doctor).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/diagnoses")
def delete_all_diagnoses(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    count = db.query(Diagnosis).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/treatments")
def delete_all_treatments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    count = db.query(Treatment).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/all")
def delete_all_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        visits = db.query(Visit).delete(synchronize_session=False)
        patients = db.query(Patient).delete(synchronize_session=False)
        doctors = db.query(Doctor).delete(synchronize_session=False)
        diagnoses = db.query(Diagnosis).delete(synchronize_session=False)
        treatments = db.query(Treatment).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "visits": visits,
        "patients": patients,
        "doctors": doctors,
        "diagnoses": diagnoses,
        "treatments": treatments,
    }
