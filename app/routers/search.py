"""
Search API router.
Provides endpoints for global test case search across modules and releases.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.services import testcase_metadata_service
from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release

router = APIRouter()


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
    # Search testcase metadata with case-insensitive partial match
    query = q.strip()

    metadata_results = db.query(TestcaseMetadata).filter(
        (TestcaseMetadata.test_case_id.ilike(f'%{query}%')) |
        (TestcaseMetadata.testrail_id.ilike(f'%{query}%')) |
        (TestcaseMetadata.testcase_name.ilike(f'%{query}%'))
    ).limit(limit).all()

    if not metadata_results:
        return []

    # For each test case, get execution history (last 10 jobs)
    results = []
    for metadata in metadata_results:
        # Get test results for this test name across all jobs
        test_results = db.query(
            TestResult,
            Job.job_id,
            Job.jenkins_url,
            Job.created_at,
            Module.name.label('module_name'),
            Release.name.label('release_name')
        ).join(
            Job, TestResult.job_id == Job.id
        ).join(
            Module, Job.module_id == Module.id
        ).join(
            Release, Module.release_id == Release.id
        ).filter(
            TestResult.test_name == metadata.testcase_name
        ).order_by(
            desc(Job.created_at)
        ).limit(10).all()

        # Build execution history
        execution_history = []
        for result in test_results:
            test_result, job_id, jenkins_url, created_at, module_name, release_name = result
            execution_history.append({
                'job_id': job_id,
                'module': module_name,
                'release': release_name,
                'status': test_result.status.value,
                'jenkins_url': jenkins_url,
                'created_at': created_at.isoformat() if created_at else None,
                'topology': test_result.topology,
                'was_rerun': test_result.was_rerun,
                'rerun_still_failed': test_result.rerun_still_failed
            })

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
    db: Session = Depends(get_db)
) -> Optional[Dict[str, Any]]:
    """
    Get detailed information for a specific test case by exact name match.

    Args:
        testcase_name: Exact test case name
        db: Database session

    Returns:
        Test case metadata and full execution history
    """
    # Get metadata
    metadata = testcase_metadata_service.get_testcase_metadata_by_name(db, testcase_name)
    if not metadata:
        return None

    # Get all execution history (not limited)
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
    ).all()

    # Build execution history
    execution_history = []
    for result in test_results:
        test_result, job_id, jenkins_url, created_at, version, module_name, release_name = result
        execution_history.append({
            'job_id': job_id,
            'module': module_name,
            'release': release_name,
            'version': version,
            'status': test_result.status.value,
            'jenkins_url': jenkins_url,
            'created_at': created_at.isoformat() if created_at else None,
            'topology': test_result.topology,
            'setup_ip': test_result.setup_ip,
            'was_rerun': test_result.was_rerun,
            'rerun_still_failed': test_result.rerun_still_failed,
            'failure_message': test_result.failure_message
        })

    # Calculate statistics
    total_runs = len(execution_history)
    passed_count = sum(1 for h in execution_history if h['status'] == 'PASSED')
    failed_count = sum(1 for h in execution_history if h['status'] == 'FAILED')
    error_count = sum(1 for h in execution_history if h['status'] == 'ERROR')
    skipped_count = sum(1 for h in execution_history if h['status'] == 'SKIPPED')

    pass_rate = (passed_count / (total_runs - skipped_count) * 100) if (total_runs - skipped_count) > 0 else 0.0

    return {
        'testcase_name': metadata.testcase_name,
        'test_case_id': metadata.test_case_id,
        'testrail_id': metadata.testrail_id,
        'priority': metadata.priority,
        'component': metadata.component,
        'automation_status': metadata.automation_status,
        'execution_history': execution_history,
        'statistics': {
            'total_runs': total_runs,
            'passed': passed_count,
            'failed': failed_count,
            'error': error_count,
            'skipped': skipped_count,
            'pass_rate': round(pass_rate, 2)
        }
    }
