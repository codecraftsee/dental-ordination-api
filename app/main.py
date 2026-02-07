from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, users, patients, doctors, diagnoses, treatments, visits
from app.database import engine, Base
from app.models import User
from app.services.auth import get_password_hash
from app.models.user import UserRole
from sqlalchemy.orm import Session

app = FastAPI(
    title="Dental Ordination API",
    description="Backend API for Dental Ordination management system",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://codecraftsee.github.io"
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


@app.on_event("startup")
def on_startup():
    # Create tables
    Base.metadata.create_all(bind=engine)

    # Create default admin user if not exists
    with Session(engine) as db:
        admin = db.query(User).filter(User.email == "admin@dental.local").first()
        if not admin:
            admin = User(
                email="admin@dental.local",
                password_hash=get_password_hash("admin123"),
                first_name="Admin",
                last_name="User",
                role=UserRole.ADMIN
            )
            db.add(admin)
            db.commit()


@app.get("/")
def root():
    return {"message": "Dental Ordination API", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
