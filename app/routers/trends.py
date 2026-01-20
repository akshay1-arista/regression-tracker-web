"""
Trends API router.
Provides endpoints for test trend analysis across jobs.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_service, trend_analyzer
from app.models.schemas import (
    TestTrendSchema,
    PaginatedResponse,
    PaginationMetadata
)

router = APIRouter()


@router.get("/{release}/{module}", response_model=PaginatedResponse[TestTrendSchema])
async def get_trends(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    flaky_only: bool = Query(False, description="Only return flaky tests"),
    always_failing_only: bool = Query(False, description="Only return always-failing tests"),
    new_failures_only: bool = Query(False, description="Only return new failures"),
    priorities: Optional[str] = Query(None, description="Comma-separated list of priorities (P0,P1,P2,P3,UNKNOWN)"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return (1-1000)"),
    db: Session = Depends(get_db)
):
    """
    Get test trends for a specific release/module (path-based) with optional filters.

    Module parameter now refers to testcase_module extracted from file paths.
    Gets all jobs containing tests for this module, regardless of which
    Jenkins job module ran them.

    Args:
        release: Release name
        module: Testcase module name from file path
        flaky_only: If True, only return flaky tests
        always_failing_only: If True, only return always-failing tests
        new_failures_only: If True, only return new failures
        priorities: Comma-separated list of priorities to filter by
        db: Database session

    Returns:
        List of test trends with status across all jobs

    Raises:
        HTTPException: If release or module not found
    """
    # Get jobs that contain tests for this testcase_module (path-based)
    jobs = data_service.get_jobs_for_testcase_module(db, release, module)

    if not jobs:
        raise HTTPException(
            status_code=404,
            detail=f"No jobs found with tests for module '{module}' in release '{release}'"
        )

    # Calculate trends using testcase_module filtering
    all_trends = trend_analyzer.calculate_test_trends(db, release, module, use_testcase_module=True)

    # Get job IDs for new failure detection
    job_ids = [job.job_id for job in jobs]

    # Parse and validate priorities parameter
    priority_list = None
    if priorities:
        from app.services.data_service import VALID_PRIORITIES
        priority_list = [p.strip().upper() for p in priorities.split(',') if p.strip()]

        # Validate priority values
        invalid = [p for p in priority_list if p not in VALID_PRIORITIES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priorities: {', '.join(invalid)}. "
                       f"Valid values: {', '.join(sorted(VALID_PRIORITIES))}"
            )

    # Apply filters
    if flaky_only or always_failing_only or new_failures_only or priority_list:
        all_trends = trend_analyzer.filter_trends(
            all_trends,
            flaky_only=flaky_only,
            always_failing_only=always_failing_only,
            new_failures_only=new_failures_only,
            priorities=priority_list,
            job_ids=job_ids
        )

    # Calculate total before pagination
    total = len(all_trends)

    # Apply pagination
    paginated_trends = all_trends[skip:skip + limit]

    # Convert to response schema
    items = [
        TestTrendSchema(
            test_key=trend.test_key,
            file_path=trend.file_path,
            class_name=trend.class_name,
            test_name=trend.test_name,
            priority=trend.priority,
            results_by_job={
                job_id: status.value
                for job_id, status in trend.results_by_job.items()
            },
            rerun_info_by_job=trend.rerun_info_by_job,
            job_modules=trend.job_modules,  # Include Jenkins module for each job
            is_flaky=trend.is_flaky,
            is_always_failing=trend.is_always_failing,
            is_always_passing=trend.is_always_passing,
            is_new_failure=trend.is_new_failure(job_ids),
            latest_status=trend.latest_status.value if trend.latest_status else "UNKNOWN"
        )
        for trend in paginated_trends
    ]

    # Create pagination metadata
    metadata = PaginationMetadata(
        total=total,
        skip=skip,
        limit=limit,
        has_next=skip + limit < total,
        has_previous=skip > 0
    )

    return PaginatedResponse(items=items, metadata=metadata)


@router.get("/{release}/{module}/classes")
async def get_trends_by_class(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    db: Session = Depends(get_db)
):
    """
    Get test trends grouped by class name (path-based module).

    Module parameter now refers to testcase_module extracted from file paths.

    Args:
        release: Release name
        module: Testcase module name from file path
        db: Database session

    Returns:
        Dict mapping class_name -> list of test trends

    Raises:
        HTTPException: If release or module not found
    """
    # Get jobs that contain tests for this testcase_module (path-based)
    jobs = data_service.get_jobs_for_testcase_module(db, release, module)

    if not jobs:
        raise HTTPException(
            status_code=404,
            detail=f"No jobs found with tests for module '{module}' in release '{release}'"
        )

    # Calculate trends using testcase_module filtering
    trends = trend_analyzer.calculate_test_trends(db, release, module, use_testcase_module=True)

    # Group by class
    trends_by_class = trend_analyzer.get_trends_by_class(trends)

    # Get job IDs for new failure detection
    job_ids = [job.job_id for job in jobs]

    # Convert to response format
    result = {}
    for class_name, class_trends in trends_by_class.items():
        result[class_name] = [
            TestTrendSchema(
                test_key=trend.test_key,
                file_path=trend.file_path,
                class_name=trend.class_name,
                test_name=trend.test_name,
                priority=trend.priority,
                results_by_job={
                    job_id: status.value
                    for job_id, status in trend.results_by_job.items()
                },
                rerun_info_by_job=trend.rerun_info_by_job,
                job_modules=trend.job_modules,  # Include Jenkins module for each job
                is_flaky=trend.is_flaky,
                is_always_failing=trend.is_always_failing,
                is_always_passing=trend.is_always_passing,
                is_new_failure=trend.is_new_failure(job_ids),
                latest_status=trend.latest_status.value if trend.latest_status else "UNKNOWN"
            )
            for trend in class_trends
        ]

    return result
