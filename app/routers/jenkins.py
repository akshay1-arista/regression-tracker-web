"""
Jenkins API Router.

Provides endpoints for manual Jenkins downloads and progress streaming via SSE.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional
from queue import Queue, Empty

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Release, Module, AppSettings
from app.services.jenkins_service import JenkinsClient, ArtifactDownloader
from app.services.import_service import ImportService
from app.config import get_settings


logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory storage for download jobs
download_jobs: Dict[str, Dict] = {}
log_queues: Dict[str, Queue] = {}


class DownloadRequest(BaseModel):
    """Request model for manual Jenkins download."""
    release: str
    job_url: str
    skip_existing: bool = True


class PollingToggleRequest(BaseModel):
    """Request model for toggling polling."""
    enabled: bool


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
    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Create log queue for this job
    log_queues[job_id] = Queue()

    # Store job info
    download_jobs[job_id] = {
        'id': job_id,
        'release': request.release,
        'job_url': request.job_url,
        'status': 'pending',
        'started_at': datetime.utcnow().isoformat(),
        'completed_at': None,
        'error': None
    }

    # Start background task
    background_tasks.add_task(
        run_download,
        job_id,
        request.release,
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
    if job_id not in download_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        """Generate SSE events from log queue."""
        log_queue = log_queues.get(job_id)

        if not log_queue:
            yield f"data: {json.dumps({'error': 'Log queue not found'})}\n\n"
            return

        while True:
            job = download_jobs.get(job_id)

            if not job:
                break

            # Try to get log message (non-blocking)
            try:
                log_message = log_queue.get(timeout=0.5)
                yield f"data: {json.dumps({'message': log_message})}\n\n"
            except Empty:
                # No message available, check if job is done
                if job['status'] in ['completed', 'failed']:
                    # Send final status
                    yield f"data: {json.dumps({'status': job['status'], 'error': job.get('error')})}\n\n"
                    break

            await asyncio.sleep(0.1)

        # Cleanup
        if job_id in log_queues:
            del log_queues[job_id]

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
    if job_id not in download_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return download_jobs[job_id]


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

    interval_setting = db.query(AppSettings).filter(
        AppSettings.key == 'POLLING_INTERVAL_MINUTES'
    ).first()

    auto_update_enabled = True
    if auto_update_setting:
        auto_update_enabled = json.loads(auto_update_setting.value)

    interval_minutes = 15
    if interval_setting:
        interval_minutes = json.loads(interval_setting.value)

    # Get scheduler status
    from app.tasks.scheduler import get_scheduler_status
    scheduler_status = get_scheduler_status()

    return {
        'enabled': auto_update_enabled,
        'interval_minutes': interval_minutes,
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

    # Get interval
    interval_setting = db.query(AppSettings).filter(
        AppSettings.key == 'POLLING_INTERVAL_MINUTES'
    ).first()

    interval_minutes = 15
    if interval_setting:
        interval_minutes = json.loads(interval_setting.value)

    # Update scheduler
    from app.tasks.scheduler import update_polling_schedule
    update_polling_schedule(request.enabled, interval_minutes)

    return {
        'enabled': request.enabled,
        'interval_minutes': interval_minutes,
        'message': f'Polling {"enabled" if request.enabled else "disabled"}'
    }


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
    def log_callback(message: str):
        """Log to queue for SSE streaming."""
        if job_id in log_queues:
            log_queues[job_id].put(message)
        logger.info(f"[{job_id}] {message}")

    try:
        log_callback(f"Starting download for release {release}")

        # Update job status
        download_jobs[job_id]['status'] = 'running'

        # Get Jenkins credentials
        settings = get_settings()

        jenkins_url_setting = db.query(AppSettings).filter(
            AppSettings.key == 'JENKINS_URL'
        ).first()
        jenkins_user_setting = db.query(AppSettings).filter(
            AppSettings.key == 'JENKINS_USER'
        ).first()
        jenkins_token_setting = db.query(AppSettings).filter(
            AppSettings.key == 'JENKINS_API_TOKEN'
        ).first()

        if not all([jenkins_url_setting, jenkins_user_setting, jenkins_token_setting]):
            raise Exception("Jenkins credentials not configured")

        jenkins_url = json.loads(jenkins_url_setting.value)
        jenkins_user = json.loads(jenkins_user_setting.value)
        jenkins_token = json.loads(jenkins_token_setting.value)

        # Create Jenkins client
        client = JenkinsClient(jenkins_url, jenkins_user, jenkins_token)
        downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH, log_callback)

        # Download artifacts
        results = downloader.download_for_release(job_url, release, skip_existing)

        log_callback(f"Download completed: {len(results)} modules downloaded")

        # Import to database
        import_service = ImportService(db)

        for module_name, job_number in results.items():
            try:
                log_callback(f"Importing {module_name} job {job_number} to database...")
                import_service.import_job(release, module_name, job_number)
                log_callback(f"  Imported {module_name} successfully")
            except Exception as e:
                log_callback(f"  ERROR importing {module_name}: {e}")

        # Update job status
        download_jobs[job_id]['status'] = 'completed'
        download_jobs[job_id]['completed_at'] = datetime.utcnow().isoformat()

        log_callback("All done!")

    except Exception as e:
        logger.error(f"Download job {job_id} failed: {e}", exc_info=True)

        download_jobs[job_id]['status'] = 'failed'
        download_jobs[job_id]['completed_at'] = datetime.utcnow().isoformat()
        download_jobs[job_id]['error'] = str(e)

        log_callback(f"ERROR: {e}")
