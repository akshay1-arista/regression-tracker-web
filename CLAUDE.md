# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

**Regression Tracker Web** is a full-stack FastAPI web application that tracks regression test results from Jenkins jobs. It provides:
- Real-time dashboard tracking across multiple releases/modules/jobs
- Historical trend analysis with flaky test detection
- Automatic background polling of Jenkins for new builds
- Manual download triggers with real-time progress tracking
- Admin interface for configuration management

## Architecture

### Stack
- **Backend**: FastAPI (Python 3.9+) with async/await support
- **Database**: SQLite with SQLAlchemy 2.0 ORM
- **Frontend**: Server-rendered Jinja2 templates + Alpine.js for reactivity
- **Scheduler**: APScheduler for background Jenkins polling
- **Charts**: Chart.js for visualizations
- **Production**: Gunicorn with multiple workers + Redis for caching/job queuing

### Database Schema

Six primary tables managed via Alembic migrations:

1. **releases** - Release versions being monitored (7.0.0.0, 6.4.0.0, etc.)
2. **modules** - Modules within releases (business_policy, routing, etc.)
3. **jobs** - Individual job runs with summary statistics (denormalized for performance)
4. **test_results** - Individual test cases with full details
5. **testcase_metadata** - Test metadata (priority, categories, filters)
6. **jenkins_polling_logs** - Background polling activity tracking

Key relationships: `Release -> Module -> Job -> TestResult`

### Routing Architecture

Seven routers organize 18+ API endpoints:
- **dashboard.py** - Dashboard data (summary, releases, modules, jobs)
- **trends.py** - Trend analysis and flaky test detection
- **jobs.py** - Job details and test results with pagination
- **jenkins.py** - Manual download triggers with SSE progress streaming
- **admin.py** - Configuration (polling, releases, settings)
- **search.py** - Autocomplete and test case search
- **views.py** - HTML page rendering (/, /trends, /jobs, /admin)

### API Versioning

All API endpoints use `/api/v1/*` prefix with backward-compatible `/api/*` aliases:
- Current: `/api/v1/dashboard/summary`
- Legacy: `/api/dashboard/summary` (maintained for compatibility)

## Development Workflow

### Initial Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with Jenkins credentials and settings

# Initialize database
alembic upgrade head
```

### Running the Application

```bash
# Development server (auto-reload enabled)
./start.sh
# OR
uvicorn app.main:app --reload --port 8000

# Production server
./start_production.sh
# OR
gunicorn -c gunicorn.conf.py app.main:app
```

Access: http://localhost:8000

API docs: http://localhost:8000/docs (Swagger UI)

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_services.py

# With coverage
pytest --cov=app --cov-report=html

# Performance tests
pytest tests/test_performance.py -v
```

### Database Migrations

```bash
# Create new migration after model changes
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

## Key Technical Patterns

### Database Sessions

Always use dependency injection for database sessions in routes:

```python
from app.database import get_db_context
from sqlalchemy.orm import Session
from fastapi import Depends

@router.get("/example")
async def example_endpoint(db: Session = Depends(get_db_context)):
    # db session automatically managed (committed/rolled back)
    results = db.query(Job).all()
    return results
```

Never create sessions manually in route handlers. Use the `get_db_context` dependency.

### Background Jobs

The application uses APScheduler for background tasks:
- **Jenkins Poller** (`app/tasks/jenkins_poller.py`) - Runs every N hours (configurable)
- **Job Tracker** (`app/utils/job_tracker.py`) - Manages in-memory job state for manual downloads
- **SSE Streaming** - Real-time progress updates via Server-Sent Events

Background jobs should NOT access `current_app` or request context. Pass config as dict.

### Caching Strategy

FastAPI-Cache2 with two backends:
- **Development**: In-memory cache (automatic fallback)
- **Production**: Redis cache (if REDIS_URL configured)

Cache decorator usage:
```python
from fastapi_cache.decorator import cache

@router.get("/expensive-query")
@cache(expire=300)  # 5 minutes
async def expensive_endpoint(db: Session = Depends(get_db_context)):
    # Cached for 5 minutes
    pass
```

Health check: `/health/detailed` shows cache backend status.

### Security Features

- **Rate Limiting**: SlowAPI middleware (configurable per-minute limits)
- **API Key Auth**: Optional via `X-API-Key` header (set API_KEY env var)
- **Admin Protection**: PIN-based access (ADMIN_PIN_HASH in .env)
- **CORS**: Restricted to specific origins (ALLOWED_ORIGINS env var)
- **Input Validation**: Pydantic schemas for all inputs

Security utilities in `app/utils/security.py` and `app/utils/auth.py`.

### Performance Optimizations

1. **Denormalized Statistics**: Job summary stats stored in `jobs` table (total, passed, failed, etc.)
2. **Pagination**: All large result sets paginated (default: 50 items)
3. **Database Indexes**: Composite indexes on frequently queried columns
4. **Async Operations**: FastAPI async/await for concurrent request handling
5. **Connection Pooling**: SQLAlchemy pool settings in `app/database.py`

## File Organization

```
regression-tracker-web/
├── app/
│   ├── routers/          # API endpoints (7 routers)
│   ├── models/           # SQLAlchemy models + Pydantic schemas
│   ├── services/         # Business logic (data_service, testcase_metadata_service)
│   ├── tasks/            # Background jobs (scheduler, jenkins_poller)
│   ├── utils/            # Utilities (auth, security, helpers, job_tracker, cleanup)
│   ├── parser/           # JUnit XML parsing logic
│   ├── templates/        # Jinja2 HTML templates (placeholder - templates/ at root)
│   ├── main.py           # FastAPI app initialization
│   ├── config.py         # Settings management (Pydantic BaseSettings)
│   └── database.py       # SQLAlchemy setup
│
├── templates/            # Jinja2 HTML templates (actual location)
├── static/               # CSS, JavaScript, images
├── alembic/              # Database migrations
│   └── versions/         # Migration scripts
├── tests/                # Pytest test suite (15+ test files)
├── scripts/              # Utility scripts (import, cleanup, validation)
├── deployment/           # Systemd service, installation scripts
├── docs/                 # Documentation (deployment, user guides)
├── data/                 # SQLite database file (git-ignored)
└── logs/                 # Downloaded Jenkins artifacts (git-ignored)
```

## Important Conventions

### Environment Configuration

All settings in `.env` file (see `.env.example`):
- **Required**: JENKINS_URL, JENKINS_USER, JENKINS_API_TOKEN
- **Optional**: REDIS_URL (enables Redis caching), ADMIN_PIN_HASH, JENKINS_BUILD_QUERY_LIMIT
- **Defaults**: AUTO_UPDATE_ENABLED=false, POLLING_INTERVAL_HOURS=12, PORT=8000, JENKINS_BUILD_QUERY_LIMIT=100

Settings loaded via Pydantic Settings in `app/config.py`. Access via `get_settings()`.

**New Setting - JENKINS_BUILD_QUERY_LIMIT:**
- Controls max number of recent builds fetched per Jenkins API call
- Default: 100 (suitable for most use cases)
- Increase if polling less frequently or expecting many builds between polls
- Uses Jenkins API range query `{0,limit}` for better performance
- System logs warning if gap detected between builds (may indicate limit too low)

### Test Data Import

Import historical test data from Jenkins artifacts:

```bash
# Import from logs/ directory structure
python scripts/import_existing_data.py

# Backfill metadata for specific release
python backfill_6.4_metadata.py
```

Expected log structure: `logs/{release}/{module}/{job_id}/test-results.xml`

**Important**: After importing data, the `last_processed_build` field is automatically synced. For manual imports or older deployments, see "Database Maintenance" below.

### Database Maintenance

**Syncing last_processed_build:**

The `last_processed_build` field in the `releases` table tracks the last processed Jenkins build to prevent re-fetching old builds during polling. This field must stay in sync with actual jobs in the database.

**When to sync:**
- After manual data imports (if not using updated `import_existing_data.py`)
- After database migrations or manual SQL operations
- When on-demand polling fetches unexpected old builds

**How to sync:**

Option 1 - Admin UI (recommended):
```
1. Navigate to http://localhost:8000/admin
2. Enter admin PIN
3. Scroll to "Database Maintenance" section
4. Click "Sync Last Processed Builds" button
5. Review results showing old → new values
```

Option 2 - CLI script:
```bash
python scripts/sync_last_processed_builds.py
```

Option 3 - API endpoint:
```bash
curl -X POST http://localhost:8000/api/v1/admin/releases/sync-last-processed-builds \
  -H "X-Admin-PIN: your_pin"
```

**How it works:**
- Queries max `parent_job_id` from `jobs` table for each release
- Updates `last_processed_build` if different
- Safely handles NULL and empty `parent_job_id` values
- Returns detailed results with update counts

**Migration for existing deployments:**

If upgrading to PR #16 with existing data:
```bash
# One-time sync after deployment
python scripts/sync_last_processed_builds.py

# Or use admin UI sync button
```

This ensures on-demand polling only fetches new builds (e.g., > 216) instead of all historical builds.

### Jenkins Integration

Jenkins poller (`app/tasks/jenkins_poller.py`) expects:
- Jenkins API v2 JSON endpoint support
- Artifacts named `test-results.xml` (JUnit XML format)
- Job URLs in format: `{JENKINS_URL}/job/{name}/{build_number}/`

Manual download endpoint: `POST /api/v1/jenkins/download` with SSE progress at `/api/v1/jenkins/download/{job_id}/progress`

### Frontend Patterns

Alpine.js for lightweight reactivity:
- Dashboard auto-refreshes every 30 seconds
- Trend charts use Chart.js with responsive config
- All forms use Alpine.js for validation and submission

Templates use Jinja2 with macros in `templates/macros/` (if present).

## Production Deployment

Production uses Gunicorn with multiple workers:

```bash
# Quick start (single server)
./start_production.sh

# Systemd service (persistent)
sudo deployment/install.sh
sudo systemctl start regression-tracker
sudo systemctl enable regression-tracker
```

Configuration:
- **gunicorn.conf.py** - Worker settings, logging, timeouts
- **deployment/regression-tracker.service** - Systemd unit file

Health checks:
- Basic: `/health`
- Detailed: `/health/detailed`
- Liveness: `/health/live` (Kubernetes)
- Readiness: `/health/ready` (Kubernetes)

See [docs/deployment/PRODUCTION.md](docs/deployment/PRODUCTION.md) for complete deployment guide.

## Logging

Application logs to stdout (captured by systemd/gunicorn):
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- Level: Controlled by LOG_LEVEL env var (default: INFO)
- Structured logging for background jobs with job IDs

Check logs: `sudo journalctl -u regression-tracker -f` (systemd) or console output (development)
