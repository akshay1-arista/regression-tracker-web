"""
Dashboard API router.
Provides endpoints for the main dashboard view.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from fastapi_cache.decorator import cache

from app.database import get_db
from app.services import data_service
from app.models.schemas import (
    ReleaseResponse, ModuleResponse, DashboardSummaryResponse
)
from app.utils.auth import verify_api_key
from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/releases", response_model=List[ReleaseResponse])
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_releases(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get all releases.

    Cached for improved performance. Cache duration: configured via CACHE_TTL_SECONDS.

    Args:
        active_only: If True, only return active releases
        db: Database session

    Returns:
        List of releases with basic information
    """
    releases = data_service.get_all_releases(db, active_only=active_only)

    return [
        ReleaseResponse(
            name=release.name,
            is_active=release.is_active,
            jenkins_job_url=release.jenkins_job_url,
            created_at=release.created_at
        )
        for release in releases
    ]


@router.get("/modules/{release}", response_model=List[ModuleResponse])
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_modules(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    version: Optional[str] = Query(None, description="Filter by version (e.g., '7.0.0.0')"),
    db: Session = Depends(get_db)
):
    """
    Get all modules for a specific release, optionally filtered by version.

    Cached for improved performance. Cache duration: configured via CACHE_TTL_SECONDS.

    Args:
        release: Release name (e.g., "7.0")
        version: Optional version filter (e.g., "7.0.0.0")
        db: Database session

    Returns:
        List of modules for the release (filtered by version if provided)

    Raises:
        HTTPException: If release not found
    """
    # Verify release exists
    release_obj = data_service.get_release_by_name(db, release)
    if not release_obj:
        raise HTTPException(status_code=404, detail=f"Release '{release}' not found")

    # If version filter provided, get modules that have jobs with that version
    if version:
        from app.models.db_models import Job, Module
        modules_query = db.query(Module).join(Job).filter(
            Module.release_id == release_obj.id,
            Job.version == version
        ).distinct()
        modules = modules_query.all()
    else:
        modules = data_service.get_modules_for_release(db, release)

    # Build response with "All Modules" as first option
    from datetime import datetime, timezone
    response = [
        ModuleResponse(
            name="__all__",
            release=release,
            created_at=datetime.now(timezone.utc)
        )
    ]

    # Add individual modules
    response.extend([
        ModuleResponse(
            name=module.name,
            release=release,
            created_at=module.created_at
        )
        for module in modules
    ])

    return response


@router.get("/versions/{release}", response_model=List[str])
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_versions(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    db: Session = Depends(get_db)
):
    """
    Get list of available versions for a specific release.

    Args:
        release: Release name
        db: Database session

    Returns:
        List of version strings (sorted, newest first)

    Raises:
        HTTPException: If release not found
    """
    # Verify release exists
    release_obj = data_service.get_release_by_name(db, release)
    if not release_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Release '{release}' not found"
        )

    # Get distinct versions from all jobs in this release
    from app.models.db_models import Job, Module
    versions = db.query(Job.version).join(Module).filter(
        Module.release_id == release_obj.id,
        Job.version.isnot(None)
    ).distinct().all()

    # Extract version strings and sort
    version_list = [v[0] for v in versions if v[0]]
    version_list.sort(reverse=True)  # Newest first

    return version_list


@router.get("/summary/{release}/{module}", response_model=DashboardSummaryResponse)
async def get_summary(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    version: Optional[str] = Query(None, description="Filter by version (e.g., '7.0.0.0')"),
    db: Session = Depends(get_db)
):
    """
    Get dashboard summary for a specific release/module.

    Includes:
    - Summary statistics (total jobs, average pass rate, etc.)
    - Recent jobs list
    - Pass rate history
    - Module breakdown (for "All Modules" view only)

    Args:
        release: Release name
        module: Module name (use "__all__" for aggregated view)
        version: Optional version filter
        db: Database session

    Returns:
        Dashboard summary data

    Raises:
        HTTPException: If release or module not found
    """
    # Handle "All Modules" aggregated view
    if module == "__all__":
        return get_all_modules_summary_response(db, release, version)

    # Standard single-module view
    # Verify module exists
    module_obj = data_service.get_module(db, release, module)
    if not module_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Module '{module}' not found in release '{release}'"
        )

    # Get summary statistics
    stats = data_service.get_job_summary_stats(db, release, module, version=version)

    # Get recent jobs (last 10)
    recent_jobs = data_service.get_jobs_for_module(db, release, module, version=version, limit=10)

    # Get pass rate history
    pass_rate_history = data_service.get_pass_rate_history(db, release, module, version=version, limit=10)

    return DashboardSummaryResponse(
        release=release,
        module=module,
        summary=stats,
        recent_jobs=[
            {
                'job_id': job.job_id,
                'total': job.total,
                'passed': job.passed,
                'failed': job.failed,
                'skipped': job.skipped,
                'error': job.error,
                'pass_rate': job.pass_rate,
                'version': job.version,
                'created_at': job.created_at
            }
            for job in recent_jobs
        ],
        pass_rate_history=pass_rate_history
    )


@router.get("/priority-stats/{release}/{module}/{job_id}")
async def get_priority_statistics(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=20),
    db: Session = Depends(get_db)
):
    """
    Get test statistics broken down by priority for a specific job.

    Args:
        release: Release name
        module: Module name (use "__all__" for aggregated view)
        job_id: Job ID or parent_job_id (for "__all__")
        db: Database session

    Returns:
        List of priority statistics with counts and pass rates

    Raises:
        HTTPException: If release, module, or job not found
    """
    # Handle "All Modules" aggregated view
    if module == "__all__":
        # Verify release exists
        release_obj = data_service.get_release_by_name(db, release)
        if not release_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Release '{release}' not found"
            )

        # Get aggregated priority statistics using job_id as parent_job_id
        stats = data_service.get_aggregated_priority_statistics(db, release, job_id)

        if not stats:
            raise HTTPException(
                status_code=404,
                detail=f"No jobs found for parent_job_id '{job_id}' in release '{release}'"
            )

        return stats

    # Standard single-module view
    # Verify job exists
    job = data_service.get_job(db, release, module, job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found in module '{module}' for release '{release}'"
        )

    # Get priority statistics
    stats = data_service.get_priority_statistics(db, release, module, job_id)

    return stats


def get_all_modules_summary_response(
    db: Session,
    release: str,
    version: Optional[str] = None
) -> DashboardSummaryResponse:
    """
    Helper function to build dashboard summary for "All Modules" view.

    Args:
        db: Database session
        release: Release name
        version: Optional version filter

    Returns:
        DashboardSummaryResponse with aggregated data

    Raises:
        HTTPException: If release not found
    """
    # Verify release exists
    release_obj = data_service.get_release_by_name(db, release)
    if not release_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Release '{release}' not found"
        )

    # Get aggregated summary statistics
    stats = data_service.get_all_modules_summary_stats(db, release, version)

    # Get pass rate history
    pass_rate_history = data_service.get_all_modules_pass_rate_history(db, release, version, limit=10)

    # Get module breakdown for latest run (if available)
    module_breakdown = []
    if stats.get('latest_run') and stats['latest_run'].get('parent_job_id'):
        latest_parent_job_id = stats['latest_run']['parent_job_id']
        module_breakdown = data_service.get_module_breakdown_for_parent_job(
            db, release, latest_parent_job_id
        )

    # Get recent runs (parent job IDs with aggregated stats)
    parent_job_ids = data_service.get_latest_parent_job_ids(db, release, version, limit=10)
    recent_runs = []
    for pj_id in parent_job_ids:
        run_stats = data_service.get_aggregated_stats_for_parent_job(db, release, pj_id)
        recent_runs.append(run_stats)

    return DashboardSummaryResponse(
        release=release,
        module="__all__",
        summary=stats,
        recent_jobs=recent_runs,  # For "All Modules", this contains parent_job_id runs
        pass_rate_history=pass_rate_history,
        module_breakdown=module_breakdown  # Per-module stats for latest run
    )
