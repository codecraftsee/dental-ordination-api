from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.diagnosis import Diagnosis
from app.models.patient import Patient
from app.models.treatment import Treatment
from app.models.user import User
from app.models.visit import Visit
from app.permissions import Permission

router = APIRouter(prefix="/api/admin", tags=["admin"])

BulkDeleteAuth = Annotated[User, Depends(require_permission(Permission.ADMIN_BULK_DELETE))]


@router.delete("/visits")
def delete_all_visits(
    db: Annotated[Session, Depends(get_db)],
    _: BulkDeleteAuth,
):
    count = db.query(Visit).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/patients")
def delete_all_patients(
    db: Annotated[Session, Depends(get_db)],
    _: BulkDeleteAuth,
):
    db.query(Visit).delete(synchronize_session=False)
    count = db.query(Patient).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/diagnoses")
def delete_all_diagnoses(
    db: Annotated[Session, Depends(get_db)],
    _: BulkDeleteAuth,
):
    # visits.diagnosis_id is a nullable FK: clear the link rather than deleting
    # the visits. Without this the delete violates the constraint and 500s as
    # soon as any visit references a diagnosis. The clinical record lives in
    # visits.diagnosis_notes, which is untouched.
    db.query(Visit).update({Visit.diagnosis_id: None}, synchronize_session=False)
    count = db.query(Diagnosis).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/treatments")
def delete_all_treatments(
    db: Annotated[Session, Depends(get_db)],
    _: BulkDeleteAuth,
):
    # Same as above: unlink rather than cascade into the visit history.
    db.query(Visit).update({Visit.treatment_id: None}, synchronize_session=False)
    count = db.query(Treatment).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


@router.delete("/all")
def delete_all_data(
    db: Annotated[Session, Depends(get_db)],
    _: BulkDeleteAuth,
):
    visits = db.query(Visit).delete(synchronize_session=False)
    patients = db.query(Patient).delete(synchronize_session=False)
    diagnoses = db.query(Diagnosis).delete(synchronize_session=False)
    treatments = db.query(Treatment).delete(synchronize_session=False)
    db.commit()
    return {
        "visits": visits,
        "patients": patients,
        "diagnoses": diagnoses,
        "treatments": treatments,
    }
