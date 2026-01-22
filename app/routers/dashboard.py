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
from app.constants import ALL_MODULES_IDENTIFIER

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
    Get all modules for a specific release based on test file paths.

    Returns modules derived from test file paths (testcase_module field),
    NOT Jenkins job modules. This ensures correct grouping regardless of
    which Jenkins job executed the tests.

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

    # Get modules based on testcase_module field (path-derived)
    module_names = data_service.get_modules_for_release_by_testcases(db, release, version=version)

    if not module_names:
        raise HTTPException(
            status_code=404,
            detail=f"No modules found for release '{release}'"
        )

    # Build response with "All Modules" as first option
    from datetime import datetime, timezone
    response = [
        ModuleResponse(
            name=ALL_MODULES_IDENTIFIER,
            release=release,
            created_at=datetime.now(timezone.utc)
        )
    ]

    # Add individual modules (using module names as strings)
    response.extend([
        ModuleResponse(
            name=module_name,
            release=release,
            created_at=datetime.now(timezone.utc)  # No created_at for path-derived modules
        )
        for module_name in module_names
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
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_summary(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    version: Optional[str] = Query(None, description="Filter by version (e.g., '7.0.0.0')"),
    priorities: Optional[str] = Query(None, description="Comma-separated list of priorities for module breakdown (P0,P1,P2,P3,UNKNOWN)"),
    db: Session = Depends(get_db)
):
    """
    Get dashboard summary for a specific release/module (path-based).

    Module parameter now refers to testcase_module extracted from file paths,
    not the Jenkins job module name. Aggregates stats across all jobs
    containing tests for this module.

    Includes:
    - Summary statistics (aggregated across all jobs with this testcase_module)
    - Recent jobs list (jobs containing tests for this module)
    - Pass rate history (calculated per job for this module's tests only)
    - Module breakdown (for "All Modules" view only, can be filtered by priorities)

    Args:
        release: Release name
        module: Testcase module name from file path (use ALL_MODULES_IDENTIFIER for aggregated view)
        version: Optional version filter
        priorities: Comma-separated priority filter for module breakdown (All Modules view only)
        db: Database session

    Returns:
        Dashboard summary data

    Raises:
        HTTPException: If release or module not found
    """
    # Parse and validate priorities parameter using centralized helper
    try:
        priority_list = data_service.parse_and_validate_priorities(priorities)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Handle "All Modules" aggregated view
    if module == ALL_MODULES_IDENTIFIER:
        return get_all_modules_summary_response(db, release, version, priorities=priority_list)

    # Path-based module view
    # Get jobs that contain tests for this testcase_module
    jobs = data_service.get_jobs_for_testcase_module(db, release, module, version=version, limit=50)

    if not jobs:
        raise HTTPException(
            status_code=404,
            detail=f"No jobs found with tests for module '{module}' in release '{release}'"
        )

    # Group jobs by parent_job_id
    from app.models.db_models import TestResult, TestStatusEnum
    from collections import defaultdict

    jobs_by_parent = defaultdict(list)
    for job in jobs:
        parent_id = job.parent_job_id or job.job_id  # Fallback to job_id if no parent
        jobs_by_parent[parent_id].append(job)

    # Get unique parent job IDs sorted by descending order (latest first)
    parent_job_ids = sorted(jobs_by_parent.keys(), key=lambda x: int(x), reverse=True)

    # Get latest parent job ID and its sub-jobs
    latest_parent_job_id = parent_job_ids[0]
    latest_parent_jobs = jobs_by_parent[latest_parent_job_id]

    # Calculate statistics for LATEST PARENT JOB ONLY (all its sub-jobs)
    # counting only tests matching this testcase_module
    # Use optimized aggregation query to avoid N+1 problem
    latest_job_ids = [job.id for job in latest_parent_jobs]
    stats_by_job = data_service._calculate_stats_for_jobs(db, latest_job_ids, testcase_module=module)

    # Aggregate stats across all sub-jobs
    total_tests = sum(stats['total'] for stats in stats_by_job.values())
    total_passed = sum(stats['passed'] for stats in stats_by_job.values())
    total_failed = sum(stats['failed'] for stats in stats_by_job.values())
    total_skipped = sum(stats['skipped'] for stats in stats_by_job.values())

    # Calculate pass rate for latest parent job (as percentage of all tests including skipped)
    if total_tests == 0:
        pass_rate = 0.0
    else:
        pass_rate = round((total_passed / total_tests) * 100, 2)

    # Build summary stats (matching expected frontend format)
    stats = {
        'total_jobs': len(parent_job_ids),  # Count unique parent job IDs
        'latest_job': {
            'job_id': latest_parent_job_id,  # Show parent job ID
            'total': total_tests,  # Frontend expects stats nested in latest_job
            'passed': total_passed,
            'failed': total_failed,  # Includes both FAILED and ERROR statuses
            'skipped': total_skipped,
            'pass_rate': pass_rate
        },
        'total_tests': total_tests,  # Also at root for summary card
        'average_pass_rate': pass_rate  # For now, using latest job pass rate
    }

    # Build recent jobs list grouped by parent_job_id
    # Show parent_job_id with path-module-specific statistics
    # Optimize by collecting all job IDs and querying once
    recent_parent_ids = parent_job_ids[:10]  # Get top 10 parent jobs
    all_recent_job_ids = []
    for parent_id in recent_parent_ids:
        all_recent_job_ids.extend([job.id for job in jobs_by_parent[parent_id]])

    # Single query for all recent jobs' stats
    all_stats_by_job = data_service._calculate_stats_for_jobs(db, all_recent_job_ids, testcase_module=module)

    recent_jobs_data = []
    for parent_id in recent_parent_ids:
        parent_jobs = jobs_by_parent[parent_id]

        # Aggregate stats for this parent job from pre-fetched data
        parent_total = 0
        parent_passed = 0
        parent_failed = 0
        parent_skipped = 0

        for job in parent_jobs:
            if job.id in all_stats_by_job:
                job_stats = all_stats_by_job[job.id]  # Changed variable name to avoid shadowing
                parent_total += job_stats['total']
                parent_passed += job_stats['passed']
                parent_failed += job_stats['failed']
                parent_skipped += job_stats['skipped']

        # Calculate pass rate for this parent job (as percentage of all tests including skipped)
        if parent_total == 0:
            parent_pass_rate = 0.0
        else:
            parent_pass_rate = round((parent_passed / parent_total) * 100, 2)

        # Use version and created_at from first sub-job
        first_job = parent_jobs[0]

        recent_jobs_data.append({
            'job_id': parent_id,  # Show parent job ID
            'total': parent_total,
            'passed': parent_passed,
            'failed': parent_failed,  # Includes both FAILED and ERROR statuses
            'skipped': parent_skipped,
            'pass_rate': parent_pass_rate,
            'version': first_job.version,
            'created_at': first_job.created_at
        })

    # Build pass rate history (per job, for this module's tests only)
    pass_rate_history = [
        {
            'job_id': job_data['job_id'],
            'pass_rate': job_data['pass_rate'],
            'total': job_data['total'],
            'passed': job_data['passed'],
            'failed': job_data['failed']
        }
        for job_data in reversed(recent_jobs_data[:10])  # Chronological order
    ]

    return DashboardSummaryResponse(
        release=release,
        module=module,
        summary=stats,
        recent_jobs=recent_jobs_data,
        pass_rate_history=pass_rate_history
    )


@router.get("/priority-stats/{release}/{module}/{job_id}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
# Note: FastAPI-Cache2 automatically includes query parameters (compare) in cache key
# This ensures compare=true and compare=false are cached separately
async def get_priority_statistics(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=20),
    compare: bool = Query(False, description="Include comparison with previous run"),
    db: Session = Depends(get_db)
):
    """
    Get test statistics broken down by priority for a specific job.

    Args:
        release: Release name
        module: Module name (use ALL_MODULES_IDENTIFIER for aggregated view)
        job_id: Job ID or parent_job_id (for ALL_MODULES_IDENTIFIER)
        compare: If True, include comparison data with previous run
        db: Database session

    Returns:
        List of priority statistics with optional comparison data

    Raises:
        HTTPException: If release, module, or job not found

    Cache Behavior:
        Responses are cached separately for compare=true and compare=false.
        FastAPI-Cache2 includes query parameters in cache keys by default.
    """
    # Handle "All Modules" aggregated view
    if module == ALL_MODULES_IDENTIFIER:
        # Verify release exists
        release_obj = data_service.get_release_by_name(db, release)
        if not release_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Release '{release}' not found"
            )

        # Get aggregated priority statistics using job_id as parent_job_id
        stats = data_service.get_aggregated_priority_statistics(
            db, release, job_id, include_comparison=compare
        )

        if not stats:
            raise HTTPException(
                status_code=404,
                detail=f"No jobs found for parent_job_id '{job_id}' in release '{release}'"
            )

        return stats

    # Standard path-based module view
    # job_id parameter is now parent_job_id (dashboard shows parent job IDs)
    # Get all sub-jobs for this parent job that contain tests for this testcase_module
    jobs = data_service.get_jobs_for_testcase_module(db, release, module, version=None, limit=50)

    # Filter to only jobs with this parent_job_id
    parent_jobs = [job for job in jobs if (job.parent_job_id or job.job_id) == job_id]

    if not parent_jobs:
        raise HTTPException(
            status_code=404,
            detail=f"No jobs found for parent_job_id '{job_id}' with tests for module '{module}' in release '{release}'"
        )

    # Get priority statistics for this parent job (all sub-jobs), filtered by testcase_module
    stats = data_service.get_priority_statistics_for_parent_job(
        db, release, module, job_id, parent_jobs, include_comparison=compare
    )

    return stats


def get_all_modules_summary_response(
    db: Session,
    release: str,
    version: Optional[str] = None,
    priorities: Optional[List[str]] = None
) -> DashboardSummaryResponse:
    """
    Helper function to build dashboard summary for "All Modules" view.

    Args:
        db: Database session
        release: Release name
        version: Optional version filter
        priorities: Optional list of priorities to filter module breakdown

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
            db, release, latest_parent_job_id, priorities=priorities
        )

    # Get recent runs (parent job IDs with aggregated stats)
    parent_job_ids = data_service.get_latest_parent_job_ids(db, release, version, limit=10)
    recent_runs = []
    for pj_id in parent_job_ids:
        run_stats = data_service.get_aggregated_stats_for_parent_job(db, release, pj_id)
        recent_runs.append(run_stats)

    return DashboardSummaryResponse(
        release=release,
        module=ALL_MODULES_IDENTIFIER,
        summary=stats,
        recent_jobs=recent_runs,  # For "All Modules", this contains parent_job_id runs
        pass_rate_history=pass_rate_history,
        module_breakdown=module_breakdown  # Per-module stats for latest run
    )
