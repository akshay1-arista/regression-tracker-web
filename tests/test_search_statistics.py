"""
Tests for the search statistics endpoint.
"""
import pytest
import asyncio
from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release
from datetime import datetime, timezone


def test_search_statistics_empty_db(test_db):
    """Test statistics endpoint with empty database."""
    from app.routers.search import get_testcase_statistics

    result = asyncio.run(get_testcase_statistics(db=test_db))

    assert result['automated']['total'] == 0
    assert result['automated']['with_history'] == 0
    assert result['automated']['without_history'] == 0

    # All priorities should be 0
    for priority in ['P0', 'P1', 'P2', 'P3', 'UNKNOWN']:
        assert result['by_priority'][priority]['total'] == 0
        assert result['by_priority'][priority]['with_history'] == 0
        assert result['by_priority'][priority]['without_history'] == 0


def test_search_statistics_with_metadata_only(test_db):
    """Test statistics when testcases exist but have no execution history."""
    # Add testcases with different priorities (all automated)
    testcases = [
        TestcaseMetadata(testcase_name='test1', test_case_id='TC-001', priority='P0', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='test2', test_case_id='TC-002', priority='P1', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='test3', test_case_id='TC-003', priority='P2', automation_status='Automated'),
        TestcaseMetadata(testcase_name='test4', test_case_id='TC-004', priority='P3', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='test5', test_case_id='TC-005', priority=None, automation_status='Hapy Automated'),  # UNKNOWN
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = asyncio.run(get_testcase_statistics(db=test_db))

    # Overall stats
    assert result["automated"]["total"] == 5
    assert result['automated']['with_history'] == 0
    assert result['automated']['without_history'] == 5

    # By priority
    assert result['by_priority']['P0']['total'] == 1
    assert result['by_priority']['P0']['without_history'] == 1
    assert result['by_priority']['P1']['total'] == 1
    assert result['by_priority']['P2']['total'] == 1
    assert result['by_priority']['P3']['total'] == 1
    assert result['by_priority']['UNKNOWN']['total'] == 1


def test_search_statistics_with_execution_history(test_db, sample_release):
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

    # Add testcases (all automated)
    testcases = [
        TestcaseMetadata(testcase_name='test_with_history_p0', test_case_id='TC-001', priority='P0', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='test_with_history_p1', test_case_id='TC-002', priority='P1', automation_status='Automated'),
        TestcaseMetadata(testcase_name='test_without_history', test_case_id='TC-003', priority='P2', automation_status='Hapy Automated'),
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
            priority='P0',
            file_path='test_file.py', class_name='TestClass'
        ),
        TestResult(
            job_id=job.id,
            test_name='test_with_history_p1',
            status='PASSED',
            priority='P1',
            file_path='test_file.py', class_name='TestClass'
        ),
    ]
    for tr in test_results:
        test_db.add(tr)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = asyncio.run(get_testcase_statistics(db=test_db))

    # Overall stats
    assert result["automated"]["total"] == 3
    assert result['automated']['with_history'] == 2
    assert result['automated']['without_history'] == 1

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


def test_search_statistics_mixed_priorities(test_db, sample_release):
    """Test statistics with mixed priorities and execution histories."""
    # Create release, module, and job
    module = Module(release_id=sample_release.id, name='test_module')
    test_db.add(module)
    test_db.commit()

    job = Job(module_id=module.id, job_id='100', total=5, passed=5, pass_rate=100.0)
    test_db.add(job)
    test_db.commit()

    # Add 10 testcases with various priorities (all automated)
    testcases = [
        # P0: 3 total, 2 with history
        TestcaseMetadata(testcase_name='p0_test1', test_case_id='TC-001', priority='P0', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='p0_test2', test_case_id='TC-002', priority='P0', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='p0_test3', test_case_id='TC-003', priority='P0', automation_status='Automated'),
        # P1: 2 total, 1 with history
        TestcaseMetadata(testcase_name='p1_test1', test_case_id='TC-004', priority='P1', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='p1_test2', test_case_id='TC-005', priority='P1', automation_status='Automated'),
        # P2: 2 total, 0 with history
        TestcaseMetadata(testcase_name='p2_test1', test_case_id='TC-006', priority='P2', automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='p2_test2', test_case_id='TC-007', priority='P2', automation_status='Automated'),
        # UNKNOWN: 3 total, 2 with history
        TestcaseMetadata(testcase_name='unknown_test1', test_case_id='TC-008', priority=None, automation_status='Hapy Automated'),
        TestcaseMetadata(testcase_name='unknown_test2', test_case_id='TC-009', priority=None, automation_status='Automated'),
        TestcaseMetadata(testcase_name='unknown_test3', test_case_id='TC-010', priority=None, automation_status='Hapy Automated'),
    ]
    for tc in testcases:
        test_db.add(tc)
    test_db.commit()

    # Add test results for some testcases
    test_results = [
        TestResult(job_id=job.id, test_name='p0_test1', status='PASSED', priority='P0', file_path='test.py', class_name='TestClass'),
        TestResult(job_id=job.id, test_name='p0_test2', status='PASSED', priority='P0', file_path='test.py', class_name='TestClass'),
        TestResult(job_id=job.id, test_name='p1_test1', status='PASSED', priority='P1', file_path='test.py', class_name='TestClass'),
        TestResult(job_id=job.id, test_name='unknown_test1', status='PASSED', priority=None, file_path='test.py', class_name='TestClass'),
        TestResult(job_id=job.id, test_name='unknown_test2', status='PASSED', priority=None, file_path='test.py', class_name='TestClass'),
    ]
    for tr in test_results:
        test_db.add(tr)
    test_db.commit()

    from app.routers.search import get_testcase_statistics
    result = asyncio.run(get_testcase_statistics(db=test_db))

    # Overall stats
    assert result["automated"]["total"] == 10
    assert result['automated']['with_history'] == 5
    assert result['automated']['without_history'] == 5

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
