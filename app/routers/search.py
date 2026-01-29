"""
Search API router.
Provides endpoints for global test case search across modules and releases.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from app.database import get_db
from app.services import testcase_metadata_service
from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release
from app.utils.helpers import escape_like_pattern
from app.utils.test_name_utils import normalize_test_name
from app.constants import TEST_STATUS_PASSED, TEST_STATUS_FAILED, TEST_STATUS_SKIPPED

router = APIRouter()

# Constants
DEFAULT_EXECUTION_HISTORY_LIMIT = 10


def _normalize_test_name_sql(test_name_column):
    """
    Create SQL expression to normalize parameterized test names.

    Extracts base name from parameterized tests:
    - test_foo[param] -> test_foo
    - test_bar -> test_bar (unchanged)

    Args:
        test_name_column: SQLAlchemy column reference (e.g., TestResult.test_name)

    Returns:
        SQLAlchemy CASE expression that normalizes test names
    """
    return case(
        (func.instr(test_name_column, '[') > 0,
         func.substr(test_name_column, 1, func.instr(test_name_column, '[') - 1)),
        else_=test_name_column
    )


def _build_execution_history_dict(
    test_result: TestResult,
    job_id: str,
    jenkins_url: Optional[str],
    created_at: Optional[Any],
    module_name: str,
    release_name: str,
    version: Optional[str] = None,
    include_failure_message: bool = False
) -> Dict[str, Any]:
    """
    Build execution history dictionary from query result.

    Args:
        test_result: TestResult object
        job_id: Job ID
        jenkins_url: Jenkins URL
        created_at: Job created timestamp
        module_name: Module name
        release_name: Release name
        version: Optional job version
        include_failure_message: Whether to include failure message

    Returns:
        Dictionary with execution history data
    """
    history = {
        'job_id': job_id,
        'module': module_name,
        'release': release_name,
        'status': test_result.status.value,
        'jenkins_url': jenkins_url,
        'created_at': created_at.isoformat() if created_at else None,
        'jenkins_topology': test_result.jenkins_topology,
        'topology_metadata': test_result.topology_metadata,
        'was_rerun': test_result.was_rerun,
        'rerun_still_failed': test_result.rerun_still_failed
    }

    if version is not None:
        history['version'] = version
        history['setup_ip'] = test_result.setup_ip

    if include_failure_message:
        history['failure_message'] = test_result.failure_message

    return history


def _get_execution_history_batch(
    db: Session,
    testcase_names: List[str],
    limit_per_test: Optional[int] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get execution history for multiple test cases in a single query.

    Solves the N+1 query problem by fetching all execution histories at once.
    Handles parameterized tests by normalizing test_name before matching.

    Args:
        db: Database session
        testcase_names: List of base test case names to fetch history for
        limit_per_test: Maximum history records per test (None = unlimited)

    Returns:
        Dictionary mapping testcase_name to list of execution history dicts
    """
    # Subquery with row_number to rank results by created_at per test
    from sqlalchemy import literal_column

    # Use SQL normalization to match parameterized tests
    # This allows test_results.test_name = "test_foo[Hub]" to match testcase_names = ["test_foo"]
    normalized_test_name = _normalize_test_name_sql(TestResult.test_name)

    subq = db.query(
        TestResult.id,
        TestResult.test_name,
        TestResult.status,
        TestResult.jenkins_topology,
        TestResult.topology_metadata,
        TestResult.was_rerun,
        TestResult.rerun_still_failed,
        TestResult.setup_ip,
        TestResult.failure_message,
        Job.job_id,
        Job.jenkins_url,
        Job.created_at,
        Job.version,
        Module.name.label('module_name'),
        Release.name.label('release_name'),
        func.row_number().over(
            partition_by=TestResult.test_name,
            order_by=desc(Job.created_at)
        ).label('rn')
    ).join(
        Job, TestResult.job_id == Job.id
    ).join(
        Module, Job.module_id == Module.id
    ).join(
        Release, Module.release_id == Release.id
    ).filter(
        normalized_test_name.in_(testcase_names)  # Use normalized name for matching
    ).subquery()

    # Build main query
    query = db.query(subq)

    if limit_per_test:
        query = query.filter(subq.c.rn <= limit_per_test)

    results = query.all()

    # Group by testcase_name
    history_by_test = {}
    for row in results:
        test_name = row.test_name
        if test_name not in history_by_test:
            history_by_test[test_name] = []

        # Build history dict directly from row
        history_by_test[test_name].append({
            'job_id': row.job_id,
            'module': row.module_name,
            'release': row.release_name,
            'status': row.status.value if hasattr(row.status, 'value') else row.status,
            'jenkins_url': row.jenkins_url,
            'created_at': row.created_at.isoformat() if row.created_at else None,
            'jenkins_topology': row.jenkins_topology,
            'topology_metadata': row.topology_metadata,
            'was_rerun': row.was_rerun,
            'rerun_still_failed': row.rerun_still_failed,
            'version': row.version,
            'setup_ip': row.setup_ip,
            'failure_message': row.failure_message
        })

    return history_by_test


@router.get("/autocomplete")
async def autocomplete_testcases(
    q: str = Query(..., min_length=2, max_length=200, description="Search query for autocomplete"),
    limit: int = Query(10, ge=1, le=20, description="Maximum number of suggestions (1-20)"),
    db: Session = Depends(get_db)
) -> List[Dict[str, str]]:
    """
    Get autocomplete suggestions for test case search.

    Returns lightweight suggestions (no execution history) for fast autocomplete.

    Args:
        q: Search query string (minimum 2 characters)
        limit: Maximum number of suggestions to return
        db: Database session

    Returns:
        List of test case suggestions with testcase_name, test_case_id, priority
    """
    # Escape LIKE pattern
    query_str = q.strip()
    escaped_query = escape_like_pattern(query_str)
    search_pattern = f'%{escaped_query}%'

    # Search with same logic as main search but return minimal data
    suggestions = db.query(
        TestcaseMetadata.testcase_name,
        TestcaseMetadata.test_case_id,
        TestcaseMetadata.priority
    ).filter(
        (TestcaseMetadata.test_case_id.ilike(search_pattern)) |
        (TestcaseMetadata.testrail_id.ilike(search_pattern)) |
        (TestcaseMetadata.testcase_name.ilike(search_pattern))
    ).limit(limit).all()

    return [
        {
            'testcase_name': s.testcase_name,
            'test_case_id': s.test_case_id or '',
            'priority': s.priority or 'UNKNOWN'
        }
        for s in suggestions
    ]


@router.get("/testcases")
async def search_testcases(
    q: str = Query(..., min_length=1, max_length=200, description="Search query for test_case_id, testrail_id, or testcase_name"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results (1-100)"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Global search for test cases across all modules and releases.

    Searches TestcaseMetadata by:
    - test_case_id (e.g., "TC-1234")
    - testrail_id (e.g., "C12345")
    - testcase_name (partial match)

    Returns test metadata with execution history from the last 10 jobs.

    Args:
        q: Search query string
        limit: Maximum number of test cases to return
        db: Database session

    Returns:
        List of test case results with metadata and execution history:
        [{
            "testcase_name": str,
            "test_case_id": str,
            "testrail_id": str,
            "priority": str,
            "component": str,
            "execution_history": [{
                "job_id": str,
                "module": str,
                "release": str,
                "status": str,
                "jenkins_url": str,
                "created_at": str
            }]
        }]
    """
    # Escape LIKE pattern to prevent SQL injection
    query_str = q.strip()
    escaped_query = escape_like_pattern(query_str)
    search_pattern = f'%{escaped_query}%'

    # Search testcase metadata with case-insensitive partial match
    metadata_results = db.query(TestcaseMetadata).filter(
        (TestcaseMetadata.test_case_id.ilike(search_pattern)) |
        (TestcaseMetadata.testrail_id.ilike(search_pattern)) |
        (TestcaseMetadata.testcase_name.ilike(search_pattern))
    ).limit(limit).all()

    if not metadata_results:
        return []

    # Extract all testcase names for batch query
    testcase_names = [m.testcase_name for m in metadata_results]

    # Single batched query for ALL execution history (fixes N+1 problem)
    history_by_test = _get_execution_history_batch(
        db,
        testcase_names,
        limit_per_test=DEFAULT_EXECUTION_HISTORY_LIMIT
    )

    # Build results
    results = []
    for metadata in metadata_results:
        execution_history = history_by_test.get(metadata.testcase_name, [])

        # Remove fields not needed for search results
        for h in execution_history:
            h.pop('version', None)
            h.pop('setup_ip', None)
            h.pop('failure_message', None)

        results.append({
            'testcase_name': metadata.testcase_name,
            'test_case_id': metadata.test_case_id,
            'testrail_id': metadata.testrail_id,
            'priority': metadata.priority,
            'component': metadata.component,
            'automation_status': metadata.automation_status,
            'test_class_name': metadata.test_class_name,
            'test_path': metadata.test_path,
            'test_state': metadata.test_state,
            'execution_history': execution_history,
            'total_executions': len(execution_history)
        })

    return results


@router.get("/testcases/{testcase_name}")
async def get_testcase_details(
    testcase_name: str,
    limit: int = Query(100, ge=1, le=500, description="Max history records (1-500)"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed information for a specific test case by exact name match.

    Metadata is optional - if the test case has execution history but no metadata,
    it will still return the history with default/unknown values for metadata fields.

    Handles parameterized tests by normalizing test names for metadata lookup.

    Args:
        testcase_name: Exact test case name (may include parameters like test_foo[param])
        limit: Maximum number of history records to return
        offset: Number of records to skip (for pagination)
        db: Database session

    Returns:
        Test case metadata and paginated execution history

    Raises:
        HTTPException: 404 if test case has neither metadata nor execution history
    """
    # Normalize test name for metadata lookup (handles parameterized tests)
    # E.g., test_foo[Hub] -> test_foo
    normalized_name = normalize_test_name(testcase_name)

    # Get metadata using normalized name (optional - may not exist for all test cases)
    metadata = testcase_metadata_service.get_testcase_metadata_by_name(db, normalized_name)

    # Get total count for pagination
    total_count = db.query(func.count(TestResult.id)).join(
        Job, TestResult.job_id == Job.id
    ).filter(
        TestResult.test_name == testcase_name
    ).scalar()

    # If no metadata AND no execution history, return 404
    if not metadata and total_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Test case '{testcase_name}' not found in metadata or execution history"
        )

    # Get paginated execution history
    test_results = db.query(
        TestResult,
        Job.job_id,
        Job.jenkins_url,
        Job.created_at,
        Job.version,
        Module.name.label('module_name'),
        Release.name.label('release_name')
    ).join(
        Job, TestResult.job_id == Job.id
    ).join(
        Module, Job.module_id == Module.id
    ).join(
        Release, Module.release_id == Release.id
    ).filter(
        TestResult.test_name == testcase_name
    ).order_by(
        desc(Job.created_at)
    ).offset(offset).limit(limit).all()

    # Build execution history
    execution_history = []
    for result in test_results:
        test_result, job_id, jenkins_url, created_at, version, module_name, release_name = result
        execution_history.append(_build_execution_history_dict(
            test_result, job_id, jenkins_url, created_at,
            module_name, release_name, version=version,
            include_failure_message=True
        ))

    # Calculate statistics (on paginated results for now - could be optimized)
    # For accurate stats, should query all results, but that's expensive
    # Compromise: calculate stats from current page + note in docs
    passed_count = sum(1 for h in execution_history if h['status'] == TEST_STATUS_PASSED)
    failed_count = sum(1 for h in execution_history if h['status'] == TEST_STATUS_FAILED)  # Includes ERROR (converted to FAILED)
    skipped_count = sum(1 for h in execution_history if h['status'] == TEST_STATUS_SKIPPED)

    # Calculate pass rate as percentage of all tests (including skipped)
    total_runs = len(execution_history)
    pass_rate = (passed_count / total_runs * 100) if total_runs > 0 else None

    return {
        'testcase_name': metadata.testcase_name if metadata else testcase_name,
        'test_case_id': metadata.test_case_id if metadata else None,
        'testrail_id': metadata.testrail_id if metadata else None,
        'priority': metadata.priority if metadata else 'UNKNOWN',
        'component': metadata.component if metadata else None,
        'automation_status': metadata.automation_status if metadata else None,
        'test_class_name': metadata.test_class_name if metadata else None,
        'test_path': metadata.test_path if metadata else None,
        'test_state': metadata.test_state if metadata else None,
        'execution_history': execution_history,
        'statistics': {
            'total_runs': len(execution_history),
            'passed': passed_count,
            'failed': failed_count,  # Includes both FAILED and ERROR statuses
            'skipped': skipped_count,
            'pass_rate': round(pass_rate, 2) if pass_rate is not None else None
        },
        'pagination': {
            'total': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': (offset + limit) < total_count
        }
    }


@router.get("/statistics")
async def get_testcase_statistics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get comprehensive statistics about AUTOMATED test cases and their execution history.

    Only considers testcases where automation_status is 'Hapy Automated' or 'Automated'.

    Returns statistics including:
    - Total number of automated test cases
    - Number of automated test cases with execution history
    - Number of automated test cases without any execution history
    - All the above statistics broken down by priority (P0, P1, P2, P3, UNKNOWN)

    Args:
        db: Database session

    Returns:
        Dictionary with comprehensive statistics:
        {
            "automated": {
                "total": int,
                "with_history": int,
                "without_history": int
            },
            "by_priority": {
                "P0": {"total": int, "with_history": int, "without_history": int},
                "P1": {...},
                "P2": {...},
                "P3": {...},
                "UNKNOWN": {...}
            }
        }
    """
    # Get only AUTOMATED testcases (Hapy Automated or Automated status)
    automated_testcases = db.query(
        TestcaseMetadata.testcase_name,
        TestcaseMetadata.priority
    ).filter(
        TestcaseMetadata.automation_status.in_(['Hapy Automated', 'Automated'])
    ).all()

    # Get distinct testcase names that have execution history
    testcases_with_history = db.query(
        TestResult.test_name
    ).distinct().all()
    testcases_with_history_set = {tc.test_name for tc in testcases_with_history}

    # Initialize statistics structure
    priorities = ['P0', 'P1', 'P2', 'P3', 'UNKNOWN']
    by_priority = {p: {'total': 0, 'with_history': 0, 'without_history': 0} for p in priorities}

    overall_total = len(automated_testcases)
    overall_with_history = 0
    overall_without_history = 0

    # Calculate statistics for automated testcases only
    for testcase in automated_testcases:
        testcase_name = testcase.testcase_name
        priority = testcase.priority or 'UNKNOWN'

        # Normalize priority - treat any non-standard priority as UNKNOWN
        if priority not in priorities:
            priority = 'UNKNOWN'

        # Increment total for this priority
        by_priority[priority]['total'] += 1

        # Check if testcase has execution history
        if testcase_name in testcases_with_history_set:
            by_priority[priority]['with_history'] += 1
            overall_with_history += 1
        else:
            by_priority[priority]['without_history'] += 1
            overall_without_history += 1

    return {
        'automated': {
            'total': overall_total,
            'with_history': overall_with_history,
            'without_history': overall_without_history
        },
        'by_priority': by_priority
    }


@router.get("/filtered-testcases")
async def get_filtered_testcases(
    priority: Optional[str] = Query(None, description="Filter by priority (P0, P1, P2, P3, UNKNOWN, or null for all)"),
    has_history: Optional[bool] = Query(None, description="Filter by execution history (true=with history, false=without history, null=all)"),
    module: Optional[str] = Query(None, description="Filter by module name"),
    test_state: Optional[str] = Query(None, description="Filter by test_state (PROD, STAGING, or comma-separated like 'PROD,STAGING')"),
    component: Optional[str] = Query(None, description="Filter by component"),
    topology: Optional[str] = Query(None, description="Filter by topology"),
    job_id: Optional[str] = Query(None, description="Filter execution history by specific job_id or parent_job_id"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of results (1-500)"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get filtered list of AUTOMATED testcases based on priority, execution history, and metadata.

    Only returns testcases where automation_status is 'Hapy Automated' or 'Automated'.

    Args:
        priority: Filter by priority (optional)
        has_history: Filter by execution history status (optional)
        module: Filter by module name (optional)
        test_state: Filter by test_state (supports comma-separated values, optional)
        component: Filter by component (optional)
        topology: Filter by topology (optional)
        job_id: Filter execution history by specific job_id or parent_job_id (optional)
        limit: Maximum number of results to return
        db: Database session

    Returns:
        List of testcases matching the filters
    """
    # Start with base query for automated testcases
    query = db.query(TestcaseMetadata).filter(
        TestcaseMetadata.automation_status.in_(['Hapy Automated', 'Automated'])
    )

    # Apply priority filter if provided
    if priority:
        if priority == 'UNKNOWN':
            query = query.filter(
                (TestcaseMetadata.priority.is_(None)) |
                (~TestcaseMetadata.priority.in_(['P0', 'P1', 'P2', 'P3']))
            )
        else:
            query = query.filter(TestcaseMetadata.priority == priority)

    # Apply module filter if provided
    if module:
        query = query.filter(TestcaseMetadata.module == module)

    # Apply test_state filter if provided
    if test_state:
        # Support comma-separated values (e.g., "PROD,STAGING")
        test_states = [s.strip() for s in test_state.split(',')]
        query = query.filter(TestcaseMetadata.test_state.in_(test_states))

    # Apply component filter if provided
    if component:
        query = query.filter(TestcaseMetadata.component == component)

    # Apply topology filter if provided
    if topology:
        query = query.filter(TestcaseMetadata.topology == topology)

    # Apply execution history filter if provided
    if has_history is not None:
        # If job_id is provided, filter by execution history in that specific job/parent_job
        if job_id:
            # Import Job model here to avoid circular imports
            from app.models.db_models import Job

            # Get all jobs that match this parent_job_id OR this job_id
            jobs_query = db.query(Job.id).filter(
                (Job.parent_job_id == job_id) | (Job.job_id == job_id)
            )
            job_ids = [job.id for job in jobs_query.all()]

            if job_ids:
                # Get testcases executed in these specific jobs only
                testcases_with_history = db.query(TestResult.test_name).filter(
                    TestResult.job_id.in_(job_ids)
                ).distinct().all()
            else:
                testcases_with_history = []
        else:
            # Get all testcases with execution history (across all jobs)
            testcases_with_history = db.query(TestResult.test_name).distinct().all()

        testcases_with_history_set = {tc.test_name for tc in testcases_with_history}

        if has_history:
            # Filter to only testcases WITH history
            query = query.filter(TestcaseMetadata.testcase_name.in_(testcases_with_history_set))
        else:
            # Filter to only testcases WITHOUT history
            query = query.filter(~TestcaseMetadata.testcase_name.in_(testcases_with_history_set))

    # Apply limit AFTER all filters
    testcases = query.limit(limit).all()

    # Build response
    return [
        {
            'testcase_name': tc.testcase_name,
            'test_case_id': tc.test_case_id,
            'testrail_id': tc.testrail_id,
            'priority': tc.priority,
            'component': tc.component,
            'automation_status': tc.automation_status,
            'topology': tc.topology,
            'module': tc.module,
            'test_state': tc.test_state,
            'test_class_name': tc.test_class_name
        }
        for tc in testcases
    ]
