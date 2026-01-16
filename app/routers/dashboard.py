"""
Dashboard API router.
Provides endpoints for the main dashboard view.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_service
from app.models.schemas import (
    ReleaseResponse, ModuleResponse, DashboardSummaryResponse
)

router = APIRouter()


@router.get("/releases", response_model=List[ReleaseResponse])
async def get_releases(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get all releases.

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
async def get_modules(
    release: str,
    db: Session = Depends(get_db)
):
    """
    Get all modules for a specific release.

    Args:
        release: Release name (e.g., "7.0.0.0")
        db: Database session

    Returns:
        List of modules for the release

    Raises:
        HTTPException: If release not found
    """
    # Verify release exists
    release_obj = data_service.get_release_by_name(db, release)
    if not release_obj:
        raise HTTPException(status_code=404, detail=f"Release '{release}' not found")

    modules = data_service.get_modules_for_release(db, release)

    return [
        ModuleResponse(
            name=module.name,
            release=release,
            created_at=module.created_at
        )
        for module in modules
    ]


@router.get("/summary/{release}/{module}", response_model=DashboardSummaryResponse)
async def get_summary(
    release: str,
    module: str,
    db: Session = Depends(get_db)
):
    """
    Get dashboard summary for a specific release/module.

    Includes:
    - Summary statistics (total jobs, average pass rate, etc.)
    - Recent jobs list
    - Pass rate history

    Args:
        release: Release name
        module: Module name
        db: Database session

    Returns:
        Dashboard summary data

    Raises:
        HTTPException: If release or module not found
    """
    # Verify module exists
    module_obj = data_service.get_module(db, release, module)
    if not module_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Module '{module}' not found in release '{release}'"
        )

    # Get summary statistics
    stats = data_service.get_job_summary_stats(db, release, module)

    # Get recent jobs (last 10)
    recent_jobs = data_service.get_jobs_for_module(db, release, module, limit=10)

    # Get pass rate history
    pass_rate_history = data_service.get_pass_rate_history(db, release, module, limit=10)

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
                'created_at': job.created_at
            }
            for job in recent_jobs
        ],
        pass_rate_history=pass_rate_history
    )
