import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers import (
    auth,
    users,
    patients,
    diagnoses,
    treatments,
    visits,
    import_xlsx,
    admin,
    patient_documents,
)
from app.database import engine, Base
from app.config import get_settings
from app.models import User
from app.models.diagnosis import Diagnosis, DiagnosisCategory
from app.models.treatment import Treatment, TreatmentCategory
from app.services.auth import get_password_hash
from app.models.user import UserRole
from sqlalchemy.orm import Session
import sqlalchemy
from sqlalchemy import inspect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # run_startup_migrations is defined further down; the name is resolved when
    # this runs, which is after the module has finished importing.
    run_startup_migrations()
    yield


app = FastAPI(
    title="Dental Ordination API",
    description="Backend API for Dental Ordination management system",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]


@app.middleware("http")
async def log_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        # Anything reaching here is an unhandled crash: FastAPI converts
        # HTTPException further in, so this is never a deliberate 4xx. The
        # exception text routinely carries the failing SQL and connection
        # details, so it is logged server-side and never returned.
        logger.exception("%s %s failed", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# CORS is registered last so it becomes the outermost middleware layer,
# ensuring Access-Control-Allow-Origin is present on all responses including errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(patients.router)
app.include_router(diagnoses.router)
app.include_router(treatments.router)
app.include_router(visits.router)
app.include_router(import_xlsx.router)
app.include_router(admin.router)
app.include_router(patient_documents.router)


def run_startup_migrations():
    """Create tables, apply the hand-rolled migrations, then seed defaults.

    PostgreSQL only — see the note in CLAUDE.md. These are one-off migrations
    that have already run everywhere; they are kept because nothing has
    replaced them yet (alembic is a dependency but is not set up).
    """
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)

    # Users table migrations
    if "users" in insp.get_table_names():
        columns = [c["name"] for c in insp.get_columns("users")]

        if "must_set_password" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        "ALTER TABLE users ADD COLUMN must_set_password BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                )

        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")
            )

        # Add profile columns directly to users (replacing staff_profiles table)
        for col_def in [
            ("first_name", "VARCHAR(100)"),
            ("last_name", "VARCHAR(100)"),
            ("phone", "VARCHAR(50)"),
            ("specialization", "VARCHAR(50)"),
            ("license_number", "VARCHAR(100)"),
        ]:
            if col_def[0] not in columns:
                with engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(f"ALTER TABLE users ADD COLUMN {col_def[0]} {col_def[1]}")
                    )

    # Migrate data from staff_profiles into users, then drop the table
    if "staff_profiles" in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                UPDATE users u
                SET first_name = sp.first_name,
                    last_name = sp.last_name,
                    phone = sp.phone,
                    specialization = sp.specialization::varchar,
                    license_number = sp.license_number
                FROM staff_profiles sp
                WHERE u.id = sp.user_id
            """)
            )
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("DROP TABLE staff_profiles"))

    # Add paid column to visits if it doesn't exist
    if "visits" in insp.get_table_names():
        columns = [c["name"] for c in insp.get_columns("visits")]
        if "paid" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        "ALTER TABLE visits ADD COLUMN paid BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                )

    # Add import_incomplete column and drop old import columns
    for table_name in ("patients", "visits"):
        if table_name in insp.get_table_names():
            columns = [c["name"] for c in insp.get_columns(table_name)]
            if "import_incomplete" not in columns:
                with engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN import_incomplete BOOLEAN NOT NULL DEFAULT FALSE"
                        )
                    )
            if "import_status" in columns:
                with engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(f"ALTER TABLE {table_name} DROP COLUMN import_status")
                    )
            if "import_warnings" in columns:
                with engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(f"ALTER TABLE {table_name} DROP COLUMN import_warnings")
                    )

    # Migrate visits.doctor_id FK from doctors table to users table, then drop doctors
    if "doctors" in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "ALTER TABLE visits DROP CONSTRAINT IF EXISTS visits_doctor_id_fkey"
                )
            )
            conn.execute(
                sqlalchemy.text(
                    "ALTER TABLE visits ADD CONSTRAINT visits_doctor_id_fkey "
                    "FOREIGN KEY (doctor_id) REFERENCES users(id)"
                )
            )
            conn.execute(sqlalchemy.text("DROP TABLE doctors"))

    # Migrate role enum values from lowercase to UPPERCASE.
    # PostgreSQL uses a native enum type, so the labels are renamed in place.
    if "users" in insp.get_table_names():
        with engine.begin() as conn:
            for old, new in [("admin", "ADMIN"), ("doctor", "DOCTOR"), ("nurse", "NURSE")]:
                # Check if the old value still exists before renaming
                result = conn.execute(
                    sqlalchemy.text(
                        "SELECT 1 FROM pg_enum WHERE enumlabel = :old "
                        "AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'userrole')"
                    ),
                    {"old": old},
                )
                if result.fetchone():
                    conn.execute(
                        sqlalchemy.text(f"ALTER TYPE userrole RENAME VALUE '{old}' TO '{new}'")
                    )

    # Seed default admin user
    with Session(engine) as db:
        admin_user = db.query(User).filter(User.email == "admin@dentalclinic.com").first()
        if not admin_user:
            db.add(
                User(
                    email="admin@dentalclinic.com",
                    password_hash=get_password_hash("Test123#"),
                    role=UserRole.ADMIN,
                    must_set_password=False,
                    first_name="Admin",
                    last_name="User",
                )
            )
            db.commit()

        # Seed diagnoses
        if db.query(Diagnosis).count() == 0:
            seed_diagnoses = [
                Diagnosis(
                    code="K02.0",
                    name="Caries superficialis",
                    category=DiagnosisCategory.CARIES,
                    description="Initial enamel caries limited to the outer enamel layer",
                ),
                Diagnosis(
                    code="K02.1",
                    name="Caries profunda",
                    category=DiagnosisCategory.CARIES,
                    description="Deep caries extending close to the dental pulp",
                ),
                Diagnosis(
                    code="K04.0",
                    name="Pulpitis",
                    category=DiagnosisCategory.PULPAL,
                    description="Inflammation of the dental pulp",
                ),
                Diagnosis(
                    code="K05.1",
                    name="Gingivitis chronica",
                    category=DiagnosisCategory.PERIODONTAL,
                    description="Chronic inflammation of the gingival tissue",
                ),
                Diagnosis(
                    code="K07.2",
                    name="Malocclusion",
                    category=DiagnosisCategory.ORTHODONTIC,
                    description="Misalignment of teeth and improper bite relationship",
                ),
                Diagnosis(
                    code="S02.5",
                    name="Fractura dentis",
                    category=DiagnosisCategory.TRAUMATIC_INJURY,
                    description="Tooth fracture due to traumatic injury",
                ),
            ]
            db.add_all(seed_diagnoses)
            db.commit()

        # Seed treatments
        if db.query(Treatment).count() == 0:
            seed_treatments = [
                Treatment(
                    code="TX-001",
                    name="Composite Filling",
                    category=TreatmentCategory.RESTORATIVE,
                    description="Tooth-colored composite resin restoration",
                    default_price=3000,
                ),
                Treatment(
                    code="TX-002",
                    name="Root Canal Treatment",
                    category=TreatmentCategory.ENDODONTIC,
                    description="Endodontic treatment to remove infected pulp tissue",
                    default_price=8000,
                ),
                Treatment(
                    code="TX-003",
                    name="Scaling and Polishing",
                    category=TreatmentCategory.PREVENTIVE,
                    description="Professional teeth cleaning and tartar removal",
                    default_price=2500,
                ),
                Treatment(
                    code="TX-004",
                    name="Tooth Extraction",
                    category=TreatmentCategory.SURGICAL,
                    description="Simple tooth extraction",
                    default_price=2000,
                ),
                Treatment(
                    code="TX-005",
                    name="Dental Crown",
                    category=TreatmentCategory.PROSTHETIC,
                    description="Porcelain or ceramic dental crown",
                    default_price=15000,
                ),
                Treatment(
                    code="TX-006",
                    name="Orthodontic Braces",
                    category=TreatmentCategory.ORTHODONTIC,
                    description="Fixed orthodontic braces for teeth alignment",
                    default_price=60000,
                ),
            ]
            db.add_all(seed_treatments)
            db.commit()


@app.get("/")
def root():
    return {"message": "Dental Ordination API", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "env": settings.app_env}
