"""
Admin API Router.

Provides endpoints for application settings and release management.

All endpoints require PIN authentication via X-Admin-PIN header.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, HttpUrl, field_validator, ConfigDict
from sqlalchemy.orm import Session
import re

from sqlalchemy import func, cast, Integer

from app.database import get_db
from app.models.db_models import Release, Module, AppSettings, Job
from app.utils.security import require_admin_pin
from app.services import testcase_metadata_service


logger = logging.getLogger(__name__)
router = APIRouter()

# Background job tracking
_import_jobs: Dict[str, Dict[str, Any]] = {}
_import_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="import_worker")


# Request/Response Models

class SettingUpdate(BaseModel):
    """Model for updating a setting."""
    value: str  # JSON-encoded value


class ReleaseCreate(BaseModel):
    """Model for creating a release."""
    name: str
    jenkins_job_url: Optional[HttpUrl] = None
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Validate release name format (semantic version)."""
        if not re.match(r'^\d+\.\d+\.\d+\.\d+$', v):
            raise ValueError('Release name must be semantic version (e.g., 7.0.0.0)')
        return v


class ReleaseUpdate(BaseModel):
    """Model for updating a release."""
    name: Optional[str] = None
    jenkins_job_url: Optional[HttpUrl] = None
    is_active: Optional[bool] = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Validate release name format if provided."""
        if v and not re.match(r'^\d+\.\d+\.\d+\.\d+$', v):
            raise ValueError('Release name must be semantic version (e.g., 7.0.0.0)')
        return v


class ReleaseResponse(BaseModel):
    """Response model for release."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    jenkins_job_url: Optional[str]
    is_active: bool
    created_at: datetime
    module_count: int


class SettingResponse(BaseModel):
    """Response model for app setting."""
    key: str
    value: str  # JSON-encoded
    description: Optional[str]
    updated_at: datetime


class TestcaseMetadataImportResponse(BaseModel):
    """Response model for testcase metadata import."""
    job_id: str
    status: str
    message: str


class TestcaseMetadataImportResult(BaseModel):
    """Response model for testcase metadata import results."""
    success: bool
    metadata_rows_imported: int
    test_results_updated: int
    import_timestamp: str
    csv_total_rows: int
    csv_filtered_rows: int
    invalid_priority_count: Optional[int] = 0


class TestcaseMetadataJobStatus(BaseModel):
    """Response model for import job status."""
    job_id: str
    status: str  # 'running', 'completed', 'failed'
    started_at: str
    completed_at: Optional[str]
    result: Optional[TestcaseMetadataImportResult]
    error: Optional[str]


class TestcaseMetadataStatusResponse(BaseModel):
    """Response model for testcase metadata import status."""
    last_import: Optional[str]
    total_metadata_records: int
    test_results_with_priority: int


class SyncReleaseResult(BaseModel):
    """Result for a single release sync operation."""
    release_name: str
    old_value: int
    new_value: int
    updated: bool


class SyncLastProcessedBuildsResponse(BaseModel):
    """Response model for sync last_processed_build operation."""
    message: str
    releases_processed: int
    updates_made: int
    results: List[SyncReleaseResult]


# Settings Endpoints

@router.get("/settings", response_model=List[SettingResponse])
@require_admin_pin
async def get_all_settings(request: Request, db: Session = Depends(get_db)):
    """
    Get all application settings.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        List of all settings
    """
    settings = db.query(AppSettings).all()

    return [
        SettingResponse(
            key=s.key,
            value=s.value,
            description=s.description,
            updated_at=s.updated_at
        )
        for s in settings
    ]


@router.get("/settings/{key}", response_model=SettingResponse)
@require_admin_pin
async def get_setting(request: Request, key: str, db: Session = Depends(get_db)):
    """
    Get a specific setting by key.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        db: Database session

    Returns:
        Setting value and metadata
    """
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at
    )


@router.put("/settings/{key}")
@require_admin_pin
async def update_setting(
    request: Request,
    key: str,
    update: SettingUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a setting value.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        update: New value (JSON-encoded)
        db: Database session

    Returns:
        Updated setting
    """
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Validate JSON
    try:
        json.loads(update.value)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Value must be valid JSON")

    # Update setting
    setting.value = update.value
    setting.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(setting)

    # If updating polling settings, update scheduler
    if key in ['AUTO_UPDATE_ENABLED', 'POLLING_INTERVAL_MINUTES', 'POLLING_INTERVAL_HOURS']:
        auto_update_setting = db.query(AppSettings).filter(
            AppSettings.key == 'AUTO_UPDATE_ENABLED'
        ).first()

        # Check for new POLLING_INTERVAL_HOURS setting first
        interval_setting = db.query(AppSettings).filter(
            AppSettings.key == 'POLLING_INTERVAL_HOURS'
        ).first()

        # Fallback to old POLLING_INTERVAL_MINUTES for backwards compatibility
        if not interval_setting:
            interval_setting = db.query(AppSettings).filter(
                AppSettings.key == 'POLLING_INTERVAL_MINUTES'
            ).first()

        auto_update_enabled = json.loads(auto_update_setting.value) if auto_update_setting else True

        # Convert minutes to hours if using old setting
        if interval_setting and interval_setting.key == 'POLLING_INTERVAL_MINUTES':
            interval_hours = json.loads(interval_setting.value) / 60.0
        else:
            interval_hours = float(json.loads(interval_setting.value)) if interval_setting else 12.0

        from app.tasks.scheduler import update_polling_schedule
        update_polling_schedule(auto_update_enabled, interval_hours)

    return {
        'key': setting.key,
        'value': setting.value,
        'description': setting.description,
        'updated_at': setting.updated_at,
        'message': 'Setting updated successfully'
    }


@router.post("/settings")
@require_admin_pin
async def create_setting(
    request: Request,
    key: str,
    update: SettingUpdate,
    description: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Create a new setting.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        update: Value (JSON-encoded)
        description: Setting description
        db: Database session

    Returns:
        Created setting
    """
    # Check if exists
    existing = db.query(AppSettings).filter(AppSettings.key == key).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Setting '{key}' already exists")

    # Validate JSON
    try:
        json.loads(update.value)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Value must be valid JSON")

    # Create setting
    setting = AppSettings(
        key=key,
        value=update.value,
        description=description
    )

    db.add(setting)
    db.commit()
    db.refresh(setting)

    return {
        'key': setting.key,
        'value': setting.value,
        'description': setting.description,
        'updated_at': setting.updated_at,
        'message': 'Setting created successfully'
    }


# Release Management Endpoints

@router.get("/releases", response_model=List[ReleaseResponse])
@require_admin_pin
async def get_all_releases(request: Request, db: Session = Depends(get_db)):
    """
    Get all releases with module counts.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        List of releases
    """
    releases = db.query(Release).all()

    return [
        ReleaseResponse(
            id=r.id,
            name=r.name,
            jenkins_job_url=r.jenkins_job_url,
            is_active=r.is_active,
            created_at=r.created_at,
            module_count=len(r.modules)
        )
        for r in releases
    ]


@router.get("/releases/{release_id}", response_model=ReleaseResponse)
@require_admin_pin
async def get_release(request: Request, release_id: int, db: Session = Depends(get_db)):
    """
    Get a specific release by ID.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        db: Database session

    Returns:
        Release details
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    return ReleaseResponse(
        id=release.id,
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active,
        created_at=release.created_at,
        module_count=len(release.modules)
    )


@router.post("/releases", response_model=ReleaseResponse)
@require_admin_pin
async def create_release(
    request: Request,
    release: ReleaseCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new release.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release: Release data
        db: Database session

    Returns:
        Created release
    """
    # Check if exists
    existing = db.query(Release).filter(Release.name == release.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Release '{release.name}' already exists"
        )

    # Create release
    new_release = Release(
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active
    )

    db.add(new_release)
    db.commit()
    db.refresh(new_release)

    return ReleaseResponse(
        id=new_release.id,
        name=new_release.name,
        jenkins_job_url=new_release.jenkins_job_url,
        is_active=new_release.is_active,
        created_at=new_release.created_at,
        module_count=0
    )


@router.put("/releases/{release_id}", response_model=ReleaseResponse)
@require_admin_pin
async def update_release(
    request: Request,
    release_id: int,
    update: ReleaseUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a release.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        update: Updated fields
        db: Database session

    Returns:
        Updated release
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    # Update fields
    if update.name is not None:
        # Check if new name conflicts
        existing = db.query(Release).filter(
            Release.name == update.name,
            Release.id != release_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Release '{update.name}' already exists"
            )
        release.name = update.name

    if update.jenkins_job_url is not None:
        release.jenkins_job_url = update.jenkins_job_url

    if update.is_active is not None:
        release.is_active = update.is_active

    release.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(release)

    return ReleaseResponse(
        id=release.id,
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active,
        created_at=release.created_at,
        module_count=len(release.modules)
    )


@router.delete("/releases/{release_id}")
@require_admin_pin
async def delete_release(request: Request, release_id: int, db: Session = Depends(get_db)):
    """
    Delete a release and all associated data (cascade).

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        db: Database session

    Returns:
        Deletion confirmation
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    release_name = release.name
    module_count = len(release.modules)

    # Delete release (cascades to modules, jobs, test_results)
    db.delete(release)
    db.commit()

    return {
        'message': f'Release {release_name} deleted successfully',
        'modules_deleted': module_count
    }


@router.post("/releases/sync-last-processed-builds", response_model=SyncLastProcessedBuildsResponse)
@require_admin_pin
async def sync_last_processed_builds(request: Request, db: Session = Depends(get_db)):
    """
    Sync last_processed_build field for all releases with actual max builds in database.

    This endpoint fixes the issue where last_processed_build is out of sync with
    the actual jobs in the database (e.g., after manual imports or migrations).

    For each release, queries the maximum parent_job_id from the jobs table
    and updates last_processed_build if it differs.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        Sync results showing old vs new values for each release
    """
    logger.info("Starting last_processed_build sync for all releases")

    releases = db.query(Release).all()

    if not releases:
        return SyncLastProcessedBuildsResponse(
            message="No releases found in database",
            releases_processed=0,
            updates_made=0,
            results=[]
        )

    results = []
    updates_made = 0

    for release in releases:
        # Query max parent_job_id for this release
        # parent_job_id is stored as String, so we need to cast to Integer
        max_parent_job = db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(
            Module
        ).filter(
            Module.release_id == release.id
        ).scalar()

        old_value = release.last_processed_build or 0

        if max_parent_job is not None and max_parent_job != old_value:
            release.last_processed_build = max_parent_job
            updates_made += 1
            updated = True
            logger.info(f"Release {release.name}: {old_value} → {max_parent_job}")
        else:
            updated = False
            new_value = max_parent_job if max_parent_job is not None else old_value
            logger.debug(f"Release {release.name}: {old_value} (no change)")

        results.append(SyncReleaseResult(
            release_name=release.name,
            old_value=old_value,
            new_value=max_parent_job if max_parent_job is not None else old_value,
            updated=updated
        ))

    # Commit all changes
    db.commit()

    logger.info(f"Sync completed: {updates_made} updates made out of {len(releases)} releases")

    return SyncLastProcessedBuildsResponse(
        message=f"Sync completed successfully. Updated {updates_made} release(s).",
        releases_processed=len(releases),
        updates_made=updates_made,
        results=results
    )


# Testcase Metadata Background Worker

def _run_import_in_background(job_id: str):
    """
    Background worker for testcase metadata import.

    Args:
        job_id: Unique job identifier
    """
    from app.database import SessionLocal

    logger.info(f"[Job {job_id}] Starting background import")

    # Update job status to running
    with _import_jobs_lock:
        if job_id in _import_jobs:
            _import_jobs[job_id]['status'] = 'running'

    try:
        # Create new DB session for background thread
        db = SessionLocal()

        try:
            # Run import
            result = testcase_metadata_service.import_testcase_metadata(
                db=db,
                job_id=job_id
            )

            # Update job with success
            with _import_jobs_lock:
                if job_id in _import_jobs:
                    _import_jobs[job_id]['status'] = 'completed'
                    _import_jobs[job_id]['completed_at'] = datetime.now().isoformat()
                    _import_jobs[job_id]['result'] = result

            logger.info(f"[Job {job_id}] Import completed successfully")

        finally:
            db.close()

    except FileNotFoundError as e:
        error_msg = str(e)
        logger.error(f"[Job {job_id}] CSV file not found: {error_msg}")

        with _import_jobs_lock:
            if job_id in _import_jobs:
                _import_jobs[job_id]['status'] = 'failed'
                _import_jobs[job_id]['completed_at'] = datetime.now().isoformat()
                _import_jobs[job_id]['error'] = f"CSV file not found: {error_msg}"

    except ValueError as e:
        error_msg = str(e)
        logger.error(f"[Job {job_id}] Validation error: {error_msg}")

        with _import_jobs_lock:
            if job_id in _import_jobs:
                _import_jobs[job_id]['status'] = 'failed'
                _import_jobs[job_id]['completed_at'] = datetime.now().isoformat()
                _import_jobs[job_id]['error'] = f"Validation error: {error_msg}"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Job {job_id}] Import failed: {error_msg}", exc_info=True)

        with _import_jobs_lock:
            if job_id in _import_jobs:
                _import_jobs[job_id]['status'] = 'failed'
                _import_jobs[job_id]['completed_at'] = datetime.now().isoformat()
                _import_jobs[job_id]['error'] = error_msg


# Testcase Metadata Endpoints

@router.get("/testcase-metadata/status", response_model=TestcaseMetadataStatusResponse)
@require_admin_pin
async def get_testcase_metadata_status(request: Request, db: Session = Depends(get_db)):
    """
    Get testcase metadata import status.

    Returns information about the last import, including timestamp,
    total metadata records, and count of test results with priority assigned.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object (required by decorator)
        db: Database session

    Returns:
        Import status information
    """
    status = testcase_metadata_service.get_import_status(db)

    if not status:
        # Never imported
        return TestcaseMetadataStatusResponse(
            last_import=None,
            total_metadata_records=0,
            test_results_with_priority=0
        )

    return TestcaseMetadataStatusResponse(**status)


@router.post("/testcase-metadata/import", response_model=TestcaseMetadataImportResponse)
@require_admin_pin
async def import_testcase_metadata(request: Request):
    """
    Trigger testcase metadata import from CSV file as a background job.

    This endpoint starts an async import process that:
    1. Reads and validates the CSV file (data/testcase_list/hapy_automated.csv)
    2. Imports metadata into testcase_metadata table
    3. Backfills priority into test_results table
    4. Updates import status

    The import runs in the background. Use the GET /testcase-metadata/import/{job_id}
    endpoint to check job status and retrieve results.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object (required by decorator)

    Returns:
        Job ID and status

    Raises:
        HTTPException: If another import is already running
    """
    # Check if an import is already running
    with _import_jobs_lock:
        running_jobs = [
            job_id for job_id, job in _import_jobs.items()
            if job['status'] == 'running'
        ]

        if running_jobs:
            raise HTTPException(
                status_code=409,
                detail=f"Import already in progress (job_id: {running_jobs[0]}). "
                       f"Please wait for it to complete or check status."
            )

    # Create new job
    job_id = str(uuid.uuid4())

    with _import_jobs_lock:
        _import_jobs[job_id] = {
            'job_id': job_id,
            'status': 'pending',
            'started_at': datetime.now().isoformat(),
            'completed_at': None,
            'result': None,
            'error': None
        }

    # Submit to executor
    _executor.submit(_run_import_in_background, job_id)

    logger.info(f"[Job {job_id}] Import job submitted to background executor")

    return TestcaseMetadataImportResponse(
        job_id=job_id,
        status='pending',
        message='Import started in background. Use GET /testcase-metadata/import/{job_id} to check status.'
    )


@router.get("/testcase-metadata/import/{job_id}", response_model=TestcaseMetadataJobStatus)
@require_admin_pin
async def get_import_job_status(request: Request, job_id: str):
    """
    Get status of a testcase metadata import job.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object (required by decorator)
        job_id: Job ID returned from import endpoint

    Returns:
        Job status and results if completed

    Raises:
        HTTPException: If job_id not found
    """
    with _import_jobs_lock:
        if job_id not in _import_jobs:
            raise HTTPException(
                status_code=404,
                detail=f"Job {job_id} not found"
            )

        job = _import_jobs[job_id].copy()

    # Convert result dict to Pydantic model if present
    if job['result']:
        job['result'] = TestcaseMetadataImportResult(**job['result'])

    return TestcaseMetadataJobStatus(**job)
