# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

**Regression Tracker Web** is a full-stack FastAPI web application that tracks regression test results from Jenkins jobs. It provides:
- Real-time dashboard tracking across multiple releases/modules/jobs
- Historical trend analysis with flaky test detection
- **Bug tracking dashboard** - VLEI/VLENG bug visibility with priority filtering
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

Eight primary tables managed via Alembic migrations:

1. **releases** - Release versions being monitored (7.0.0.0, 6.4.0.0, etc.)
2. **modules** - Modules within releases (business_policy, routing, etc.)
3. **jobs** - Individual job runs with summary statistics (denormalized for performance)
4. **test_results** - Individual test cases with full details
   - Includes `jenkins_topology` (execution context from JUnit XML)
   - Includes `topology_metadata` (design specification from metadata CSV)
5. **testcase_metadata** - Test metadata with extended fields
   - Core fields: priority, test_case_id, testrail_id, component, automation_status
   - Extended fields: module, test_state, test_class_name, test_path, topology
6. **bug_metadata** - VLEI/VLENG bug information (defect_id, status, summary, url, priority)
7. **bug_testcase_mappings** - Many-to-many relationships between bugs and test cases
8. **jenkins_polling_logs** - Background polling activity tracking

Key relationships:
- Test execution: `Release -> Module -> Job -> TestResult`
- Bug tracking: `TestResult -> TestcaseMetadata -> BugTestcaseMapping -> BugMetadata`

Metadata enrichment: `TestResult.topology_metadata` denormalized from `TestcaseMetadata.topology` for fast filtering

### Routing Architecture

Seven routers organize 21+ API endpoints:
- **dashboard.py** - Dashboard data (summary, releases, modules, jobs, bug tracking)
  - Includes 3 bug tracking endpoints: bug-breakdown, bug-details, bug-affected-tests
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

### Pre-Commit Testing Procedures

**IMPORTANT**: Always run tests before committing changes to ensure code quality and prevent regressions.

#### 1. Identify Affected Tests

Based on your changes, determine which test files to run:

| Files Changed | Tests to Run |
|--------------|-------------|
| `app/models/db_models.py` | `tests/test_db_models.py`, `tests/test_services.py`, `tests/test_import_service.py` |
| `app/services/data_service.py` | `tests/test_services.py`, `tests/test_api_endpoints.py` |
| `app/services/import_service.py` | `tests/test_import_service.py` |
| `app/routers/*.py` | `tests/test_api_endpoints.py`, `tests/test_api_security.py` |
| `app/parser/*.py` | `tests/test_parser.py` (if exists) |
| Database migrations | All tests in `tests/` |

#### 2. Run Relevant Tests

```bash
# For model changes
pytest tests/test_db_models.py tests/test_services.py tests/test_import_service.py -v

# For service layer changes
pytest tests/test_services.py tests/test_import_service.py -v

# For API endpoint changes
pytest tests/test_api_endpoints.py tests/test_api_security.py -v

# For database migration changes - run ALL tests
pytest --ignore=tests/test_security.py -v
```

#### 3. Verify All Tests Pass

- All tests in the relevant files MUST pass before committing
- Fix any failing tests related to your changes
- If tests fail due to pre-existing issues unrelated to your changes:
  - Document the pre-existing failures
  - Ensure your changes don't introduce NEW failures
  - Consider creating a separate commit to fix legacy test issues

#### 4. Fast Feedback Loop

For rapid iteration during development:

```bash
# Run only tests for the specific class/function you're working on
pytest tests/test_services.py::TestDataService::test_specific_function -v

# Run tests with fail-fast (stop on first failure)
pytest tests/test_services.py -x

# Run tests matching a pattern
pytest -k "test_job" -v
```

#### 5. Example Workflow

```bash
# 1. Make your changes to app/services/data_service.py
# 2. Run affected tests
pytest tests/test_services.py -v

# 3. If tests pass, run broader test suite
pytest tests/test_api_endpoints.py tests/test_services.py -v

# 4. All clear? Commit your changes
git add app/services/data_service.py tests/test_services.py
git commit -m "fix: Update data_service logic for X"

# 5. Push to remote
git push origin main
```

#### 6. Known Test Issues

Some test files have legacy issues (as of 2026-01-22):

- **FastAPI Cache Issues**: Some integration tests fail with "You must call init first!" error
  - Files: `tests/test_all_modules_endpoints.py`, `tests/test_api_endpoints.py`, `tests/test_multi_select_filters.py`
  - Root cause: FastAPI cache not initialized in test fixtures
  - Workaround: Ignore these tests when running pre-commit checks: `pytest --ignore=tests/test_all_modules_endpoints.py`

- **Bug API Tests**: Some tests have errors due to missing fixtures/setup
  - Files: `tests/test_bug_api.py`

- **Jenkins Poller Tests**: Some tests fail due to mock configuration issues
  - Files: `tests/test_jenkins_poller.py`

**Core test files that MUST pass**:
- ✅ `tests/test_db_models.py` (12 tests)
- ✅ `tests/test_services.py` (60 tests)
- ✅ `tests/test_import_service.py` (16 tests)
- ✅ `tests/test_admin_sync.py` (8 tests)
- ✅ `tests/test_autocomplete.py` (19 tests)
- ✅ `tests/test_bug_tracking.py` (partial - 18 tests)
- ✅ `tests/test_job_tracker.py` (28 tests)

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

**Important Notes for Topology Metadata Migrations:**

The topology metadata feature (PR #20) includes two migrations that must be applied in sequence:
1. `3dbc680859a3` - Adds 5 new fields to `testcase_metadata` table
2. `9722860d4fd4` - Splits `topology` field in `test_results` into `jenkins_topology` and `topology_metadata`

**Expected behavior after migration:**
- `test_results.topology_metadata` will be NULL until import script is run
- This is INTENTIONAL - topology_metadata comes from CSV metadata, not Jenkins
- UI handles NULL values gracefully with "N/A" display

**Post-migration data import:**
```bash
# Import topology metadata from CSV (populates topology_metadata field)
python scripts/import_topology_metadata.py

# Dry-run mode to preview changes
python scripts/import_topology_metadata.py --dry-run

# Skip backfilling test_results table (faster)
python scripts/import_topology_metadata.py --skip-backfill-results
```

The import script uses **bulk operations** for optimal performance and includes:
- Conditional priority update (preserves manual overrides)
- Comprehensive statistics tracking (including "both NULL" cases)
- Error handling with encoding fallback (UTF-8 → latin-1)

## Bug Tracking Feature

**Added in PR #29** - Provides visibility into VLEI/VLENG bugs affecting test cases across modules.

### Overview

The bug tracking feature displays per-module aggregation of bugs affecting **SKIPPED** test cases (tests blocked by known bugs). It integrates seamlessly with the dashboard and provides:

- **Per-module bug breakdown** - VLEI and VLENG bug counts with affected test counts
- **Priority filtering** - Filter by P0, P1, P2, P3, HIGH, MEDIUM, UNKNOWN priorities
- **Interactive modals** - Click-through navigation from module → bug details → affected tests
- **Real-time filtering** - Instant updates when priorities are selected/deselected
- **Accessibility support** - Full ARIA attributes and keyboard navigation

### Database Integration

Uses existing bug metadata infrastructure with 4-table join chain:

```
TestResult → TestcaseMetadata → BugTestcaseMapping → BugMetadata
```

**Key tables:**
- `bug_metadata` - VLEI/VLENG bug information (defect_id, status, summary, url, priority)
- `bug_testcase_mappings` - Many-to-many relationships between bugs and test cases
- `testcase_metadata` - Test metadata including priorities and test_case_id/testrail_id
- `test_results` - Test execution results (filtered by status='SKIPPED')

**Important**: The bug tracking table only shows bugs affecting **SKIPPED** tests in the selected parent job. This focuses on tests that are currently blocked by known issues.

### API Endpoints

Three new endpoints in `app/routers/dashboard.py`:

#### 1. Bug Breakdown
```
GET /api/v1/dashboard/bug-breakdown/{release}/{module}?parent_job_id=X&priorities=P0,P1
```

Returns per-module bug statistics:
```json
[
  {
    "module_name": "business_policy",
    "vlei_count": 3,
    "vleng_count": 2,
    "affected_test_count": 12,
    "total_bug_count": 5
  }
]
```

**Parameters:**
- `release` (path) - Release name (e.g., "7.0")
- `module` (path) - Module name or "__all__" for all modules
- `parent_job_id` (query, required) - Parent job ID to filter by
- `priorities` (query, optional) - Comma-separated priority filters (validated with regex `^[A-Z0-9,]+$`)

**Features:**
- Uses distinct counts to avoid double-counting
- Groups by `testcase_module` from test results
- Sorted by `affected_test_count` descending (most impactful bugs first)
- Cached with configurable TTL

#### 2. Bug Details
```
GET /api/v1/dashboard/bug-details/{release}/{module}?parent_job_id=X&bug_type=VLEI
```

Returns detailed bug information for modal display:
```json
[
  {
    "defect_id": "VLEI-12345",
    "bug_type": "VLEI",
    "status": "Open",
    "summary": "Test fails on 5-site topology",
    "url": "https://jira.example.com/browse/VLEI-12345",
    "priority": "P0",
    "affected_test_count": 8,
    "priority_breakdown": {
      "P0": 3,
      "P1": 5,
      "P2": 0,
      "P3": 0,
      "UNKNOWN": 0
    }
  }
]
```

**Parameters:**
- `bug_type` (query, optional) - Filter by "VLEI" or "VLENG"

**Performance Optimization** (PR #29 fixes):
- Single query with grouping by both `bug_id` and `test_priority`
- Avoids N+1 query problem (previously 1 + N queries, now just 1 query)
- Post-processes results in Python to build nested structure

#### 3. Affected Tests
```
GET /api/v1/dashboard/bug-affected-tests/{release}/{module}/{defect_id}?parent_job_id=X
```

Returns list of test cases affected by a specific bug:
```json
[
  {
    "testcase_name": "test_policy_creation",
    "priority": "P0",
    "status": "SKIPPED",
    "test_case_id": "TC-1234",
    "file_path": "tests/business_policy/test_policies.py"
  }
]
```

**Features:**
- Sorted by priority (P0 first) then alphabetically by test name
- Uses `PRIORITY_ORDER` constant for consistent sorting
- Handles NULL priorities as "UNKNOWN"

### Frontend Components

**Location**: `templates/dashboard.html`, `static/js/dashboard.js`, `static/css/styles.css`

#### Bug Breakdown Table
- Displays when `bugBreakdown.length > 0 || selectedBugPriorities.length > 0`
- Only visible when parent job is selected
- Module names link to trend pages
- Bug counts are clickable badges that open modals

#### Priority Filter Checkboxes
```javascript
availablePriorities: ['P0', 'P1', 'P2', 'P3', 'HIGH', 'MEDIUM', 'UNKNOWN']
```

**Features:**
- Multi-select checkboxes for priority filtering
- "Clear Filters" button appears when priorities selected
- Real-time filtering via `loadBugBreakdown()` on change
- Empty state message when filter returns no results

#### Bug Details Modal
- Triggered by clicking VLEI/VLENG count badges
- Shows table of bugs with status badges, priority breakdown, and affected test counts
- "View Tests" button navigates to affected tests modal
- **Accessibility**: Full ARIA attributes, keyboard navigation (Escape to close)

#### Affected Tests Modal
- Shows test cases affected by a specific bug
- **Back button** returns to bug details modal (preserves state)
- Displays priority badges, test names, and status
- **Accessibility**: ARIA labels, keyboard navigation

### Priority Filtering

**Implementation**: `app/services/data_service.py`

Helper functions for priority handling:
```python
def parse_and_validate_priorities(priorities_str: Optional[str]) -> Optional[List[str]]:
    """Parse and validate comma-separated priority string."""
    # Validates against VALID_PRIORITIES = {'P0', 'P1', 'P2', 'P3', 'HIGH', 'MEDIUM', 'UNKNOWN'}
    # Raises ValidationError if invalid priorities found

def _apply_priority_filter(query, priority_list: List[str]):
    """Apply priority filter to SQLAlchemy query, handling UNKNOWN (NULL) priorities."""
    # Special handling for 'UNKNOWN' → maps to NULL in database
    # Case-insensitive matching for priority values
```

**NULL Handling**: The `UNKNOWN` priority maps to NULL values in the database. The filter logic handles this with a special case:
```python
if 'UNKNOWN' in priority_list:
    # Include both specific priorities AND NULL values
    query.filter(
        (func.upper(TestResult.priority).in_(other_priorities)) |
        (TestResult.priority.is_(None))
    )
```

### CSS Styling

**Location**: `static/css/styles.css` (lines 2519-2844)

**Key styles:**
- `.bug-breakdown-table` - Main table with gradient header
- `.vlei-badge` - Red gradient badge for VLEI bugs
- `.vleng-badge` - Orange gradient badge for VLENG bugs
- `.affected-tests-count` - Blue gradient badge for affected test counts
- `.modal-overlay` - Full-screen modal with backdrop blur
- `.modal-content` - Centered modal with shadow and animations
- `.bug-status-badge` - Color-coded status badges (open, resolved, closed, etc.)
- `.priority-breakdown-compact` - Inline priority count display
- `.btn-back` - Back button with hover effects
- `.bug-modal-text-center` - Scoped text-center class (avoids global conflicts)

**Animations:**
- `modalFadeIn` / `modalFadeOut` - Smooth modal transitions
- Hover effects on clickable badges (transform + box-shadow)

### Example Usage

**Typical workflow:**

1. **User selects parent job** on dashboard
   - Bug breakdown table automatically loads
   - Shows per-module bug statistics

2. **User applies priority filter** (e.g., P0 + P1)
   - Table updates to show only high-priority bugs
   - Empty state appears if no bugs match filter

3. **User clicks VLEI count** for a module
   - Bug details modal opens
   - Shows list of VLEI bugs with priority breakdown

4. **User clicks "View Tests"** for a specific bug
   - Affected tests modal opens
   - Shows test cases blocked by that bug
   - **Back button** returns to bug list

5. **User clicks module name**
   - Navigates to trend page for that module
   - Full historical view with charts

### Performance Considerations

**Optimizations applied:**
- ✅ Single query for bug details with priority breakdown (avoids N+1)
- ✅ Distinct counts to avoid duplication
- ✅ Caching enabled on all endpoints
- ✅ Indexes on `job_id`, `testcase_module`, `status` columns
- ✅ Frontend uses request cancellation to prevent race conditions

**Query complexity**: 4-table join with multiple filters
- Joins: `TestResult` → `TestcaseMetadata` → `BugTestcaseMapping` → `BugMetadata`
- Filters: `job_id IN (...)`, `testcase_module`, `status='SKIPPED'`, `is_active=True`
- Performance: Acceptable for current scale, monitor with larger datasets

### Testing

**Test files:**
- `tests/test_bug_tracking.py` - Bug tracking feature tests (18 tests)
- `tests/test_bug_api.py` - Bug API endpoint tests

**Key test scenarios:**
- Bug breakdown aggregation with distinct counts
- Priority filtering including NULL/UNKNOWN handling
- Modal data loading and navigation
- Empty states and edge cases
- Input validation for priority parameters

### Known Limitations

1. **No pagination** - Bug breakdown table shows all modules (acceptable for current scale)
2. **Parent job required** - Bug tracking only available when parent job selected
3. **SKIPPED tests only** - Only shows bugs affecting currently skipped tests (by design)
4. **No historical view** - Shows bugs for selected parent job only (not historical trend)

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

### Testcase Metadata Management

The application enriches test results with metadata from CSV files for enhanced filtering, categorization, and reporting.

#### Testcase Metadata Fields

The `testcase_metadata` table stores comprehensive metadata for each test case:

**Core Fields** (from `hapy_automated.csv`):
- `testcase_name`: Unique test identifier (e.g., "test_create_policy")
- `test_case_id`: Test case ID from test management system
- `priority`: Test priority (P0, P1, P2, P3, or NULL)
- `testrail_id`: TestRail integration ID
- `component`: Component under test (e.g., "DataPlane")
- `automation_status`: Automation state (e.g., "Hapy Automated")

**Extended Fields** (from `dataplane_test_topologies.csv`):
- `module`: Test module category (e.g., "business_policy", "routing")
- `test_state`: Test maturity state (e.g., "PROD", "STAGING")
- `test_class_name`: Python test class name (e.g., "TestBackhaulToHub")
- `test_path`: Full file path to test source
- `topology`: Design topology specification (e.g., "5-site", "3-site-ipv6")

#### Topology Field Distinction

**IMPORTANT**: The application maintains TWO separate topology fields to distinguish execution context from test design:

1. **`test_results.jenkins_topology`** (Execution Topology)
   - Source: JUnit XML from Jenkins artifacts
   - Represents: What topology Jenkins actually ran the test on
   - Example: "5s" (execution context)
   - Used for: Filtering by actual execution environment

2. **`testcase_metadata.topology`** (Design Topology)
   - Source: CSV metadata files
   - Represents: What topology the test was designed for
   - Example: "5-site" (design specification)
   - Used for: Categorization and test design tracking

Both fields are denormalized into `test_results` table for fast filtering:
- `test_results.jenkins_topology`: From JUnit XML
- `test_results.topology_metadata`: Copied from `testcase_metadata.topology`

**UI Display**: Trend and job detail pages show both topologies with tooltips explaining the distinction.

#### Importing Topology Metadata

Import test metadata from CSV files using the dedicated import script:

```bash
# Import from dataplane_test_topologies.csv (default location)
python scripts/import_topology_metadata.py

# Specify custom CSV path
python scripts/import_topology_metadata.py --csv-path /path/to/custom.csv

# Dry-run mode (preview changes without committing)
python scripts/import_topology_metadata.py --dry-run

# Skip backfilling test_results table (faster import)
python scripts/import_topology_metadata.py --skip-backfill-results
```

**Script Behavior**:
- **New test cases**: Inserts all fields from CSV (including priority, can be NULL)
- **Existing test cases**: Selective update logic
  - Always updates: `topology`, `module`, `test_state`, `test_class_name`, `test_path`, `test_case_id`
  - Conditionally updates: `priority` (only if existing value is NULL)
- **CSV column mapping**:
  - `testcase_id` (CSV) → `test_case_id` (DB)
  - `path` (CSV) → `test_path` (DB)
  - Direct mappings: `module`, `test_class_name`, `testcase_name`, `topology`, `test_state`, `priority`
- **Priority validation**: Invalid values (not P0-P3) are stored as NULL with warning
- **Batch processing**: Processes in batches of 1,000 for optimal performance

**Conditional Priority Update Logic**:

The import script preserves manually set priorities while updating NULL values:

```python
# EXISTING RECORD - Selective updates
if existing_record:
    # Always update these fields (unconditional)
    existing.topology = csv_record['topology']
    existing.module = csv_record['module']
    # ... other fields

    # Conditionally update priority (only if NULL)
    if existing.priority is None and csv_record['priority'] is not None:
        existing.priority = csv_record['priority']  # Update from CSV
    # else: preserve existing priority value
```

This allows manual priority overrides in the database to be preserved during CSV re-imports.

**Example Import Session**:

```bash
$ python scripts/import_topology_metadata.py --dry-run
2026-01-24 10:30:15 - INFO - Reading CSV: 10,810 total rows
2026-01-24 10:30:15 - INFO - Filtering: 10,810 rows with testcase_name
2026-01-24 10:30:15 - INFO - Validating priorities...
2026-01-24 10:30:15 - WARNING - Invalid priority 'Medium' for test_case_001 (setting to NULL)
2026-01-24 10:30:15 - INFO - Preview (dry-run mode):
  - New records to insert: 658
  - Existing records to update: 10,152
  - Priority updates (NULL → CSV): 9,689
  - Priority preserved (non-NULL): 463
  - Invalid priorities → NULL: 14

$ python scripts/import_topology_metadata.py
# (Actual import runs with same statistics)
2026-01-24 10:32:45 - INFO - Import complete: 658 inserted, 10,152 updated
```

**Topology Distribution** (example from dataplane_test_topologies.csv):
- 5-site: ~4,477 test cases (41%)
- 3-site: ~2,841 test cases (26%)
- 5-site-mpg: ~794 test cases
- 5-site-ipv6: ~709 test cases

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
