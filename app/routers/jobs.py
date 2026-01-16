"""
Jobs API router.
Provides endpoints for accessing job details and test results.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_service
from app.models.schemas import (
    JobSummarySchema, TestResultSchema,
    PaginatedResponse, PaginationMetadata
)
from app.models.db_models import TestStatusEnum

router = APIRouter()


@router.get("/{release}/{module}", response_model=List[JobSummarySchema])
async def get_jobs(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Limit number of jobs (1-1000)"),
    db: Session = Depends(get_db)
):
    """
    Get all jobs for a specific module.

    Args:
        release: Release name
        module: Module name
        limit: Optional limit on number of jobs (most recent)
        db: Database session

    Returns:
        List of job summaries sorted by job_id descending

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

    jobs = data_service.get_jobs_for_module(db, release, module, limit=limit)

    return [
        JobSummarySchema(
            job_id=job.job_id,
            total=job.total,
            passed=job.passed,
            failed=job.failed,
            skipped=job.skipped,
            error=job.error,
            pass_rate=job.pass_rate,
            jenkins_url=job.jenkins_url,
            created_at=job.created_at,
            downloaded_at=job.downloaded_at
        )
        for job in jobs
    ]


@router.get("/{release}/{module}/{job_id}", response_model=JobSummarySchema)
async def get_job(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    db: Session = Depends(get_db)
):
    """
    Get detailed information for a specific job.

    Args:
        release: Release name
        module: Module name
        job_id: Job ID
        db: Database session

    Returns:
        Job summary with statistics

    Raises:
        HTTPException: If job not found
    """
    job = data_service.get_job(db, release, module, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found in module '{module}' of release '{release}'"
        )

    return JobSummarySchema(
        job_id=job.job_id,
        total=job.total,
        passed=job.passed,
        failed=job.failed,
        skipped=job.skipped,
        error=job.error,
        pass_rate=job.pass_rate,
        jenkins_url=job.jenkins_url,
        created_at=job.created_at,
        downloaded_at=job.downloaded_at
    )


@router.get("/{release}/{module}/{job_id}/tests", response_model=PaginatedResponse[TestResultSchema])
async def get_test_results(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    status: Optional[TestStatusEnum] = Query(None, description="Filter by test status"),
    topology: Optional[str] = Query(None, min_length=1, max_length=100, description="Filter by topology"),
    search: Optional[str] = Query(None, min_length=1, max_length=200, description="Search in test name, class, or file path"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return (1-1000)"),
    db: Session = Depends(get_db)
):
    """
    Get test results for a specific job with optional filters.

    Args:
        release: Release name
        module: Module name
        job_id: Job ID
        status: Optional status filter (PASSED, FAILED, SKIPPED, ERROR)
        topology: Optional topology filter
        search: Optional search string
        db: Database session

    Returns:
        List of test results

    Raises:
        HTTPException: If job not found
    """
    # Verify job exists
    job = data_service.get_job(db, release, module, job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found in module '{module}' of release '{release}'"
        )

    # Get all results matching filters
    all_results = data_service.get_test_results_for_job(
        db=db,
        release_name=release,
        module_name=module,
        job_id=job_id,
        status_filter=status,
        topology_filter=topology,
        search=search
    )

    # Calculate total before pagination
    total = len(all_results)

    # Apply pagination
    paginated_results = all_results[skip:skip + limit]

    # Convert to schema
    items = [
        TestResultSchema(
            test_key=result.test_key,
            test_name=result.test_name,
            class_name=result.class_name,
            file_path=result.file_path,
            status=result.status,
            setup_ip=result.setup_ip,
            topology=result.topology,
            was_rerun=result.was_rerun,
            rerun_still_failed=result.rerun_still_failed,
            failure_message=result.failure_message,
            order_index=result.order_index
        )
        for result in paginated_results
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


@router.get("/{release}/{module}/{job_id}/grouped")
async def get_test_results_grouped(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    db: Session = Depends(get_db)
):
    """
    Get test results grouped by topology and setup_ip.

    Args:
        release: Release name
        module: Module name
        job_id: Job ID
        db: Database session

    Returns:
        Nested dict: {topology: {setup_ip: [TestResult]}}

    Raises:
        HTTPException: If job not found
    """
    # Verify job exists
    job = data_service.get_job(db, release, module, job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found in module '{module}' of release '{release}'"
        )

    grouped = data_service.get_test_results_grouped_by_topology(
        db=db,
        release_name=release,
        module_name=module,
        job_id=job_id
    )

    # Convert to response format
    result = {}
    for topology, by_ip in grouped.items():
        result[topology] = {}
        for setup_ip, tests in by_ip.items():
            result[topology][setup_ip] = [
                TestResultSchema(
                    test_key=test.test_key,
                    test_name=test.test_name,
                    class_name=test.class_name,
                    file_path=test.file_path,
                    status=test.status,
                    setup_ip=test.setup_ip,
                    topology=test.topology,
                    was_rerun=test.was_rerun,
                    rerun_still_failed=test.rerun_still_failed,
                    failure_message=test.failure_message,
                    order_index=test.order_index
                )
                for test in tests
            ]

    return result
