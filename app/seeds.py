"""Default rows created on first startup.

Split out of `app/main.py`, where the seeding sat at the bottom of
`run_startup_migrations()` and made one function responsible for DDL, data
migration and reference data at once.

Every seed is guarded: the admin is created only when no row with that email
exists, and the catalogues only when their table is completely empty. So this
runs on every boot and is a no-op after the first.
"""

from sqlalchemy.orm import Session

from app.models.diagnosis import Diagnosis, DiagnosisCategory
from app.models.treatment import Treatment, TreatmentCategory
from app.models.user import User, UserRole
from app.services.auth import get_password_hash

DEFAULT_ADMIN_EMAIL = "admin@dentalclinic.com"
DEFAULT_ADMIN_PASSWORD = "Test123#"

DIAGNOSES = [
    {
        "code": "K02.0",
        "name": "Caries superficialis",
        "category": DiagnosisCategory.CARIES,
        "description": "Initial enamel caries limited to the outer enamel layer",
    },
    {
        "code": "K02.1",
        "name": "Caries profunda",
        "category": DiagnosisCategory.CARIES,
        "description": "Deep caries extending close to the dental pulp",
    },
    {
        "code": "K04.0",
        "name": "Pulpitis",
        "category": DiagnosisCategory.PULPAL,
        "description": "Inflammation of the dental pulp",
    },
    {
        "code": "K05.1",
        "name": "Gingivitis chronica",
        "category": DiagnosisCategory.PERIODONTAL,
        "description": "Chronic inflammation of the gingival tissue",
    },
    {
        "code": "K07.2",
        "name": "Malocclusion",
        "category": DiagnosisCategory.ORTHODONTIC,
        "description": "Misalignment of teeth and improper bite relationship",
    },
    {
        "code": "S02.5",
        "name": "Fractura dentis",
        "category": DiagnosisCategory.TRAUMATIC_INJURY,
        "description": "Tooth fracture due to traumatic injury",
    },
]

TREATMENTS = [
    {
        "code": "TX-001",
        "name": "Composite Filling",
        "category": TreatmentCategory.RESTORATIVE,
        "description": "Tooth-colored composite resin restoration",
        "default_price": 3000,
    },
    {
        "code": "TX-002",
        "name": "Root Canal Treatment",
        "category": TreatmentCategory.ENDODONTIC,
        "description": "Endodontic treatment to remove infected pulp tissue",
        "default_price": 8000,
    },
    {
        "code": "TX-003",
        "name": "Scaling and Polishing",
        "category": TreatmentCategory.PREVENTIVE,
        "description": "Professional teeth cleaning and tartar removal",
        "default_price": 2500,
    },
    {
        "code": "TX-004",
        "name": "Tooth Extraction",
        "category": TreatmentCategory.SURGICAL,
        "description": "Simple tooth extraction",
        "default_price": 2000,
    },
    {
        "code": "TX-005",
        "name": "Dental Crown",
        "category": TreatmentCategory.PROSTHETIC,
        "description": "Porcelain or ceramic dental crown",
        "default_price": 15000,
    },
    {
        "code": "TX-006",
        "name": "Orthodontic Braces",
        "category": TreatmentCategory.ORTHODONTIC,
        "description": "Fixed orthodontic braces for teeth alignment",
        "default_price": 60000,
    },
]


def seed_defaults(engine) -> None:
    """Create the default admin and the diagnosis/treatment catalogues."""
    with Session(engine) as db:
        _seed_admin(db)
        _seed_catalogue(db, Diagnosis, DIAGNOSES)
        _seed_catalogue(db, Treatment, TREATMENTS)


def _seed_admin(db: Session) -> None:
    """Create the default admin if no user holds that email.

    Deliberately keyed on the email rather than "are there any admins", which is
    also why deleting the last admin is blocked in the users router: this would
    not recreate one.
    """
    if db.query(User).filter(User.email == DEFAULT_ADMIN_EMAIL).first():
        return
    db.add(
        User(
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=get_password_hash(DEFAULT_ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            must_set_password=False,
            first_name="Admin",
            last_name="User",
        )
    )
    db.commit()


def _seed_catalogue(db: Session, model, rows: list[dict]) -> None:
    """Populate a reference table, but only while it is completely empty.

    All-or-nothing on purpose: filling in individual missing rows would fight
    with an admin who deliberately deleted one.
    """
    if db.query(model).count() != 0:
        return
    db.add_all([model(**row) for row in rows])
    db.commit()
