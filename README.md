# Dental Ordination API

Python backend API for the Dental Ordination web application.

## Technology Stack

- FastAPI
- PostgreSQL + SQLAlchemy
- JWT Authentication
- Alembic migrations

## Setup

### 1. Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Copy `.env.example` to `.env` and update the values:

```bash
cp .env.example .env
```

### 4. Create PostgreSQL database

```sql
CREATE DATABASE dental_ordination;
```

### 5. Run the application

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

- Swagger docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Default Admin User

On first run, a default admin user is created:

- Email: `admin@dental.local`
- Password: `admin123`

**Change this password immediately in production!**

## User Roles

| Role | Description |
|------|-------------|
| admin | Full system access |
| doctor | Manage patients, visits, diagnoses, treatments |
| assistant | View patients, create visits |
| patient | View own profile and visits only |

## API Endpoints

- `POST /api/auth/login` - Login
- `POST /api/auth/refresh` - Refresh token
- `GET /api/auth/me` - Current user

- `GET/POST /api/users` - List/Create users (admin)
- `GET/PUT/DELETE /api/users/{id}` - User operations (admin)

- `GET/POST /api/patients` - List/Create patients
- `GET/PUT/DELETE /api/patients/{id}` - Patient operations

- `GET/POST /api/doctors` - List/Create doctors
- `GET/PUT/DELETE /api/doctors/{id}` - Doctor operations

- `GET/POST /api/visits` - List/Create visits
- `GET/PUT/DELETE /api/visits/{id}` - Visit operations

- `GET/POST /api/diagnoses` - List/Create diagnoses
- `GET/PUT/DELETE /api/diagnoses/{id}` - Diagnosis operations

- `GET/POST /api/treatments` - List/Create treatments
- `GET/PUT/DELETE /api/treatments/{id}` - Treatment operations
