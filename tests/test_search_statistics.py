"""
Tests for the search statistics endpoint.
"""
import pytest
from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_search_statistics_empty_db(test_db):
    """Test statistics endpoint with empty database."""
    from app.routers.search import get_testcase_statistics

    result = await get_testcase_statistics(db=test_db)

    assert result['overall']['total_testcases'] == 0
    assert result['overall']['with_history'] == 0
    assert result['overall']['without_history'] == 0

    # All priorities should be 0
    for priority in ['P0', 'P1', 'P2', 'P3', 'UNKNOWN']:
        assert result['by_priority'][priority]['total'] == 0
        assert result['by_priority'][priority]['with_history'] == 0
        assert result['by_priority'][priority]['without_history'] == 0


def test_search_statistics_api_endpoint_empty(client):
    """Test statistics API endpoint with empty database via TestClient."""
    response = client.get('/api/v1/search/statistics')

    assert response.status_code == 200
    data = response.json()

    assert 'overall' in data
    assert 'by_priority' in data
    assert data['overall']['total_testcases'] == 0
    assert data['overall']['with_history'] == 0
    assert data['overall']['without_history'] == 0


@pytest.mark.asyncio
async def test_search_statistics_with_metadata_only(test_db):
    """Test statistics when testcases exist but have no execution history."""
    # Add testcases with different priorities
    testcases = [
        TestcaseMetadata(testcase_name='test1', test_case_id='TC-001', priority='P0'),
        TestcaseMetadata(testcase_name='test2', test_case_id='TC-002', priority='P1'),
        TestcaseMetadata(testcase_name='test3', test_case_id='TC-003', priority='P2'),
        TestcaseMetadata(testcase_name='test4', test_case_id='TC-004', priority='P3'),
        TestcaseMetadata(testcase_name='test5', test_case_id='TC-005', priority=None),  # UNKNOWN
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = await get_testcase_statistics(db=test_db)

    # Overall stats
    assert result['overall']['total_testcases'] == 5
    assert result['overall']['with_history'] == 0
    assert result['overall']['without_history'] == 5

    # By priority
    assert result['by_priority']['P0']['total'] == 1
    assert result['by_priority']['P0']['without_history'] == 1
    assert result['by_priority']['P1']['total'] == 1
    assert result['by_priority']['P2']['total'] == 1
    assert result['by_priority']['P3']['total'] == 1
    assert result['by_priority']['UNKNOWN']['total'] == 1


@pytest.mark.asyncio
async def test_search_statistics_with_execution_history(test_db, sample_release):
    """Test statistics when testcases have execution history."""
    # Create release, module, and job
    module = Module(release_id=sample_release.id, name='test_module')
    test_db.add(module)
    test_db.commit()

    job = Job(
        module_id=module.id,
        job_id='100',
        total=3,
        passed=3,
        pass_rate=100.0
    )
    test_db.add(job)
    test_db.commit()

    # Add testcases
    testcases = [
        TestcaseMetadata(testcase_name='test_with_history_p0', test_case_id='TC-001', priority='P0'),
        TestcaseMetadata(testcase_name='test_with_history_p1', test_case_id='TC-002', priority='P1'),
        TestcaseMetadata(testcase_name='test_without_history', test_case_id='TC-003', priority='P2'),
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    # Add test results for some testcases
    test_results = [
        TestResult(
            job_id=job.id,
            test_name='test_with_history_p0',
            status='PASSED',
            priority='P0'
        ),
        TestResult(
            job_id=job.id,
            test_name='test_with_history_p1',
            status='PASSED',
            priority='P1'
        ),
    ]
    for tr in test_results:
        test_db.add(tr)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = await get_testcase_statistics(db=test_db)

    # Overall stats
    assert result['overall']['total_testcases'] == 3
    assert result['overall']['with_history'] == 2
    assert result['overall']['without_history'] == 1

    # By priority
    assert result['by_priority']['P0']['total'] == 1
    assert result['by_priority']['P0']['with_history'] == 1
    assert result['by_priority']['P0']['without_history'] == 0

    assert result['by_priority']['P1']['total'] == 1
    assert result['by_priority']['P1']['with_history'] == 1
    assert result['by_priority']['P1']['without_history'] == 0

    assert result['by_priority']['P2']['total'] == 1
    assert result['by_priority']['P2']['with_history'] == 0
    assert result['by_priority']['P2']['without_history'] == 1


@pytest.mark.asyncio
async def test_search_statistics_mixed_priorities(test_db, sample_release):
    """Test statistics with mixed priorities and execution histories."""
    # Create release, module, and job
    module = Module(release_id=sample_release.id, name='test_module')
    test_db.add(module)
    test_db.commit()

    job = Job(module_id=module.id, job_id='100', total=5, passed=5, pass_rate=100.0)
    test_db.add(job)
    test_db.commit()

    # Add 10 testcases with various priorities
    testcases = [
        # P0: 3 total, 2 with history
        TestcaseMetadata(testcase_name='p0_test1', test_case_id='TC-001', priority='P0'),
        TestcaseMetadata(testcase_name='p0_test2', test_case_id='TC-002', priority='P0'),
        TestcaseMetadata(testcase_name='p0_test3', test_case_id='TC-003', priority='P0'),
        # P1: 2 total, 1 with history
        TestcaseMetadata(testcase_name='p1_test1', test_case_id='TC-004', priority='P1'),
        TestcaseMetadata(testcase_name='p1_test2', test_case_id='TC-005', priority='P1'),
        # P2: 2 total, 0 with history
        TestcaseMetadata(testcase_name='p2_test1', test_case_id='TC-006', priority='P2'),
        TestcaseMetadata(testcase_name='p2_test2', test_case_id='TC-007', priority='P2'),
        # UNKNOWN: 3 total, 2 with history
        TestcaseMetadata(testcase_name='unknown_test1', test_case_id='TC-008', priority=None),
        TestcaseMetadata(testcase_name='unknown_test2', test_case_id='TC-009', priority=None),
        TestcaseMetadata(testcase_name='unknown_test3', test_case_id='TC-010', priority=None),
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    # Add test results for some testcases
    test_results = [
        TestResult(job_id=job.id, test_name='p0_test1', status='PASSED', priority='P0'),
        TestResult(job_id=job.id, test_name='p0_test2', status='PASSED', priority='P0'),
        TestResult(job_id=job.id, test_name='p1_test1', status='PASSED', priority='P1'),
        TestResult(job_id=job.id, test_name='unknown_test1', status='PASSED', priority=None),
        TestResult(job_id=job.id, test_name='unknown_test2', status='PASSED', priority=None),
    ]
    for tr in test_results:
        test_db.add(tr)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = await get_testcase_statistics(db=test_db)

    # Overall stats
    assert result['overall']['total_testcases'] == 10
    assert result['overall']['with_history'] == 5
    assert result['overall']['without_history'] == 5

    # P0: 3 total, 2 with history, 1 without
    assert result['by_priority']['P0']['total'] == 3
    assert result['by_priority']['P0']['with_history'] == 2
    assert result['by_priority']['P0']['without_history'] == 1

    # P1: 2 total, 1 with history, 1 without
    assert result['by_priority']['P1']['total'] == 2
    assert result['by_priority']['P1']['with_history'] == 1
    assert result['by_priority']['P1']['without_history'] == 1

    # P2: 2 total, 0 with history, 2 without
    assert result['by_priority']['P2']['total'] == 2
    assert result['by_priority']['P2']['with_history'] == 0
    assert result['by_priority']['P2']['without_history'] == 2

    # P3: 0 total
    assert result['by_priority']['P3']['total'] == 0

    # UNKNOWN: 3 total, 2 with history, 1 without
    assert result['by_priority']['UNKNOWN']['total'] == 3
    assert result['by_priority']['UNKNOWN']['with_history'] == 2
    assert result['by_priority']['UNKNOWN']['without_history'] == 1


@pytest.mark.asyncio
async def test_search_statistics_non_standard_priorities(test_db):
    """Test that non-standard priority values are treated as UNKNOWN."""
    # Add testcases with non-standard priorities
    testcases = [
        TestcaseMetadata(testcase_name='test_p10', test_case_id='TC-001', priority='P10'),
        TestcaseMetadata(testcase_name='test_high', test_case_id='TC-002', priority='High'),
        TestcaseMetadata(testcase_name='test_low', test_case_id='TC-003', priority='Low'),
        TestcaseMetadata(testcase_name='test_p1_valid', test_case_id='TC-004', priority='P1'),
        TestcaseMetadata(testcase_name='test_none', test_case_id='TC-005', priority=None),
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = await get_testcase_statistics(db=test_db)

    # All non-standard priorities should be counted as UNKNOWN
    assert result['overall']['total_testcases'] == 5
    assert result['by_priority']['UNKNOWN']['total'] == 4  # P10, High, Low, None
    assert result['by_priority']['P1']['total'] == 1


def test_search_statistics_api_endpoint_with_data(client, test_db, sample_release):
    """Test statistics API endpoint with data via TestClient."""
    # Create module and job
    module = Module(release_id=sample_release.id, name='test_module')
    test_db.add(module)
    test_db.commit()

    job = Job(module_id=module.id, job_id='100', total=2, passed=2, pass_rate=100.0)
    test_db.add(job)
    test_db.commit()

    # Add testcases with execution history
    testcases = [
        TestcaseMetadata(testcase_name='test1', test_case_id='TC-001', priority='P0'),
        TestcaseMetadata(testcase_name='test2', test_case_id='TC-002', priority='P1'),
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    test_results = [
        TestResult(job_id=job.id, test_name='test1', status='PASSED', priority='P0'),
    ]
    for tr in test_results:
        test_db.add(tr)
    test_db.commit()

    response = client.get('/api/v1/search/statistics')

    assert response.status_code == 200
    data = response.json()

    # Verify structure
    assert 'overall' in data
    assert 'by_priority' in data

    # Verify counts
    assert data['overall']['total_testcases'] == 2
    assert data['overall']['with_history'] == 1
    assert data['overall']['without_history'] == 1

    # Verify priority breakdown
    assert data['by_priority']['P0']['total'] == 1
    assert data['by_priority']['P0']['with_history'] == 1
    assert data['by_priority']['P1']['total'] == 1
    assert data['by_priority']['P1']['with_history'] == 0


def test_search_statistics_api_endpoint_legacy_path(client):
    """Test that legacy /api/search/statistics endpoint also works."""
    response = client.get('/api/search/statistics')

    assert response.status_code == 200
    data = response.json()

    assert 'overall' in data
    assert 'by_priority' in data
