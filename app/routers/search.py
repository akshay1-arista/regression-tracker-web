"""
Search API router.
Provides endpoints for global test case search across modules and releases.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.services import testcase_metadata_service
from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release
from app.utils.helpers import escape_like_pattern

router = APIRouter()

# Constants
DEFAULT_EXECUTION_HISTORY_LIMIT = 10


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
        'topology': test_result.topology,
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

    Args:
        db: Database session
        testcase_names: List of test case names to fetch history for
        limit_per_test: Maximum history records per test (None = unlimited)

    Returns:
        Dictionary mapping testcase_name to list of execution history dicts
    """
    # Subquery with row_number to rank results by created_at per test
    from sqlalchemy import literal_column, case

    subq = db.query(
        TestResult.id,
        TestResult.test_name,
        TestResult.status,
        TestResult.topology,
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
        TestResult.test_name.in_(testcase_names)
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
            'topology': row.topology,
            'was_rerun': row.was_rerun,
            'rerun_still_failed': row.rerun_still_failed,
            'version': row.version,
            'setup_ip': row.setup_ip,
            'failure_message': row.failure_message
        })

    return history_by_test


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

    Args:
        testcase_name: Exact test case name
        limit: Maximum number of history records to return
        offset: Number of records to skip (for pagination)
        db: Database session

    Returns:
        Test case metadata and paginated execution history

    Raises:
        HTTPException: 404 if test case not found
    """
    # Get metadata
    metadata = testcase_metadata_service.get_testcase_metadata_by_name(db, testcase_name)
    if not metadata:
        raise HTTPException(
            status_code=404,
            detail=f"Test case '{testcase_name}' not found"
        )

    # Get total count for pagination
    total_count = db.query(func.count(TestResult.id)).join(
        Job, TestResult.job_id == Job.id
    ).filter(
        TestResult.test_name == testcase_name
    ).scalar()

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
    passed_count = sum(1 for h in execution_history if h['status'] == 'PASSED')
    failed_count = sum(1 for h in execution_history if h['status'] == 'FAILED')
    error_count = sum(1 for h in execution_history if h['status'] == 'ERROR')
    skipped_count = sum(1 for h in execution_history if h['status'] == 'SKIPPED')

    total_non_skipped = len(execution_history) - skipped_count
    pass_rate = (passed_count / total_non_skipped * 100) if total_non_skipped > 0 else None

    return {
        'testcase_name': metadata.testcase_name,
        'test_case_id': metadata.test_case_id,
        'testrail_id': metadata.testrail_id,
        'priority': metadata.priority,
        'component': metadata.component,
        'automation_status': metadata.automation_status,
        'execution_history': execution_history,
        'statistics': {
            'total_runs': len(execution_history),
            'passed': passed_count,
            'failed': failed_count,
            'error': error_count,
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
