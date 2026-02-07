# Dental Ordination Backend - Claude Instructions

## Project Overview

Create a Python backend API for the Dental Ordination web application. The backend will provide REST API endpoints for managing patients, doctors, visits, diagnoses, treatments, and dental records with JWT authentication and role-based access control.

## Technology Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Authentication**: JWT (access + refresh tokens)
- **Password Hashing**: bcrypt via passlib
- **Migrations**: Alembic
- **Validation**: Pydantic v2
- **Testing**: pytest

## Project Location

`C:\Users\Miodrag\development\dental-ordination-api`

## Project Structure

```
dental-ordination-api/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings from environment variables
│   ├── database.py             # Database connection and session
│   ├── dependencies.py         # Dependency injection (get_db, get_current_user)
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── doctor.py
│   │   ├── visit.py
│   │   ├── diagnosis.py
│   │   └── treatment.py
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── doctor.py
│   │   ├── visit.py
│   │   ├── diagnosis.py
│   │   └── treatment.py
│   ├── routers/                # API route handlers
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── patients.py
│   │   ├── doctors.py
│   │   ├── visits.py
│   │   ├── diagnoses.py
│   │   └── treatments.py
│   └── services/               # Business logic
│       ├── __init__.py
│       ├── auth.py             # JWT token creation/validation
│       └── dental_card.py      # Dental card generation logic
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # pytest fixtures
│   └── test_auth.py
├── alembic.ini
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## User Roles

| Role | Value | Description |
|------|-------|-------------|
| ADMIN | admin | Full system access, user management, all CRUD operations |
| DOCTOR | doctor | Manage patients, create/edit visits, manage diagnoses/treatments |
| ASSISTANT | assistant | View patients, create visits under doctor supervision |
| PATIENT | patient | View own profile, own visits and dental card only |

## Database Models

### User
```python
class User(Base):
    id: UUID (primary key)
    email: str (unique, indexed)
    password_hash: str
    first_name: str
    last_name: str
    role: Enum(admin, doctor, assistant, patient)
    is_active: bool (default True)
    created_at: datetime
    updated_at: datetime
```

### Patient
```python
class Patient(Base):
    id: UUID (primary key)
    user_id: UUID (FK to users, optional - links to patient user account)
    first_name: str
    last_name: str
    parent_name: str
    gender: Enum(male, female)
    date_of_birth: date
    address: str
    city: str
    phone: str
    email: str (optional)
    created_at: datetime
    updated_at: datetime
```

### Doctor
```python
class Doctor(Base):
    id: UUID (primary key)
    user_id: UUID (FK to users, optional - links to user account)
    first_name: str
    last_name: str
    specialization: Enum(GeneralDentistry, Orthodontics, Endodontics, Periodontics, OralSurgery, PediatricDentistry, Prosthodontics)
    phone: str
    email: str
    license_number: str
    created_at: datetime
    updated_at: datetime
```

### Diagnosis
```python
class Diagnosis(Base):
    id: UUID (primary key)
    code: str (unique)
    name: str
    category: Enum(Caries, Periodontal, Pulpal, Orthodontic, TraumaticInjury, Other)
    description: str
    created_at: datetime
```

### Treatment
```python
class Treatment(Base):
    id: UUID (primary key)
    code: str (unique)
    name: str
    category: Enum(Preventive, Restorative, Endodontic, Periodontal, Surgical, Prosthetic, Orthodontic)
    description: str
    default_price: Decimal
    created_at: datetime
```

### Visit
```python
class Visit(Base):
    id: UUID (primary key)
    patient_id: UUID (FK to patients)
    doctor_id: UUID (FK to doctors)
    date: date
    tooth_number: int (nullable)
    diagnosis_id: UUID (FK to diagnoses)
    diagnosis_notes: str
    treatment_id: UUID (FK to treatments)
    treatment_notes: str
    price: Decimal
    created_at: datetime
    updated_at: datetime
```

## API Endpoints

### Authentication
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | /api/auth/login | Login, returns tokens | No |
| POST | /api/auth/refresh | Refresh access token | Refresh token |
| POST | /api/auth/logout | Invalidate refresh token | Yes |
| GET | /api/auth/me | Get current user | Yes |

### Users (Admin only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/users | List all users |
| POST | /api/users | Create user |
| GET | /api/users/{id} | Get user by ID |
| PUT | /api/users/{id} | Update user |
| DELETE | /api/users/{id} | Delete user |

### Patients
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | /api/patients | List patients (search, filter) | Admin, Doctor, Assistant |
| POST | /api/patients | Create patient | Admin, Doctor |
| GET | /api/patients/{id} | Get patient | Admin, Doctor, Assistant, Patient (own only) |
| PUT | /api/patients/{id} | Update patient | Admin, Doctor |
| DELETE | /api/patients/{id} | Delete patient | Admin |
| GET | /api/patients/{id}/dental-card | Get dental card with all visits | Admin, Doctor, Assistant, Patient (own only) |

### Doctors
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | /api/doctors | List doctors | Admin, Doctor, Assistant |
| POST | /api/doctors | Create doctor | Admin |
| GET | /api/doctors/{id} | Get doctor | Admin, Doctor, Assistant |
| PUT | /api/doctors/{id} | Update doctor | Admin |
| DELETE | /api/doctors/{id} | Delete doctor | Admin |

### Visits
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | /api/visits | List visits (filter by patient, doctor, date) | Admin, Doctor, Assistant, Patient (own only) |
| POST | /api/visits | Create visit | Admin, Doctor, Assistant |
| GET | /api/visits/{id} | Get visit | Admin, Doctor, Assistant, Patient (own only) |
| PUT | /api/visits/{id} | Update visit | Admin, Doctor |
| DELETE | /api/visits/{id} | Delete visit | Admin |

### Diagnoses
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | /api/diagnoses | List diagnosis catalog | Admin, Doctor, Assistant |
| POST | /api/diagnoses | Create diagnosis | Admin, Doctor |
| PUT | /api/diagnoses/{id} | Update diagnosis | Admin, Doctor |
| DELETE | /api/diagnoses/{id} | Delete diagnosis | Admin |

### Treatments
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | /api/treatments | List treatment catalog | Admin, Doctor, Assistant |
| POST | /api/treatments | Create treatment | Admin, Doctor |
| PUT | /api/treatments/{id} | Update treatment | Admin, Doctor |
| DELETE | /api/treatments/{id} | Delete treatment | Admin |

## Authentication Implementation

### JWT Tokens
- **Access Token**: 30 minutes expiry, contains user_id and role
- **Refresh Token**: 7 days expiry, stored in database for revocation

### Token Payload
```json
{
  "sub": "user_id",
  "role": "doctor",
  "exp": 1234567890
}
```

### Password Requirements
- Minimum 8 characters
- Hash using bcrypt

## Configuration (.env)

```
DATABASE_URL=postgresql://user:password@localhost:5432/dental_ordination
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

## CORS Configuration

Allow origins:
- http://localhost:4200 (Angular dev)
- https://codecraftsee.github.io (production)

## Response Format

### Success
```json
{
  "data": { ... },
  "message": "Success"
}
```

### Error
```json
{
  "detail": "Error message"
}
```

### Pagination
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

## Initial Setup Commands

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Initialize alembic
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial tables"

# Run migrations
alembic upgrade head

# Run development server
uvicorn app.main:app --reload --port 8000
```

## Seed Data

Create an initial admin user on first run:
- Email: admin@dental.local
- Password: admin123 (change on first login)
- Role: admin
