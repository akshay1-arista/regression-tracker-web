"""
Dashboard API router.
Provides endpoints for the main dashboard view.
"""
import logging
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi_cache.decorator import cache

from app.database import get_db
from app.services import data_service, trend_analyzer
from app.models.schemas import (
    ReleaseResponse, ModuleResponse, DashboardSummaryResponse
)
from app.utils.auth import verify_api_key
from app.utils.helpers import serialize_datetime_list
from app.config import get_settings
from app.constants import ALL_MODULES_IDENTIFIER, PARENT_JOB_DROPDOWN_LIMIT

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


def _count_passed_flaky_tests(
    db: Session,
    job_ids: List[int],
    flaky_test_keys: List[str],
    module_filter: Optional[str] = None
) -> int:
    """
    Helper function to count flaky tests that passed in specific jobs.

    Args:
        db: Database session
        job_ids: List of job IDs to check
        flaky_test_keys: List of test keys in format "file_path::class_name::test_name"
        module_filter: Optional testcase_module filter

    Returns:
        Count of flaky tests that passed in the specified jobs
    """
    from app.models.db_models import TestResult, TestStatusEnum
    from sqlalchemy import tuple_, func

    if not flaky_test_keys or not job_ids:
        return 0

    # Parse test_keys into tuples (file_path, class_name, test_name)
    test_key_tuples = []
    for test_key in flaky_test_keys:
        parts = test_key.split('::')
        if len(parts) == 3:
            test_key_tuples.append(tuple(parts))

    if not test_key_tuples:
        return 0

    try:
        # Build query
        query = db.query(func.count(TestResult.id)).filter(
            TestResult.job_id.in_(job_ids),
            tuple_(TestResult.file_path, TestResult.class_name, TestResult.test_name).in_(test_key_tuples),
            TestResult.status == TestStatusEnum.PASSED
        )

        # Add module filter if provided
        if module_filter:
            query = query.filter(TestResult.testcase_module == module_filter)

        passed_flaky_count = query.scalar()
        return passed_flaky_count if passed_flaky_count else 0

    except SQLAlchemyError as e:
        logger.error(f"Database error counting passed flaky tests: {e}", exc_info=True)
        return 0
    except Exception as e:
        logger.error(f"Unexpected error counting passed flaky tests: {e}", exc_info=True)
        return 0


def _batch_count_passed_flaky_tests(
    db: Session,
    job_id_groups: Dict[str, List[int]],
    flaky_test_keys: List[str],
    module_filter: Optional[str] = None
) -> Dict[str, int]:
    """
    Optimized batch version to count flaky tests across multiple job groups in a single query.

    Args:
        db: Database session
        job_id_groups: Dict mapping group keys (e.g., parent_job_id) to list of job IDs
        flaky_test_keys: List of test keys in format "file_path::class_name::test_name"
        module_filter: Optional testcase_module filter

    Returns:
        Dict mapping group keys to count of flaky tests that passed
    """
    from app.models.db_models import TestResult, TestStatusEnum
    from sqlalchemy import tuple_

    if not flaky_test_keys or not job_id_groups:
        return {key: 0 for key in job_id_groups.keys()}

    # Parse test_keys into tuples (file_path, class_name, test_name)
    test_key_tuples = []
    for test_key in flaky_test_keys:
        parts = test_key.split('::')
        if len(parts) == 3:
            test_key_tuples.append(tuple(parts))

    if not test_key_tuples:
        return {key: 0 for key in job_id_groups.keys()}

    try:
        # Get all job IDs from all groups
        all_job_ids = []
        job_id_to_group = {}  # Map job_id -> group_key
        for group_key, job_ids in job_id_groups.items():
            all_job_ids.extend(job_ids)
            for job_id in job_ids:
                job_id_to_group[job_id] = group_key

        # Single query to get all passed flaky tests across all jobs
        query = db.query(TestResult.job_id).filter(
            TestResult.job_id.in_(all_job_ids),
            tuple_(TestResult.file_path, TestResult.class_name, TestResult.test_name).in_(test_key_tuples),
            TestResult.status == TestStatusEnum.PASSED
        )

        # Add module filter if provided
        if module_filter:
            query = query.filter(TestResult.testcase_module == module_filter)

        results = query.all()

        # Count results per group
        counts_by_group = {key: 0 for key in job_id_groups.keys()}
        for (job_id,) in results:
            group_key = job_id_to_group.get(job_id)
            if group_key:
                counts_by_group[group_key] += 1

        return counts_by_group

    except SQLAlchemyError as e:
        logger.error(f"Database error batch counting passed flaky tests: {e}", exc_info=True)
        return {key: 0 for key in job_id_groups.keys()}
    except Exception as e:
        logger.error(f"Unexpected error batch counting passed flaky tests: {e}", exc_info=True)
        return {key: 0 for key in job_id_groups.keys()}


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


@router.get("/parent-jobs/{release}/{module}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_parent_jobs(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    version: Optional[str] = Query(None, description="Filter by version (e.g., '7.0.0.0')"),
    limit: int = Query(PARENT_JOB_DROPDOWN_LIMIT, ge=1, le=50, description="Maximum number of parent job IDs to return"),
    db: Session = Depends(get_db)
):
    """
    Get available parent job IDs for a release/module with execution dates.

    For All Modules: Returns parent job IDs with multi-module jobs
    For specific module: Returns parent job IDs filtered by testcase_module

    Uses Jenkins execution timestamp (executed_at) when available,
    falls back to DB import time (created_at) for older records.

    Args:
        release: Release name (e.g., "7.0")
        module: Module name or '__all__' for all modules
        version: Optional version filter (e.g., "7.0.0.0")
        limit: Maximum number of parent job IDs to return (default: 10, max: 50)
        db: Database session

    Returns:
        List of parent job IDs with metadata:
        [
            {
                "parent_job_id": "2840",
                "executed_at": "2026-01-15T10:30:00"
            },
            ...
        ]
        Sorted numerically descending (newest first)

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

    # Get parent job IDs with dates
    parent_jobs = data_service.get_parent_jobs_with_dates(
        db, release, module, version=version, limit=limit
    )

    if not parent_jobs:
        return []

    # Convert datetime objects to ISO format strings for JSON serialization
    serialize_datetime_list(parent_jobs, 'executed_at')

    return parent_jobs


@router.get("/summary/{release}/{module}", response_model=DashboardSummaryResponse)
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_summary(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    version: Optional[str] = Query(None, description="Filter by version (e.g., '7.0.0.0')"),
    parent_job_id: Optional[str] = Query(None, description="Specific parent job ID to display (if None, shows latest)"),
    priorities: Optional[str] = Query(None, description="Comma-separated list of priorities for module breakdown (P0,P1,P2,P3,UNKNOWN)"),
    exclude_flaky: bool = Query(False, description="Exclude flaky tests from pass rate calculation"),
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
        return get_all_modules_summary_response(db, release, version, parent_job_id=parent_job_id, priorities=priority_list, exclude_flaky=exclude_flaky)

    # Path-based module view
    # For specific modules:
    # - If parent_job_id is provided: use it ONLY for summary stats/flaky stats
    # - Always fetch ALL jobs for pass rate history and recent jobs list

    # Fetch ALL jobs for this module (for pass rate history and recent jobs)
    all_jobs = data_service.get_jobs_for_testcase_module(db, release, module, version=version, parent_job_id=None, limit=50)

    if not all_jobs:
        raise HTTPException(
            status_code=404,
            detail=f"No jobs found with tests for module '{module}' in release '{release}'"
        )

    # Group ALL jobs by parent_job_id (for pass rate history and recent jobs)
    from app.models.db_models import TestResult, TestStatusEnum
    from collections import defaultdict

    jobs_by_parent = defaultdict(list)
    for job in all_jobs:
        parent_id = job.parent_job_id or job.job_id  # Fallback to job_id if no parent
        jobs_by_parent[parent_id].append(job)

    # Get unique parent job IDs sorted by descending order (latest first)
    parent_job_ids = sorted(jobs_by_parent.keys(), key=lambda x: int(x), reverse=True)

    # Determine which parent job to use for summary stats
    # If parent_job_id provided, use it; otherwise use latest
    if parent_job_id and parent_job_id in jobs_by_parent:
        latest_parent_job_id = parent_job_id
    else:
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

    # Calculate flaky and new failure statistics
    # - Flaky: based on last 5 jobs
    # - New failures: current vs previous run
    failure_summary = trend_analyzer.get_dashboard_failure_summary(
        db, release, module, use_testcase_module=True
    )

    # Add to summary stats with priority breakdown
    stats['flaky_by_priority'] = failure_summary['flaky_by_priority']
    stats['passed_flaky_by_priority'] = failure_summary['passed_flaky_by_priority']
    stats['new_failures_by_priority'] = failure_summary['new_failures_by_priority']
    stats['total_flaky'] = failure_summary['total_flaky']
    stats['total_passed_flaky'] = failure_summary['total_passed_flaky']
    stats['total_new_failures'] = failure_summary['total_new_failures']

    # If exclude_flaky is True, recalculate pass rate by excluding PASSED flaky tests from numerator only
    if exclude_flaky and failure_summary['flaky_test_keys']:
        # Count how many flaky tests PASSED in the latest job
        passed_flaky_count = _count_passed_flaky_tests(
            db, latest_job_ids, failure_summary['flaky_test_keys'], module_filter=module
        )

        # Adjusted pass rate = (Passed - Passed_Flaky) / Total * 100
        adjusted_passed = total_passed - passed_flaky_count
        adjusted_pass_rate = round((adjusted_passed / total_tests) * 100, 2) if total_tests > 0 else 0.0

        stats['adjusted_stats'] = {
            'total': total_tests,  # Total stays the same
            'passed': adjusted_passed,  # Only subtract passed flaky tests
            'failed': total_failed,  # Failed count stays the same
            'skipped': total_skipped,  # Skipped count stays the same
            'pass_rate': adjusted_pass_rate,
            'excluded_passed_flaky_count': passed_flaky_count  # Only passed flaky tests excluded
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
    pass_rate_history = []

    # Optimize batch query: if exclude_flaky, get all counts at once instead of per-job
    flaky_counts_by_job = {}
    if exclude_flaky and failure_summary['flaky_test_keys']:
        job_id_groups = {
            job_data['job_id']: [job.id for job in jobs_by_parent[job_data['job_id']]]
            for job_data in recent_jobs_data[:10]
        }
        flaky_counts_by_job = _batch_count_passed_flaky_tests(
            db, job_id_groups, failure_summary['flaky_test_keys'], module_filter=module
        )

    for job_data in reversed(recent_jobs_data[:10]):  # Chronological order
        history_entry = {
            'job_id': job_data['job_id'],
            'pass_rate': job_data['pass_rate'],
            'total': job_data['total'],
            'passed': job_data['passed'],
            'failed': job_data['failed']
        }

        # If exclude_flaky, use pre-computed counts
        if exclude_flaky and failure_summary['flaky_test_keys']:
            passed_flaky_count = flaky_counts_by_job.get(job_data['job_id'], 0)

            # Adjusted pass rate = (Passed - Passed_Flaky) / Total * 100
            adjusted_passed = job_data['passed'] - passed_flaky_count
            adjusted_rate = round((adjusted_passed / job_data['total']) * 100, 2) if job_data['total'] > 0 else 0.0

            history_entry['adjusted_pass_rate'] = adjusted_rate
            history_entry['adjusted_passed'] = adjusted_passed
            history_entry['excluded_passed_flaky_count'] = passed_flaky_count

        pass_rate_history.append(history_entry)

    return DashboardSummaryResponse(
        release=release,
        module=module,
        summary=stats,
        recent_jobs=recent_jobs_data,
        pass_rate_history=pass_rate_history
    )


@router.get("/priority-stats/{release}/{module}/{job_id}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
# Note: FastAPI-Cache2 automatically includes query parameters (compare, exclude_flaky) in cache key
# This ensures different combinations are cached separately
async def get_priority_statistics(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=20),
    compare: bool = Query(False, description="Include comparison with previous run"),
    exclude_flaky: bool = Query(False, description="Exclude flaky tests from pass rate calculation"),
    db: Session = Depends(get_db)
):
    """
    Get test statistics broken down by priority for a specific job.

    Args:
        release: Release name
        module: Module name (use ALL_MODULES_IDENTIFIER for aggregated view)
        job_id: Job ID or parent_job_id (for ALL_MODULES_IDENTIFIER)
        compare: If True, include comparison data with previous run
        exclude_flaky: If True, exclude passed flaky tests from pass rate calculation
        db: Database session

    Returns:
        List of priority statistics with optional comparison data

    Raises:
        HTTPException: If release, module, or job not found

    Cache Behavior:
        Responses are cached separately for different parameter combinations.
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
            db, release, job_id, include_comparison=compare, exclude_flaky=exclude_flaky
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
        db, release, module, job_id, parent_jobs, include_comparison=compare, exclude_flaky=exclude_flaky
    )

    return stats


def get_all_modules_summary_response(
    db: Session,
    release: str,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    priorities: Optional[List[str]] = None,
    exclude_flaky: bool = False
) -> DashboardSummaryResponse:
    """
    Helper function to build dashboard summary for "All Modules" view.

    Args:
        db: Database session
        release: Release name
        version: Optional version filter
        parent_job_id: Optional specific parent job ID to display (if None, shows latest)
        priorities: Optional list of priorities to filter module breakdown
        exclude_flaky: If True, exclude flaky tests from pass rate calculation

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
    stats = data_service.get_all_modules_summary_stats(db, release, version, parent_job_id=parent_job_id)

    # Get pass rate history
    pass_rate_history = data_service.get_all_modules_pass_rate_history(db, release, version, limit=10)

    # Get module breakdown for the selected parent job (if available)
    module_breakdown = []
    if stats.get('latest_run') and stats['latest_run'].get('parent_job_id'):
        selected_parent_job_id = stats['latest_run']['parent_job_id']
        module_breakdown = data_service.get_module_breakdown_for_parent_job(
            db, release, selected_parent_job_id, priorities=priorities, exclude_flaky=exclude_flaky
        )

    # Calculate flaky/new failures for All Modules
    # Aggregate across all testcase_modules
    all_module_names = data_service.get_modules_for_release_by_testcases(db, release, version)

    total_flaky = 0
    total_passed_flaky = 0
    total_new_failures = 0
    flaky_by_priority_agg = {}
    passed_flaky_by_priority_agg = {}
    new_failures_by_priority_agg = {}
    all_flaky_test_keys = set()  # Collect all flaky test keys across modules

    for mod_name in all_module_names:
        mod_summary = trend_analyzer.get_dashboard_failure_summary(
            db, release, mod_name, use_testcase_module=True
        )
        total_flaky += mod_summary['total_flaky']
        total_passed_flaky += mod_summary['total_passed_flaky']
        total_new_failures += mod_summary['total_new_failures']
        all_flaky_test_keys.update(mod_summary['flaky_test_keys'])

        # Aggregate priority breakdowns
        for priority, count in mod_summary['flaky_by_priority'].items():
            flaky_by_priority_agg[priority] = flaky_by_priority_agg.get(priority, 0) + count
        for priority, count in mod_summary['passed_flaky_by_priority'].items():
            passed_flaky_by_priority_agg[priority] = passed_flaky_by_priority_agg.get(priority, 0) + count
        for priority, count in mod_summary['new_failures_by_priority'].items():
            new_failures_by_priority_agg[priority] = new_failures_by_priority_agg.get(priority, 0) + count

    stats['flaky_by_priority'] = flaky_by_priority_agg
    stats['passed_flaky_by_priority'] = passed_flaky_by_priority_agg
    stats['new_failures_by_priority'] = new_failures_by_priority_agg
    stats['total_flaky'] = total_flaky
    stats['total_passed_flaky'] = total_passed_flaky
    stats['total_new_failures'] = total_new_failures

    # If exclude_flaky is True, recalculate pass rate by excluding PASSED flaky tests from numerator only
    if exclude_flaky and all_flaky_test_keys and stats.get('latest_run'):
        # Get job IDs for latest run
        latest_parent_job_id = stats['latest_run'].get('parent_job_id')
        if latest_parent_job_id:
            latest_jobs = data_service.get_jobs_by_parent_job_id(db, release, latest_parent_job_id)
            latest_job_ids = [job.id for job in latest_jobs]

            # Count how many flaky tests PASSED in the latest run (across all modules, no module filter)
            passed_flaky_count = _count_passed_flaky_tests(
                db, latest_job_ids, list(all_flaky_test_keys), module_filter=None
            )

            # Get current stats from latest_run
            total_tests = stats['latest_run'].get('total', 0)
            passed_tests = stats['latest_run'].get('passed', 0)
            failed_tests = stats['latest_run'].get('failed', 0)
            skipped_tests = stats['latest_run'].get('skipped', 0)

            # Adjusted pass rate = (Passed - Passed_Flaky) / Total * 100
            adjusted_passed = passed_tests - passed_flaky_count
            adjusted_pass_rate = round((adjusted_passed / total_tests) * 100, 2) if total_tests > 0 else 0.0

            stats['adjusted_stats'] = {
                'total': total_tests,  # Total stays the same
                'passed': adjusted_passed,  # Only subtract passed flaky tests
                'failed': failed_tests,  # Failed count stays the same
                'skipped': skipped_tests,  # Skipped count stays the same
                'pass_rate': adjusted_pass_rate,
                'excluded_passed_flaky_count': passed_flaky_count  # Only passed flaky tests excluded
            }

    # Get recent runs (parent job IDs with aggregated stats)
    parent_job_ids = data_service.get_latest_parent_job_ids(db, release, version, limit=10)
    recent_runs = []
    for pj_id in parent_job_ids:
        run_stats = data_service.get_aggregated_stats_for_parent_job(db, release, pj_id)
        recent_runs.append(run_stats)

    # If exclude_flaky is True, update pass_rate_history with adjusted rates
    if exclude_flaky and all_flaky_test_keys:
        # Optimize batch query: get all counts at once instead of per-parent-job
        job_id_groups = {}
        for history_entry in pass_rate_history:
            parent_job_id = history_entry.get('parent_job_id')
            if parent_job_id:
                jobs_for_parent = data_service.get_jobs_by_parent_job_id(db, release, parent_job_id)
                job_id_groups[parent_job_id] = [job.id for job in jobs_for_parent]

        # Single batch query for all parent jobs
        flaky_counts_by_parent = _batch_count_passed_flaky_tests(
            db, job_id_groups, list(all_flaky_test_keys), module_filter=None
        )

        # Update each history entry with pre-computed counts
        for history_entry in pass_rate_history:
            parent_job_id = history_entry.get('parent_job_id')
            if parent_job_id:
                passed_flaky_count = flaky_counts_by_parent.get(parent_job_id, 0)

                # Adjusted pass rate = (Passed - Passed_Flaky) / Total * 100
                adjusted_passed = history_entry['passed'] - passed_flaky_count
                adjusted_rate = round((adjusted_passed / history_entry['total']) * 100, 2) if history_entry['total'] > 0 else 0.0

                history_entry['adjusted_pass_rate'] = adjusted_rate
                history_entry['adjusted_passed'] = adjusted_passed
                history_entry['excluded_passed_flaky_count'] = passed_flaky_count

    # Serialize datetime fields in pass_rate_history
    serialize_datetime_list(pass_rate_history, 'created_at', 'executed_at')

    return DashboardSummaryResponse(
        release=release,
        module=ALL_MODULES_IDENTIFIER,
        summary=stats,
        recent_jobs=recent_runs,  # For "All Modules", this contains parent_job_id runs
        pass_rate_history=pass_rate_history,
        module_breakdown=module_breakdown  # Per-module stats for latest run
    )


@router.get("/bug-breakdown/{release}/{module}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_bug_breakdown(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    parent_job_id: Optional[str] = Query(None, description="Filter by parent job ID (required)"),
    priorities: Optional[str] = Query(None, description="Comma-separated priority filters (P0,P1,P2,P3,HIGH,MEDIUM,UNKNOWN)"),
    db: Session = Depends(get_db)
):
    """
    Get bug tracking breakdown per module for a parent job.

    Shows VLEI/VLENG bug counts and affected test counts grouped by module.
    Respects "All Modules" filter vs specific module selection.

    Args:
        release: Release name
        module: Module name or '__all__' for all modules
        parent_job_id: Parent job ID (required for filtering)
        db: Database session

    Returns:
        List of module bug statistics:
        [{
            'module_name': str,
            'vlei_count': int,
            'vleng_count': int,
            'affected_test_count': int,
            'total_bug_count': int
        }]

    Raises:
        HTTPException: If release not found or parent_job_id missing
    """
    try:
        # Verify release exists
        release_obj = data_service.get_release_by_name(db, release)
        if not release_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Release '{release}' not found"
            )

        # Require parent_job_id for bug breakdown
        if not parent_job_id:
            raise HTTPException(
                status_code=400,
                detail="parent_job_id parameter is required for bug breakdown"
            )

        # Handle "All Modules" vs specific module
        module_filter = None if module == ALL_MODULES_IDENTIFIER else module

        # Parse and validate priorities parameter
        priority_list = None
        if priorities:
            priority_list = data_service.parse_and_validate_priorities(priorities)

        # Get bug breakdown
        breakdown = data_service.get_bug_breakdown_for_parent_job(
            db, release, parent_job_id, module_filter=module_filter, priorities=priority_list
        )

        return breakdown

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bug breakdown: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching bug breakdown"
        )


@router.get("/bug-details/{release}/{module}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_bug_details(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100),
    parent_job_id: str = Query(..., description="Parent job ID"),
    bug_type: Optional[str] = Query(None, regex="^(VLEI|VLENG)$", description="Filter by bug type"),
    db: Session = Depends(get_db)
):
    """
    Get detailed bug information for a module.

    Used for modal popups when clicking VLEI/VLENG counts.

    Args:
        release: Release name
        module: Module name
        parent_job_id: Parent job ID
        bug_type: Optional bug type filter ('VLEI' or 'VLENG')
        db: Database session

    Returns:
        List of bugs with details:
        [{
            'defect_id': str,
            'bug_type': str,
            'status': str,
            'summary': str,
            'url': str,
            'priority': str,
            'affected_test_count': int,
            'priority_breakdown': {'P0': int, 'P1': int, ...}
        }]

    Raises:
        HTTPException: If release/module not found
    """
    try:
        # Verify release
        release_obj = data_service.get_release_by_name(db, release)
        if not release_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Release '{release}' not found"
            )

        # Get bug details
        bug_details = data_service.get_bug_details_for_module(
            db, release, parent_job_id, module, bug_type=bug_type
        )

        return bug_details

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bug details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching bug details"
        )


@router.get("/bug-affected-tests/{release}/{module}/{defect_id}")
@cache(expire=settings.CACHE_TTL_SECONDS if settings.CACHE_ENABLED else 0)
async def get_bug_affected_tests(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100),
    defect_id: str = Path(..., description="Bug defect ID (e.g., VLEI-12345)"),
    parent_job_id: str = Query(..., description="Parent job ID"),
    db: Session = Depends(get_db)
):
    """
    Get list of test cases affected by a specific bug.

    Args:
        release: Release name
        module: Module name
        defect_id: Bug defect ID
        parent_job_id: Parent job ID
        db: Database session

    Returns:
        List of affected test cases:
        [{
            'testcase_name': str,
            'priority': str,
            'status': str,
            'test_case_id': str,
            'file_path': str
        }]

    Raises:
        HTTPException: If release not found
    """
    try:
        # Verify release
        release_obj = data_service.get_release_by_name(db, release)
        if not release_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Release '{release}' not found"
            )

        # Get affected tests
        affected_tests = data_service.get_affected_tests_for_bug(
            db, release, parent_job_id, module, defect_id
        )

        return affected_tests

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting affected tests: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching affected tests"
        )
