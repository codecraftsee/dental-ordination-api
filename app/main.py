import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers import auth, users, patients, doctors, diagnoses, treatments, visits, import_xlsx, admin
from app.database import engine, Base
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

app = FastAPI(
    title="Dental Ordination API",
    description="Backend API for Dental Ordination management system",
    version="1.0.0"
)


@app.middleware("http")
async def log_exceptions(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.error(f"{request.method} {request.url.path} failed: {exc}")
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=500, content={"detail": str(exc)})

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://codecraftsee.github.io",
        "https://dental-ordination-api.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(diagnoses.router)
app.include_router(treatments.router)
app.include_router(visits.router)
app.include_router(import_xlsx.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup():
    # Create tables
    Base.metadata.create_all(bind=engine)

    # Add 'paid' column to visits if it doesn't exist (no Alembic)
    insp = inspect(engine)
    if "visits" in insp.get_table_names():
        columns = [c["name"] for c in insp.get_columns("visits")]
        if "paid" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text("ALTER TABLE visits ADD COLUMN paid BOOLEAN NOT NULL DEFAULT FALSE")
                )

    # Add import_incomplete column and drop old import_status/import_warnings columns
    for table_name in ("patients", "visits"):
        if table_name in insp.get_table_names():
            columns = [c["name"] for c in insp.get_columns(table_name)]
            if "import_incomplete" not in columns:
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN import_incomplete BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
            if "import_status" in columns:
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f"ALTER TABLE {table_name} DROP COLUMN import_status"
                    ))
            if "import_warnings" in columns:
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f"ALTER TABLE {table_name} DROP COLUMN import_warnings"
                    ))

    # Create default admin user if not exists
    with Session(engine) as db:
        admin = db.query(User).filter(User.email == "admin@dentalclinic.com").first()
        if not admin:
            admin = User(
                email="admin@dentalclinic.com",
                password_hash=get_password_hash("p5zTCyUJ^B#^Juvy^%bj"),
                first_name="Admin",
                last_name="User",
                role=UserRole.ADMIN
            )
            db.add(admin)
            db.commit()

        # Seed diagnoses
        if db.query(Diagnosis).count() == 0:
            seed_diagnoses = [
                Diagnosis(code="K02.0", name="Caries superficialis", category=DiagnosisCategory.CARIES, description="Initial enamel caries limited to the outer enamel layer"),
                Diagnosis(code="K02.1", name="Caries profunda", category=DiagnosisCategory.CARIES, description="Deep caries extending close to the dental pulp"),
                Diagnosis(code="K04.0", name="Pulpitis", category=DiagnosisCategory.PULPAL, description="Inflammation of the dental pulp"),
                Diagnosis(code="K05.1", name="Gingivitis chronica", category=DiagnosisCategory.PERIODONTAL, description="Chronic inflammation of the gingival tissue"),
                Diagnosis(code="K07.2", name="Malocclusion", category=DiagnosisCategory.ORTHODONTIC, description="Misalignment of teeth and improper bite relationship"),
                Diagnosis(code="S02.5", name="Fractura dentis", category=DiagnosisCategory.TRAUMATIC_INJURY, description="Tooth fracture due to traumatic injury"),
            ]
            db.add_all(seed_diagnoses)
            db.commit()

        # Seed treatments
        if db.query(Treatment).count() == 0:
            seed_treatments = [
                Treatment(code="TX-001", name="Composite Filling", category=TreatmentCategory.RESTORATIVE, description="Tooth-colored composite resin restoration", default_price=3000),
                Treatment(code="TX-002", name="Root Canal Treatment", category=TreatmentCategory.ENDODONTIC, description="Endodontic treatment to remove infected pulp tissue", default_price=8000),
                Treatment(code="TX-003", name="Scaling and Polishing", category=TreatmentCategory.PREVENTIVE, description="Professional teeth cleaning and tartar removal", default_price=2500),
                Treatment(code="TX-004", name="Tooth Extraction", category=TreatmentCategory.SURGICAL, description="Simple tooth extraction", default_price=2000),
                Treatment(code="TX-005", name="Dental Crown", category=TreatmentCategory.PROSTHETIC, description="Porcelain or ceramic dental crown", default_price=15000),
                Treatment(code="TX-006", name="Orthodontic Braces", category=TreatmentCategory.ORTHODONTIC, description="Fixed orthodontic braces for teeth alignment", default_price=60000),
            ]
            db.add_all(seed_treatments)
            db.commit()


@app.get("/")
def root():
    return {"message": "Dental Ordination API", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
