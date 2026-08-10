from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import apply_update, get_or_404, require_permission
from app.models.patient import Patient
from app.models.user import User
from app.permissions import Permission
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("", response_model=List[PatientResponse])
def list_patients(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_READ))],
    search: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    import_incomplete: Optional[bool] = Query(None),
):
    query = db.query(Patient)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Patient.first_name.ilike(search_term))
            | (Patient.last_name.ilike(search_term))
            | (Patient.phone.ilike(search_term))
        )

    if city:
        query = query.filter(Patient.city == city)

    if import_incomplete is not None:
        query = query.filter(Patient.import_incomplete == import_incomplete)

    return query.all()


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
def create_patient(
    patient_data: PatientCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_CREATE))],
):
    patient = Patient(**patient_data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_READ))],
):
    return get_or_404(db, Patient, patient_id, "Patient")


@router.put("/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: str,
    patient_data: PatientUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_UPDATE))],
):
    patient = get_or_404(db, Patient, patient_id, "Patient")
    apply_update(patient, patient_data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(patient)
    return patient


@router.patch("/{patient_id}/dismiss-warning", response_model=PatientResponse)
def dismiss_import_warning(
    patient_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_UPDATE))],
):
    patient = get_or_404(db, Patient, patient_id, "Patient")
    patient.import_incomplete = False
    db.commit()
    db.refresh(patient)
    return patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient(
    patient_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.PATIENTS_DELETE))],
):
    patient = get_or_404(db, Patient, patient_id, "Patient")
    db.delete(patient)
    db.commit()
