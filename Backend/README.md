# Estimaro Backend

Professional auto repair estimation system built with FastAPI.

## Setup Instructions

### 1. Install Dependencies
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
# Copy .env.example to .env
copy .env.example .env

# Edit .env and set your configuration
# Especially generate a secure SECRET_KEY
```

### 3. Start Database (Docker)
```bash
# Start PostgreSQL and pgAdmin
docker-compose up -d

# Check status
docker-compose ps
```

### 4. Run Database Migrations
```bash
# Create initial migration
alembic revision --autogenerate -m "Initial schema"

# Apply migrations
alembic upgrade head
```

### 5. Run Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Access API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- pgAdmin: http://localhost:5050 (admin@estimaro.com / admin123)

## Project Structure
```
Backend/
├── app/
│   ├── core/           # Configuration, database, security
│   ├── models/         # SQLAlchemy models
│   ├── schemas/        # Pydantic schemas
│   ├── services/       # Business logic
│   ├── repositories/   # Data access layer
│   ├── adapters/       # External API adapters
│   ├── api/
│   │   └── v1/         # API routes
│   └── main.py         # FastAPI application
├── alembic/            # Database migrations
├── requirements.txt
├── docker-compose.yml
└── .env
```

## Tech Stack
- **Framework**: FastAPI 0.104.1
- **Database**: PostgreSQL 15 + SQLAlchemy 2.0.45
- **Validation**: Pydantic 2.10.4
- **Auth**: JWT (python-jose)
- **Migrations**: Alembic
- **Testing**: pytest

## Development Status
✅ Phase 1: Foundation & Database Setup (Complete)
- Project structure created
- Database models implemented
- Docker setup configured
- Alembic migrations initialized

🚧 Phase 2: Core Estimation Logic (Next)
