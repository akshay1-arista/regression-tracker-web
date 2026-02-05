"""
Jobs API router.
Provides endpoints for accessing job details and test results.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_service
from app.services import error_clustering_service
from app.models.schemas import (
    JobSummarySchema, TestResultSchema,
    PaginatedResponse, PaginationMetadata,
    ClusterResponseSchema, ErrorClusterSchema, ErrorSignatureSchema,
    ClusterSummarySchema
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


@router.get("/{release}/{module}/{job_id}")
async def get_job(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    db: Session = Depends(get_db)
):
    """
    Get detailed information for a specific job with statistics.

    Args:
        release: Release name
        module: Module name
        job_id: Job ID
        db: Database session

    Returns:
        Job summary with topology statistics

    Raises:
        HTTPException: If job not found
    """
    job = data_service.get_job(db, release, module, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found in module '{module}' of release '{release}'"
        )

    # Get topology statistics
    topologies = data_service.get_unique_topologies(db, release, module, job_id)

    # Get status breakdown by topology
    topology_stats = data_service.get_topology_statistics(db, release, module, job_id)

    # Get unique modules
    modules = data_service.get_unique_modules(db, release, module, job_id)

    return {
        "job": JobSummarySchema(
            job_id=job.job_id,
            total=job.total,
            passed=job.passed,
            failed=job.failed,
            skipped=job.skipped,
            pass_rate=job.pass_rate,
            jenkins_url=job.jenkins_url,
            created_at=job.created_at,
            downloaded_at=job.downloaded_at
        ),
        "statistics": {
            "by_topology": topology_stats,
            "topologies": topologies,
            "modules": modules
        }
    }


@router.get("/{release}/{module}/{job_id}/tests", response_model=PaginatedResponse[TestResultSchema])
async def get_test_results(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    statuses: Optional[str] = Query(None, description="Comma-separated test statuses (PASSED,FAILED,SKIPPED)"),
    priorities: Optional[str] = Query(None, description="Comma-separated priorities (P0,P1,P2,P3,UNKNOWN)"),
    topology: Optional[str] = Query(None, min_length=1, max_length=100, description="Filter by topology"),
    testcase_module: Optional[str] = Query(None, min_length=1, max_length=100, description="Filter by testcase module"),
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
        statuses: Optional comma-separated status filters (PASSED, FAILED, SKIPPED)
        priorities: Optional comma-separated priority filters (P0, P1, P2, P3, UNKNOWN)
        topology: Optional topology filter
        testcase_module: Optional testcase module filter (e.g., business_policy, routing)
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

    # Parse comma-separated filters into lists
    status_filter = None
    if statuses:
        try:
            status_filter = [TestStatusEnum(s.strip()) for s in statuses.split(',') if s.strip()]
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value: {e}"
            )

    priority_filter = None
    if priorities:
        priority_filter = [p.strip().upper() for p in priorities.split(',') if p.strip()]

    all_results = data_service.get_test_results_for_job(
        db=db,
        release_name=release,
        module_name=module,
        job_id=job_id,
        status_filter=status_filter,
        topology_filter=topology,
        priority_filter=priority_filter,
        testcase_module_filter=testcase_module,
        search=search
    )

    # Calculate total before pagination
    total = len(all_results)

    # Apply pagination
    paginated_results = all_results[skip:skip + limit]

    # Fetch bugs for paginated results
    bugs_map = data_service.get_bugs_for_tests(db, paginated_results)

    # Convert to schema and attach bugs
    items = [
        TestResultSchema(
            test_key=result.test_key,
            test_name=result.test_name,
            class_name=result.class_name,
            file_path=result.file_path,
            status=result.status,
            setup_ip=result.setup_ip,
            jenkins_topology=result.jenkins_topology,
            topology_metadata=result.topology_metadata,
            priority=result.priority,
            testcase_module=result.testcase_module,
            was_rerun=result.was_rerun,
            rerun_still_failed=result.rerun_still_failed,
            failure_message=result.failure_message,
            order_index=result.order_index,
            bugs=bugs_map.get(result.test_key, [])
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

    grouped = data_service.get_test_results_grouped_by_jenkins_topology(
        db=db,
        release_name=release,
        module_name=module,
        job_id=job_id
    )

    # Fetch bugs for all tests
    all_tests = [test for by_ip in grouped.values() for tests in by_ip.values() for test in tests]
    bugs_map = data_service.get_bugs_for_tests(db, all_tests)

    # Convert to response format with bugs
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
                    jenkins_topology=test.jenkins_topology,
                    topology_metadata=test.topology_metadata,
                    priority=test.priority,
                    testcase_module=test.testcase_module,
                    was_rerun=test.was_rerun,
                    rerun_still_failed=test.rerun_still_failed,
                    failure_message=test.failure_message,
                    order_index=test.order_index,
                    bugs=bugs_map.get(test.test_key, [])
                )
                for test in tests
            ]

    return result


@router.get("/{release}/{module}/{job_id}/failures/clustered", response_model=ClusterResponseSchema)
async def get_clustered_failures(
    release: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9._-]+$"),
    module: str = Path(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9._-]+$"),
    job_id: str = Path(..., min_length=1, max_length=100),
    min_cluster_size: int = Query(1, ge=1, le=1000, description="Minimum cluster size to include"),
    sort_by: str = Query("count", regex="^(count|error_type)$", description="Sort order: count or error_type"),
    skip: int = Query(0, ge=0, description="Number of clusters to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum clusters to return"),
    db: Session = Depends(get_db)
):
    """
    Get error clusters for failed tests in a job.

    Groups similar test failures by error signature to identify common root causes.
    Uses hybrid clustering: exact fingerprint matching + fuzzy similarity (80% threshold).

    Args:
        release: Release name
        module: Module name
        job_id: Job ID
        min_cluster_size: Filter clusters with fewer tests (default: 1)
        sort_by: Sort order - "count" (descending) or "error_type" (alphabetical)
        skip: Pagination offset
        limit: Maximum clusters to return (1-1000)
        db: Database session

    Returns:
        ClusterResponseSchema with:
        - clusters: List of error clusters with signature, count, affected tests
        - summary: Statistics (total failures, unique clusters, largest cluster)

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

    # Fetch failed tests with failure messages
    failures = data_service.get_failed_tests_for_job(db, release, module, job_id)

    if not failures:
        # Return empty response if no failures
        return ClusterResponseSchema(
            clusters=[],
            summary=ClusterSummarySchema(
                total_failures=0,
                unique_clusters=0,
                largest_cluster=0,
                unclustered=0
            )
        )

    # Perform clustering
    cluster_summary = error_clustering_service.cluster_failures(failures)

    # Apply filters
    filtered_clusters = [
        cluster for cluster in cluster_summary.clusters
        if cluster.count >= min_cluster_size
    ]

    # Apply sorting
    if sort_by == "count":
        filtered_clusters.sort(key=lambda c: c.count, reverse=True)
    elif sort_by == "error_type":
        filtered_clusters.sort(key=lambda c: c.signature.error_type)

    # Apply pagination
    total_clusters = len(filtered_clusters)
    paginated_clusters = filtered_clusters[skip:skip+limit]

    # Fetch bugs for all tests in all paginated clusters (avoid N+1 query)
    all_tests = [test for cluster in paginated_clusters for test in cluster.test_results]
    bugs_map = data_service.get_bugs_for_tests(db, all_tests)

    # Convert to response schema
    response_clusters = []
    for cluster in paginated_clusters:
        # Get test keys for affected_tests list
        affected_tests = [test.test_key for test in cluster.test_results]

        # Convert test results to TestResultSchema
        test_schemas = []

        for test in cluster.test_results:
            test_schema = TestResultSchema(
                test_key=test.test_key,
                test_name=test.test_name,
                class_name=test.class_name,
                file_path=test.file_path,
                status=test.status,
                setup_ip=test.setup_ip,
                jenkins_topology=test.jenkins_topology,
                topology_metadata=test.topology_metadata,
                priority=test.priority,
                was_rerun=test.was_rerun,
                rerun_still_failed=test.rerun_still_failed,
                failure_message=test.failure_message,
                order_index=test.order_index,
                bugs=bugs_map.get(test.test_key, [])
            )
            test_schemas.append(test_schema)

        # Create cluster schema
        cluster_schema = ErrorClusterSchema(
            signature=ErrorSignatureSchema(
                error_type=cluster.signature.error_type,
                file_path=cluster.signature.file_path,
                line_number=cluster.signature.line_number,
                normalized_message=cluster.signature.normalized_message,
                fingerprint=cluster.signature.fingerprint
            ),
            count=cluster.count,
            affected_tests=affected_tests,
            affected_topologies=sorted(list(cluster.affected_topologies)),
            affected_priorities=sorted(list(cluster.affected_priorities)),
            sample_message=cluster.sample_message,
            match_type=cluster.match_type,
            test_results=test_schemas
        )
        response_clusters.append(cluster_schema)

    # Build summary (use original cluster_summary for accurate counts)
    summary = ClusterSummarySchema(
        total_failures=cluster_summary.total_failures,
        unique_clusters=cluster_summary.unique_clusters,
        largest_cluster=cluster_summary.largest_cluster,
        unclustered=cluster_summary.unclustered
    )

    return ClusterResponseSchema(
        clusters=response_clusters,
        summary=summary
    )
