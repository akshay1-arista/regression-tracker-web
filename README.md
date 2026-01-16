# Regression Tracker Web Application

Full-stack web application for tracking regression test results across Jenkins jobs.

## Features

- **Live Dashboard**: Real-time tracking of multiple releases/modules/jobs
- **Historical Trends**: Test trend analysis with flaky test detection
- **Automatic Updates**: Background polling of Jenkins for new builds (configurable interval)
- **Manual Downloads**: Trigger Jenkins downloads with real-time progress tracking
- **Admin Interface**: Configuration management for polling, releases, and settings

## Tech Stack

- **Backend**: FastAPI (Python 3.9+)
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Server-rendered Jinja2 templates + Alpine.js for reactivity
- **Scheduler**: APScheduler for background Jenkins polling
- **Charts**: Chart.js for visualizations

## Architecture

```
regression-tracker-web/
├── app/
│   ├── models/         # SQLAlchemy models & Pydantic schemas
│   ├── routers/        # API endpoints (18 endpoints)
│   ├── services/       # Business logic layer
│   ├── tasks/          # Background jobs (Jenkins poller)
│   ├── templates/      # Jinja2 HTML templates
│   └── utils/          # Utility functions (reused from CLI)
├── static/             # CSS, JavaScript, images
├── data/               # SQLite database
├── logs/               # Jenkins test artifacts
├── scripts/            # Utility scripts
└── tests/              # Unit & integration tests
```

## Quick Start

### Prerequisites

- Python 3.9+
- Git
- Jenkins credentials (username + API token)

### Installation

```bash
# Clone the repository
git clone https://github.com/akshay1-arista/regression-tracker-web.git
cd regression-tracker-web

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Jenkins credentials
```

### Database Setup

```bash
# Initialize Alembic
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial schema"

# Apply migration
alembic upgrade head
```

### Run Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

## Production Deployment

For production deployments:

```bash
# Quick production start (single server)
./start_production.sh

# Or install as system service
sudo deployment/install.sh
sudo systemctl start regression-tracker
```

**Documentation:**
- [Production Deployment Guide](docs/deployment/PRODUCTION.md) - Complete deployment guide
- [Quick Start Guide](docs/deployment/QUICKSTART.md) - Get started in 10 minutes
- [Testing Guide](docs/deployment/TESTING.md) - Validation and performance testing

**Health Checks:**
- Basic: http://localhost:8000/health
- Detailed: http://localhost:8000/health/detailed
- Liveness: http://localhost:8000/health/live
- Readiness: http://localhost:8000/health/ready

## Development Phases

This project is being developed in phases:

- [x] **Phase 0**: Repository setup & initial structure
- [x] **Phase 1**: Database foundation
  - ✅ SQLAlchemy models for 6 tables
  - ✅ Alembic migrations
  - ✅ Import service for logs → database
  - ✅ Import historical data script
- [x] **Phase 2**: FastAPI backend
  - ✅ Core application setup
  - ✅ Data service layer
  - ✅ 18 API endpoints across 5 routers
  - ✅ Unit & integration tests
- [x] **Phase 3**: Frontend pages
  - ✅ Jinja2 templates with Alpine.js
  - ✅ Dashboard, trends, job details pages
  - ✅ Chart.js visualizations
  - ✅ Client-side polling for updates
- [x] **Phase 4**: Background polling
  - ✅ APScheduler setup
  - ✅ Jenkins poller task
  - ✅ Admin interface
  - ✅ Manual download with SSE progress
- [x] **Phase 5**: Deployment & testing
  - ✅ Production setup with gunicorn ([gunicorn.conf.py](gunicorn.conf.py), [start_production.sh](start_production.sh))
  - ✅ Systemd service configuration ([deployment/regression-tracker.service](deployment/regression-tracker.service))
  - ✅ Data validation script ([scripts/validate_data.py](scripts/validate_data.py))
  - ✅ Performance testing suite ([tests/test_performance.py](tests/test_performance.py))
  - ✅ Enhanced health check endpoints (`/health`, `/health/detailed`, `/health/live`, `/health/ready`)
  - ✅ Deployment documentation ([docs/deployment/](docs/deployment/))
  - ✅ Production deployment guide

## API Documentation

Once the server is running, visit:
- **Interactive API docs**: http://localhost:8000/docs (Swagger UI)
- **Alternative API docs**: http://localhost:8000/redoc (ReDoc)

## Configuration

See [.env.example](.env.example) for all available configuration options.

Key settings:
- `POLLING_INTERVAL_MINUTES`: How often to check Jenkins for new builds (default: 15)
- `AUTO_UPDATE_ENABLED`: Enable/disable automatic polling (default: true)
- `JENKINS_URL`: Jenkins server base URL
- `LOGS_BASE_PATH`: Directory for storing downloaded Jenkins artifacts

## Contributing

This project follows a phase-based development approach. Each phase is developed in a feature branch and merged to `develop` after verification.

Branch strategy:
- `main` - Production-ready code
- `develop` - Integration branch
- `feature/*` - Feature branches for each phase

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

For issues or questions, please open an issue on GitHub: https://github.com/akshay1-arista/regression-tracker-web/issues
