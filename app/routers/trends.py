"""
Trends API router.
Provides endpoints for test trend analysis across jobs.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_service, trend_analyzer
from app.models.schemas import TestTrendSchema

router = APIRouter()


@router.get("/{release}/{module}", response_model=List[TestTrendSchema])
async def get_trends(
    release: str,
    module: str,
    flaky_only: bool = Query(False, description="Only return flaky tests"),
    always_failing_only: bool = Query(False, description="Only return always-failing tests"),
    new_failures_only: bool = Query(False, description="Only return new failures"),
    db: Session = Depends(get_db)
):
    """
    Get test trends for a specific release/module with optional filters.

    Args:
        release: Release name
        module: Module name
        flaky_only: If True, only return flaky tests
        always_failing_only: If True, only return always-failing tests
        new_failures_only: If True, only return new failures
        db: Database session

    Returns:
        List of test trends with status across all jobs

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

    # Calculate trends
    trends = trend_analyzer.calculate_test_trends(db, release, module)

    # Get job IDs for new failure detection
    jobs = data_service.get_jobs_for_module(db, release, module)
    job_ids = [job.job_id for job in jobs]

    # Apply filters
    if flaky_only or always_failing_only or new_failures_only:
        trends = trend_analyzer.filter_trends(
            trends,
            flaky_only=flaky_only,
            always_failing_only=always_failing_only,
            new_failures_only=new_failures_only,
            job_ids=job_ids
        )

    # Convert to response schema
    return [
        TestTrendSchema(
            test_key=trend.test_key,
            file_path=trend.file_path,
            class_name=trend.class_name,
            test_name=trend.test_name,
            results_by_job={
                job_id: status.value
                for job_id, status in trend.results_by_job.items()
            },
            rerun_info_by_job=trend.rerun_info_by_job,
            is_flaky=trend.is_flaky,
            is_always_failing=trend.is_always_failing,
            is_always_passing=trend.is_always_passing,
            is_new_failure=trend.is_new_failure(job_ids),
            latest_status=trend.latest_status.value if trend.latest_status else "UNKNOWN"
        )
        for trend in trends
    ]


@router.get("/{release}/{module}/classes")
async def get_trends_by_class(
    release: str,
    module: str,
    db: Session = Depends(get_db)
):
    """
    Get test trends grouped by class name.

    Args:
        release: Release name
        module: Module name
        db: Database session

    Returns:
        Dict mapping class_name -> list of test trends

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

    # Calculate trends
    trends = trend_analyzer.calculate_test_trends(db, release, module)

    # Group by class
    trends_by_class = trend_analyzer.get_trends_by_class(trends)

    # Get job IDs for new failure detection
    jobs = data_service.get_jobs_for_module(db, release, module)
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
                results_by_job={
                    job_id: status.value
                    for job_id, status in trend.results_by_job.items()
                },
                rerun_info_by_job=trend.rerun_info_by_job,
                is_flaky=trend.is_flaky,
                is_always_failing=trend.is_always_failing,
                is_always_passing=trend.is_always_passing,
                is_new_failure=trend.is_new_failure(job_ids),
                latest_status=trend.latest_status.value if trend.latest_status else "UNKNOWN"
            )
            for trend in class_trends
        ]

    return result
