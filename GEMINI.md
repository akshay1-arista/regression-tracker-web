# Regression Tracker Web Application

## Project Overview

**Type:** Full-stack Web Application (Python/FastAPI)

This project is a regression test tracking system designed to monitor Jenkins jobs, analyze test results, and provide visualization of historical trends. It serves as a web-based replacement/enhancement for an existing CLI tool.

**Key Features:**
*   **Live Dashboard:** Real-time status of releases and modules.
*   **Trend Analysis:** Historical views of test pass rates and failure patterns.
*   **Data Ingestion:** Automated parsing of Jenkins log artifacts.
*   **API-First:** Comprehensive REST API for all data operations.

## Architecture & Tech Stack

*   **Backend:** FastAPI (Python 3.9+)
*   **Database:** SQLAlchemy ORM with SQLite (default)
*   **Migrations:** Alembic
*   **Task Scheduling:** APScheduler (for Jenkins polling)
*   **Frontend:** Jinja2 Templates + Alpine.js (Server-side rendered with lightweight interactivity)
*   **Testing:** Pytest

## Key Directories & Files

*   `app/`
    *   `main.py`: Application entry point and configuration.
    *   `models/db_models.py`: SQLAlchemy database models (`Release`, `Module`, `Job`, `TestResult`).
    *   `routers/`: API route handlers (`dashboard.py`, `trends.py`, `jobs.py`).
    *   `services/`: Business logic, specifically `import_service.py` for log parsing.
    *   `templates/`: HTML templates (Jinja2).
*   `alembic/`: Database migration scripts.
*   `static/`: CSS, JS, and image assets.
*   `tests/`: Unit and integration tests.
*   `scripts/`: Utility scripts for data management.

## Setup & Development

### 1. Installation
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure environment variables
```

### 2. Database
Manage the database using Alembic:
```bash
# Apply migrations
alembic upgrade head

# Create a new migration (after modifying models)
alembic revision --autogenerate -m "description_of_change"
```

### 3. Running the Server
```bash
# Development mode with hot reload
uvicorn app.main:app --reload --port 8000
```

### 4. Testing
Run the test suite using pytest:
```bash
pytest
```

## Conventions

*   **Code Style:** Follow PEP 8.
*   **Architecture:** Service-Repository pattern. Keep business logic in `app/services/` and data access in `app/routers/` or dedicated CRUD helpers.
*   **Async/Await:** Use `async def` for route handlers and database operations where possible.
*   **Configuration:** All configuration should be managed via `app/config.py` and environment variables.
*   **Logging:** Use the standard `logging` module configured in `main.py`.

## Useful Commands

*   **Run Linter:** `ruff check .` (if installed) or `flake8`
*   **Import Data:** `python scripts/import_existing_data.py` (assumes `scripts` module context)
