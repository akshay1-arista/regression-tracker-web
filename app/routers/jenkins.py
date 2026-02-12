"""
Jenkins API Router.

Provides endpoints for manual Jenkins downloads and progress streaming via SSE.
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Dict, Optional, Callable

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Release, Module, Job, AppSettings, TestResult
from app.services.jenkins_service import (
    JenkinsClient,
    ArtifactDownloader,
    parse_build_map,
    extract_version_from_title
)
from app.services.import_service import ImportService
from app.config import get_settings
from app.utils.security import require_admin_pin
from concurrent.futures import ThreadPoolExecutor, as_completed


logger = logging.getLogger(__name__)
router = APIRouter()

# Job tracker (Redis-backed or in-memory fallback)
from app.utils.job_tracker import get_job_tracker


class DownloadRequest(BaseModel):
    """Request model for manual Jenkins download."""
    release: Optional[str] = None  # If not provided, will be extracted from job_url
    job_url: str
    skip_existing: bool = True


class PollingToggleRequest(BaseModel):
    """Request model for toggling polling."""
    enabled: bool


class DiscoveredMainJob(BaseModel):
    """Model for a discovered main job build from Jenkins."""
    key: str  # Unique identifier: "release/build_number"
    release: str
    release_id: int
    build_number: int
    build_url: str
    jenkins_job_url: str  # Release job URL


class DiscoverJobsResponse(BaseModel):
    """Response model for job discovery."""
    jobs: list[DiscoveredMainJob]
    total: int


class DownloadSelectedRequest(BaseModel):
    """Request model for downloading selected jobs."""
    jobs: list[DiscoveredMainJob]


@router.post("/download")
async def trigger_download(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Trigger manual Jenkins download.

    Args:
        request: Download request parameters
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        Job ID for tracking progress
    """
    # Extract release from URL if not provided
    release = request.release
    if not release:
        release = extract_release_from_url(request.job_url)
        if not release:
            raise HTTPException(
                status_code=400,
                detail="Could not extract release from job URL. Please provide release explicitly or use a URL with pattern: .../QA_Release_X.X/..."
            )

    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Store job info in tracker
    tracker = get_job_tracker()
    tracker.set_job(job_id, {
        'id': job_id,
        'release': release,
        'job_url': request.job_url,
        'status': 'pending',
        'started_at': datetime.utcnow().isoformat(),
        'completed_at': None,
        'error': None
    })

    # Start background task
    background_tasks.add_task(
        run_download,
        job_id,
        release,
        request.job_url,
        request.skip_existing,
        db
    )

    return {
        'job_id': job_id,
        'message': 'Download started',
        'logs_url': f'/api/v1/jenkins/download/{job_id}'
    }


@router.get("/download/{job_id}")
async def stream_download_logs(job_id: str):
    """
    Stream download progress logs via Server-Sent Events.

    Args:
        job_id: Download job ID

    Returns:
        SSE stream of log messages
    """
    tracker = get_job_tracker()

    if not tracker.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        """Generate SSE events from log queue with heartbeat."""
        import time
        last_heartbeat = time.time()
        heartbeat_interval = 30  # Send heartbeat every 30 seconds

        while True:
            job = tracker.get_job(job_id)

            if not job:
                break

            # Try to get log message (blocking with timeout)
            log_message = tracker.pop_log(job_id, timeout=0.5)

            if log_message:
                yield f"data: {json.dumps({'message': log_message})}\n\n"
                last_heartbeat = time.time()  # Reset heartbeat timer
            else:
                # No message available, check if job is done
                if job['status'] in ['completed', 'failed']:
                    # Send final status
                    yield f"data: {json.dumps({'status': job['status'], 'error': job.get('error')})}\n\n"
                    break

                # Send heartbeat to keep connection alive
                current_time = time.time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    last_heartbeat = current_time

            await asyncio.sleep(0.1)

        # Cleanup (tracker handles cleanup internally)
        tracker.delete_job(job_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )


@router.get("/download/{job_id}/status")
async def get_download_status(job_id: str):
    """
    Get current status of a download job.

    Args:
        job_id: Download job ID

    Returns:
        Job status information
    """
    tracker = get_job_tracker()
    job = tracker.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.delete("/download/{job_id}")
async def cleanup_download_job(job_id: str):
    """
    Explicitly cleanup a completed or failed download job.

    This endpoint allows manual cleanup of job data and logs.
    Jobs are also automatically cleaned up via TTL (24 hours for jobs, 1 hour for logs).

    Args:
        job_id: Download job ID

    Returns:
        Success message
    """
    tracker = get_job_tracker()

    # Check if job exists before deleting
    job = tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Only allow cleanup of completed or failed jobs
    if job.get('status') not in ['completed', 'failed']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cleanup job in '{job.get('status')}' status. Only completed or failed jobs can be cleaned up."
        )

    # Delete the job
    tracker.delete_job(job_id)

    return {
        "message": f"Job {job_id} cleaned up successfully",
        "job_id": job_id
    }


@router.get("/polling/status")
async def get_polling_status(db: Session = Depends(get_db)):
    """
    Get current polling configuration and status.

    Args:
        db: Database session

    Returns:
        Polling status information
    """
    # Get settings from database
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

    auto_update_enabled = True
    if auto_update_setting:
        auto_update_enabled = json.loads(auto_update_setting.value)

    # Convert minutes to hours if using old setting
    if interval_setting and interval_setting.key == 'POLLING_INTERVAL_MINUTES':
        interval_hours = json.loads(interval_setting.value) / 60.0
    else:
        interval_hours = float(json.loads(interval_setting.value)) if interval_setting else 12.0

    # Get scheduler status
    from app.tasks.scheduler import get_scheduler_status
    scheduler_status = get_scheduler_status()

    return {
        'enabled': auto_update_enabled,
        'interval_hours': interval_hours,
        'scheduler': scheduler_status
    }


@router.post("/polling/toggle")
async def toggle_polling(
    request: PollingToggleRequest,
    db: Session = Depends(get_db)
):
    """
    Enable or disable automatic polling.

    Args:
        request: Toggle request
        db: Database session

    Returns:
        Updated polling status
    """
    # Update database setting
    auto_update_setting = db.query(AppSettings).filter(
        AppSettings.key == 'AUTO_UPDATE_ENABLED'
    ).first()

    if auto_update_setting:
        auto_update_setting.value = json.dumps(request.enabled)
        auto_update_setting.updated_at = datetime.utcnow()
    else:
        auto_update_setting = AppSettings(
            key='AUTO_UPDATE_ENABLED',
            value=json.dumps(request.enabled),
            description='Enable automatic Jenkins polling'
        )
        db.add(auto_update_setting)

    db.commit()

    # Get interval - check for new POLLING_INTERVAL_HOURS setting first
    interval_setting = db.query(AppSettings).filter(
        AppSettings.key == 'POLLING_INTERVAL_HOURS'
    ).first()

    # Fallback to old POLLING_INTERVAL_MINUTES for backwards compatibility
    if not interval_setting:
        interval_setting = db.query(AppSettings).filter(
            AppSettings.key == 'POLLING_INTERVAL_MINUTES'
        ).first()

    # Convert minutes to hours if using old setting
    if interval_setting and interval_setting.key == 'POLLING_INTERVAL_MINUTES':
        interval_hours = json.loads(interval_setting.value) / 60.0
    else:
        interval_hours = float(json.loads(interval_setting.value)) if interval_setting else 12.0

    # Update scheduler
    from app.tasks.scheduler import update_polling_schedule
    update_polling_schedule(request.enabled, interval_hours)

    return {
        'enabled': request.enabled,
        'interval_hours': interval_hours,
        'message': f'Polling {"enabled" if request.enabled else "disabled"}'
    }


@router.post("/discover-jobs", response_model=DiscoverJobsResponse)
@require_admin_pin
async def discover_available_jobs(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Discover new main job builds from Jenkins for all active releases.

    Fetches main job builds that are after last_processed_build for each release.

    Args:
        db: Database session

    Returns:
        List of discovered main job builds
    """
    discovered = []

    try:
        # Get Jenkins credentials from environment variables (secure)
        from app.utils.security import CredentialsManager

        try:
            jenkins_url, jenkins_user, jenkins_token = CredentialsManager.get_jenkins_credentials()
        except ValueError as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Get all active releases
        active_releases = db.query(Release).filter(Release.is_active == True).all()

        if not active_releases:
            logger.info("No active releases found")
            return DiscoverJobsResponse(jobs=[], total=0)

        # Create Jenkins client
        with JenkinsClient(jenkins_url, jenkins_user, jenkins_token) as client:
            for release in active_releases:
                try:
                    if not release.jenkins_job_url:
                        logger.warning(f"Release {release.name} has no Jenkins job URL configured")
                        continue

                    # Get builds after last_processed_build
                    min_build = release.last_processed_build or 0
                    builds = client.get_job_builds(release.jenkins_job_url, min_build=min_build)

                    if not builds:
                        logger.info(f"No new builds found for {release.name} (last processed: {min_build})")
                        continue

                    logger.info(f"Found {len(builds)} new main builds for {release.name}")

                    # Add each main build to discovered list
                    for build_number in builds:
                        build_url = f"{release.jenkins_job_url.rstrip('/')}/{build_number}/"

                        discovered.append(DiscoveredMainJob(
                            key=f"{release.name}/{build_number}",
                            release=release.name,
                            release_id=release.id,
                            build_number=build_number,
                            build_url=build_url,
                            jenkins_job_url=release.jenkins_job_url
                        ))

                except Exception as e:
                    logger.error(f"Error discovering jobs for {release.name}: {e}")
                    continue

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in job discovery: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(f"Discovered {len(discovered)} new main builds")
    return DiscoverJobsResponse(jobs=discovered, total=len(discovered))


@router.post("/download-selected")
@require_admin_pin
async def download_selected_jobs(
    request: Request,
    req_body: DownloadSelectedRequest,
    background_tasks: BackgroundTasks
):
    """
    Download and import selected jobs.

    Args:
        request: HTTP request for authentication
        req_body: Download request with selected jobs
        background_tasks: FastAPI background tasks

    Returns:
        Job ID for tracking progress via SSE
    """
    if not req_body.jobs:
        raise HTTPException(status_code=400, detail="No jobs selected")

    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Store job info in tracker
    tracker = get_job_tracker()
    tracker.set_job(job_id, {
        'id': job_id,
        'type': 'on-demand',
        'status': 'pending',
        'jobs': [j.model_dump() for j in req_body.jobs],
        'started_at': datetime.utcnow().isoformat(),
        'completed_at': None,
        'error': None
    })

    # Start background task
    background_tasks.add_task(
        run_selected_download,
        job_id,
        req_body.jobs
    )

    return {
        'job_id': job_id,
        'message': f'Download started for {len(req_body.jobs)} builds',
        'logs_url': f'/api/v1/jenkins/download-selected/{job_id}'
    }


@router.get("/download-selected/{job_id}")
async def stream_selected_download_logs(job_id: str):
    """
    Stream download progress logs for selected jobs via Server-Sent Events.

    Args:
        job_id: Download job ID

    Returns:
        SSE stream of log messages
    """
    tracker = get_job_tracker()

    if not tracker.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        """Generate SSE events from log queue with heartbeat."""
        import time
        last_heartbeat = time.time()
        heartbeat_interval = 30  # Send heartbeat every 30 seconds

        while True:
            job = tracker.get_job(job_id)

            if not job:
                break

            # Try to get log message (blocking with timeout)
            log_message = tracker.pop_log(job_id, timeout=0.5)

            if log_message:
                yield f"data: {json.dumps({'message': log_message, 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                last_heartbeat = time.time()  # Reset heartbeat timer
            else:
                # No message available, check if job is done
                if job['status'] in ['completed', 'failed']:
                    # Send final status
                    yield f"data: {json.dumps({'status': job['status'], 'error': job.get('error')})}\n\n"
                    yield f"event: complete\ndata: {json.dumps({'status': job['status']})}\n\n"
                    break

                # Send heartbeat to keep connection alive
                current_time = time.time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    last_heartbeat = current_time

            await asyncio.sleep(0.1)

        # Cleanup (tracker handles cleanup internally)
        tracker.delete_job(job_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )


def extract_release_from_url(job_url: str) -> Optional[str]:
    """
    Extract release name from Jenkins job URL.

    Args:
        job_url: Jenkins job URL (e.g., .../QA_Release_6.4/job/...)

    Returns:
        Release name (e.g., "6.4") or None if not found

    Example:
        >>> extract_release_from_url("https://.../QA_Release_6.4/job/.../216/")
        "6.4"
    """
    match = re.search(r'/QA_Release_([0-9.]+)/', job_url)
    return match.group(1) if match else None


def run_download(
    job_id: str,
    release: str,
    job_url: str,
    skip_existing: bool,
    db: Session
):
    """
    Run download in background task.

    Args:
        job_id: Download job ID
        release: Release name
        job_url: Jenkins job URL
        skip_existing: Skip existing files
        db: Database session
    """
    tracker = get_job_tracker()

    def log_callback(message: str):
        """Log to queue for SSE streaming."""
        try:
            tracker.push_log(job_id, message)
        except Exception as e:
            # Log push failed, but still log to terminal
            logger.warning(f"[{job_id}] Failed to push log to SSE queue: {e}")
        finally:
            # Always log to terminal (this is what users see in server logs)
            logger.info(f"[{job_id}] {message}")

    try:
        log_callback(f"Starting download for release {release}")

        # Update job status atomically
        tracker.update_job_field(job_id, 'status', 'running')

        # Get Jenkins credentials from environment variables (secure)
        from app.utils.security import CredentialsManager
        settings = get_settings()

        try:
            jenkins_url, jenkins_user, jenkins_token = CredentialsManager.get_jenkins_credentials()
        except ValueError as e:
            raise Exception(str(e))

        # Create Jenkins client
        with JenkinsClient(jenkins_url, jenkins_user, jenkins_token) as client:
            # Download build_map to get list of modules
            log_callback(f"Downloading build_map.json...")
            build_map = client.download_build_map(job_url)
            if not build_map:
                raise Exception("Failed to download build_map.json")

            # Parse module jobs from build_map
            module_jobs = parse_build_map(build_map, job_url)
            log_callback(f"Found {len(module_jobs)} modules to process")

            # Extract parent job ID from main job URL
            # Example URL: .../job/MODULE-RUN-ESXI-IPV4-ALL/216/
            parent_job_id = None
            parent_match = re.search(r'/(\d+)/?$', job_url.rstrip('/'))
            if parent_match:
                parent_job_id = parent_match.group(1)
                log_callback(f"Extracted parent job ID: {parent_job_id}")

            # Extract base Jenkins job URL (without build number) for releases table
            # Example: .../MODULE-RUN-ESXI-IPV4-ALL/216/ -> .../MODULE-RUN-ESXI-IPV4-ALL/
            base_jenkins_url = re.sub(r'/\d+/?$', '/', job_url.rstrip('/'))

            # Update release's jenkins_job_url if not already set
            release_obj = db.query(Release).filter(Release.name == release).first()
            if release_obj and not release_obj.jenkins_job_url:
                release_obj.jenkins_job_url = base_jenkins_url
                db.commit()
                log_callback(f"Updated release {release} with Jenkins job URL")

            # Create downloader and import service
            downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH, log_callback)
            import_service = ImportService(db)

            # Process each module: download -> import -> cleanup
            success_count = 0
            skipped_count = 0
            for module_name, (module_job_url, module_job_id) in module_jobs.items():
                try:
                    # Check if job already exists in database to skip unnecessary download
                    existing_job = db.query(Job).join(Module).join(Release).filter(
                        Release.name == release,
                        Module.name == module_name,
                        Job.job_id == module_job_id
                    ).first()

                    if existing_job:
                        existing_count = db.query(TestResult).filter(TestResult.job_id == existing_job.id).count()
                        if existing_count > 0:
                            log_callback(f"  Skipping {module_name} (job {module_job_id}) - already in database ({existing_count} test results)")
                            skipped_count += 1
                            success_count += 1  # Count as success since data exists
                            continue

                    # Extract version and timestamp from module job info (if available)
                    version = None
                    executed_at = None
                    try:
                        job_info = client.get_job_info(module_job_url)
                        version = extract_version_from_title(job_info.get('displayName', ''))
                        if version:
                            log_callback(f"  Extracted version {version} for {module_name}")

                        # Extract Jenkins execution timestamp (milliseconds since epoch)
                        timestamp_ms = job_info.get('timestamp')
                        if timestamp_ms:
                            from datetime import datetime
                            executed_at = datetime.utcfromtimestamp(timestamp_ms / 1000)
                            log_callback(f"  Extracted execution time: {executed_at.isoformat()}")
                    except Exception as e:
                        log_callback(f"  Could not extract metadata for {module_name}: {e}")

                    # Download this module's artifacts
                    result = downloader._download_module_artifacts(
                        module_name,
                        module_job_url,
                        module_job_id,
                        release,
                        skip_existing
                    )

                    if not result:
                        log_callback(f"  Skipped or failed: {module_name}")
                        continue

                    # Import to database immediately with complete metadata
                    log_callback(f"  Importing {module_name} to database...")
                    import_service.import_job(
                        release,
                        module_name,
                        module_job_id,
                        jenkins_url=module_job_url,
                        version=version,
                        parent_job_id=parent_job_id,
                        executed_at=executed_at
                    )
                    db.commit()  # Commit immediately to persist data even if worker is killed later
                    log_callback(f"  Imported {module_name} successfully")

                    # Cleanup artifacts immediately to save disk space
                    if settings.CLEANUP_ARTIFACTS_AFTER_IMPORT:
                        log_callback(f"  Cleaning up artifacts for {module_name}...")
                        from app.utils.cleanup import cleanup_artifacts
                        cleanup_artifacts(settings.LOGS_BASE_PATH, release, module_name, module_job_id)

                    success_count += 1

                except Exception as e:
                    db.rollback()  # Rollback failed transaction
                    log_callback(f"  ERROR processing {module_name}: {e}")
                    logger.error(f"Failed to process {module_name}: {e}", exc_info=True)

            if skipped_count > 0:
                log_callback(f"Download completed: {success_count}/{len(module_jobs)} modules succeeded ({skipped_count} already in database)")
            else:
                log_callback(f"Download completed: {success_count}/{len(module_jobs)} modules succeeded")

        # Update job status atomically
        tracker.update_job_fields(job_id, {
            'status': 'completed',
            'completed_at': datetime.utcnow().isoformat()
        })

        log_callback("All done!")

    except Exception as e:
        logger.error(f"Download job {job_id} failed: {e}", exc_info=True)

        # Update job status atomically
        tracker.update_job_fields(job_id, {
            'status': 'failed',
            'completed_at': datetime.utcnow().isoformat(),
            'error': str(e)
        })

        log_callback(f"ERROR: {e}")


def _download_and_import_module(
    downloader: ArtifactDownloader,
    release: str,
    module_name: str,
    job_url: str,
    job_id: str,
    version: str,
    build_number: int,
    log_callback: Callable[[str], None]
) -> bool:
    """
    Download and import a single module (called in parallel).

    Args:
        downloader: ArtifactDownloader instance
        release: Release name
        module_name: Module name
        job_url: Jenkins job URL
        job_id: Job ID
        version: Version string
        build_number: Main build number
        log_callback: Logging callback

    Returns:
        True if successful, False otherwise
    """
    from app.database import get_db_context

    # Create thread-local database session for this worker
    with get_db_context() as db:
        try:
            # Check if job already exists in database to skip unnecessary download
            existing_job = db.query(Job).join(Module).join(Release).filter(
                Release.name == release,
                Module.name == module_name,
                Job.job_id == job_id
            ).first()

            if existing_job:
                existing_count = db.query(TestResult).filter(TestResult.job_id == existing_job.id).count()
                if existing_count > 0:
                    log_callback(f"      Skipping {module_name} job {job_id} - already in database ({existing_count} test results)")
                    return True  # Return True as this is a "success" (data already exists)

            # Download artifacts
            log_callback(f"    Downloading {module_name} job {job_id}...")
            result = downloader._download_module_artifacts(
                module_name,
                job_url,
                job_id,
                release,
                skip_existing=False
            )

            if not result:
                log_callback(f"      Download failed for {module_name}")
                return False

            # Import to database
            log_callback(f"      Importing {module_name} job {job_id}...")
            import_service = ImportService(db)
            import_service.import_job(
                release,
                module_name,
                job_id,
                jenkins_url=job_url,
                version=version,
                parent_job_id=str(build_number)
            )
            db.commit()  # Commit immediately to persist data even if worker is killed later

            # Cleanup artifacts after successful import to save disk space
            from app.config import get_settings
            settings = get_settings()
            if settings.CLEANUP_ARTIFACTS_AFTER_IMPORT:
                log_callback(f"      Cleaning up artifacts for {module_name}...")
                from app.utils.cleanup import cleanup_artifacts
                cleanup_artifacts(downloader.logs_base, release, module_name, job_id)

            return True

        except Exception as e:
            db.rollback()  # Rollback failed transaction
            log_callback(f"      ERROR: {module_name} job {job_id}: {e}")
            logger.error(f"Failed to download/import {module_name}: {e}", exc_info=True)
            return False


def run_selected_download(
    job_id: str,
    main_jobs: list[DiscoveredMainJob]
):
    """
    Run selected download in background task.

    Downloads all module artifacts from selected main builds in parallel,
    imports to database, and updates last_processed_build tracker.

    Args:
        job_id: Download job ID for tracking
        main_jobs: List of main job builds to download
    """
    from app.database import get_db_context

    tracker = get_job_tracker()

    def log_callback(message: str):
        """Log to queue for SSE streaming."""
        try:
            tracker.push_log(job_id, message)
        except Exception as e:
            # Log push failed, but still log to terminal
            logger.warning(f"[{job_id}] Failed to push log to SSE queue: {e}")
        finally:
            # Always log to terminal (this is what users see in server logs)
            logger.info(f"[{job_id}] {message}")

    # Create database session for this background task
    with get_db_context() as db:
        try:
            log_callback(f"Starting on-demand download for {len(main_jobs)} main builds")

            # Update job status atomically
            tracker.update_job_field(job_id, 'status', 'running')

            # Get Jenkins credentials from environment variables (secure)
            from app.utils.security import CredentialsManager

            try:
                jenkins_url, jenkins_user, jenkins_token = CredentialsManager.get_jenkins_credentials()
            except ValueError as e:
                raise Exception(str(e))

            # Get logs base path
            settings = get_settings()

            # Track successes for updating last_processed_build
            # Map: release_name -> list of successfully imported build numbers
            success_builds_by_release = {}

            # Create Jenkins client and downloader
            with JenkinsClient(jenkins_url, jenkins_user, jenkins_token) as client:
                downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH, log_callback)

                # Process each main build
                for main_job in main_jobs:
                    log_callback(f"\nProcessing {main_job.release} build #{main_job.build_number}...")

                    try:
                        # Download build_map.json
                        build_map = client.download_build_map(main_job.build_url)
                        if not build_map:
                            log_callback(f"  ERROR: No build_map found for build #{main_job.build_number}")
                            continue

                        # Parse module jobs from build_map
                        module_jobs = parse_build_map(build_map, main_job.build_url)
                        log_callback(f"  Found {len(module_jobs)} modules to download (parallel mode)")

                        # Download and import all modules from this build IN PARALLEL
                        module_success_count = 0

                        # Create download tasks for parallel execution
                        with ThreadPoolExecutor(max_workers=5) as executor:
                            futures = {}

                            for module_name, (job_url, job_id) in module_jobs.items():
                                # Get version from Jenkins (do this before parallel download)
                                version = None
                                try:
                                    job_info = client.get_job_info(job_url)
                                    version = extract_version_from_title(
                                        job_info.get('displayName', '')
                                    )
                                except:
                                    pass

                                # Submit download task
                                future = executor.submit(
                                    _download_and_import_module,
                                    downloader,
                                    main_job.release,
                                    module_name,
                                    job_url,
                                    job_id,
                                    version,
                                    main_job.build_number,
                                    log_callback
                                )
                                futures[future] = module_name

                            # Log immediate feedback after task submission
                            log_callback(f"  Submitted {len(futures)} download tasks to parallel executor")
                            log_callback(f"  Waiting for downloads to complete...")

                            # Wait for all downloads to complete
                            completed_count = 0
                            for future in as_completed(futures):
                                module_name = futures[future]
                                completed_count += 1
                                try:
                                    success = future.result()
                                    if success:
                                        module_success_count += 1
                                        log_callback(f"    [{completed_count}/{len(futures)}] ✓ {module_name} completed successfully")
                                    else:
                                        log_callback(f"    [{completed_count}/{len(futures)}] ✗ {module_name} failed")
                                except Exception as e:
                                    log_callback(f"    [{completed_count}/{len(futures)}] ERROR: {module_name}: {e}")
                                    logger.error(f"Failed to download/import {module_name}: {e}", exc_info=True)

                        # If at least one module succeeded, track this build
                        if module_success_count > 0:
                            if main_job.release not in success_builds_by_release:
                                success_builds_by_release[main_job.release] = []
                            success_builds_by_release[main_job.release].append(main_job.build_number)
                            log_callback(f"  Completed build #{main_job.build_number}: {module_success_count}/{len(module_jobs)} modules succeeded")
                        else:
                            log_callback(f"  Build #{main_job.build_number} failed - no modules imported")

                    except Exception as e:
                        log_callback(f"  ERROR processing build #{main_job.build_number}: {e}")
                        logger.error(f"Error processing build {main_job.build_number}: {e}", exc_info=True)

            # Update last_processed_build for each release
            log_callback("\nUpdating last_processed_build tracker...")
            for release_name, build_numbers in success_builds_by_release.items():
                try:
                    release = db.query(Release).filter(Release.name == release_name).first()
                    if release:
                        highest_build = max(build_numbers)
                        new_last_processed = max(
                            release.last_processed_build or 0,
                            highest_build
                        )
                        release.last_processed_build = new_last_processed
                        db.commit()
                        log_callback(f"  Updated {release_name} last_processed_build to {new_last_processed}")
                except Exception as e:
                    log_callback(f"  ERROR updating tracker for {release_name}: {e}")
                    logger.error(f"Error updating last_processed_build for {release_name}: {e}")
                    db.rollback()

            # Update job status atomically
            tracker.update_job_fields(job_id, {
                'status': 'completed',
                'completed_at': datetime.utcnow().isoformat()
            })

            total_builds = len(main_jobs)
            success_builds = sum(len(builds) for builds in success_builds_by_release.values())
            log_callback(f"\n✓ Download completed: {success_builds}/{total_builds} builds succeeded")

        except Exception as e:
            logger.error(f"Selected download job {job_id} failed: {e}", exc_info=True)

            # Update job status atomically
            tracker.update_job_fields(job_id, {
                'status': 'failed',
                'completed_at': datetime.utcnow().isoformat(),
                'error': str(e)
            })

            log_callback(f"FATAL ERROR: {e}")


