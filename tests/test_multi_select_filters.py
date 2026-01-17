"""
Unit tests for multi-select filter functionality.

Tests cover:
- Multi-select status filtering in job details
- Multi-select priority filtering in job details
- Multi-select priority filtering in trends
- CSV parsing of filter parameters
- Combined filters
- Edge cases
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.models.db_models import Base, Release, Module, Job, TestResult, TestStatusEnum
from app.services import data_service
from app.main import app

# Test client
client = TestClient(app)


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def setup_multi_filter_test_data(in_memory_db):
    """Set up test data for multi-select filter tests."""
    # Create release
    release = Release(name='7.0', is_active=True)
    in_memory_db.add(release)
    in_memory_db.commit()

    # Create module
    module = Module(release_id=release.id, name='business_policy')
    in_memory_db.add(module)
    in_memory_db.commit()

    # Create job
    job = Job(module_id=module.id, job_id='11', version='7.0.0.0-123')
    in_memory_db.add(job)
    in_memory_db.commit()

    # Create test results with various status and priority combinations
    test_results = [
        # P0 tests
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p0_passed',
            status=TestStatusEnum.PASSED,
            priority='P0'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p0_failed',
            status=TestStatusEnum.FAILED,
            priority='P0'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p0_skipped',
            status=TestStatusEnum.SKIPPED,
            priority='P0'
        ),
        # P1 tests
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p1_passed',
            status=TestStatusEnum.PASSED,
            priority='P1'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p1_failed',
            status=TestStatusEnum.FAILED,
            priority='P1'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p1_error',
            status=TestStatusEnum.ERROR,
            priority='P1'
        ),
        # P2 tests
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p2_passed',
            status=TestStatusEnum.PASSED,
            priority='P2'
        ),
        # P3 tests
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p3_skipped',
            status=TestStatusEnum.SKIPPED,
            priority='P3'
        ),
        # UNKNOWN priority
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_unknown_passed',
            status=TestStatusEnum.PASSED,
            priority=None
        ),
    ]

    for tr in test_results:
        in_memory_db.add(tr)
    in_memory_db.commit()

    return {
        'release': release,
        'module': module,
        'job': job,
        'test_results': test_results
    }


# Multi-Select Status Filter Tests

def test_multi_select_status_single(setup_multi_filter_test_data):
    """Test filtering by single status."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests?statuses=PASSED"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert all(t['status'] == 'PASSED' for t in tests)
    assert len(tests) == 4  # 4 PASSED tests


def test_multi_select_status_multiple(setup_multi_filter_test_data):
    """Test filtering by multiple statuses (comma-separated)."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests?statuses=PASSED,FAILED"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert all(t['status'] in ['PASSED', 'FAILED'] for t in tests)
    assert len(tests) == 6  # 4 PASSED + 2 FAILED


def test_multi_select_status_all_types(setup_multi_filter_test_data):
    """Test filtering by all status types."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED,FAILED,SKIPPED,ERROR"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should return all tests
    assert len(tests) == 9


def test_multi_select_status_invalid(setup_multi_filter_test_data):
    """Test that invalid status values are rejected."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED,INVALID"
    )

    assert response.status_code == 400
    error_detail = response.json()['detail']
    assert 'Invalid status value' in error_detail


# Multi-Select Priority Filter Tests

def test_multi_select_priority_single(setup_multi_filter_test_data):
    """Test filtering by single priority."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests?priorities=P0"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert all(t['priority'] == 'P0' for t in tests)
    assert len(tests) == 3  # 3 P0 tests


def test_multi_select_priority_multiple(setup_multi_filter_test_data):
    """Test filtering by multiple priorities (comma-separated)."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=P0,P1"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert all(t['priority'] in ['P0', 'P1'] for t in tests)
    assert len(tests) == 6  # 3 P0 + 3 P1


def test_multi_select_priority_with_unknown(setup_multi_filter_test_data):
    """Test filtering by UNKNOWN priority."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=UNKNOWN"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert all(t['priority'] is None or t['priority'] == 'UNKNOWN' for t in tests)
    assert len(tests) == 1


def test_multi_select_priority_mixed_with_unknown(setup_multi_filter_test_data):
    """Test filtering by mix of priorities including UNKNOWN."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=P0,UNKNOWN"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert len(tests) == 4  # 3 P0 + 1 UNKNOWN


def test_multi_select_priority_case_insensitive(setup_multi_filter_test_data):
    """Test that priority filter is case-insensitive."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=p0,p1"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    assert len(tests) == 6  # Should work with lowercase


def test_multi_select_priority_invalid(setup_multi_filter_test_data):
    """Test that invalid priority values are rejected."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=P0,INVALID"
    )

    assert response.status_code == 400
    error_detail = response.json()['detail']
    assert 'Invalid priorities' in error_detail


# Combined Filters Tests

def test_combined_status_and_priority_filters(setup_multi_filter_test_data):
    """Test combining status and priority filters."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED&priorities=P0,P1"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should only return PASSED tests with P0 or P1 priority
    assert all(t['status'] == 'PASSED' for t in tests)
    assert all(t['priority'] in ['P0', 'P1'] for t in tests)
    assert len(tests) == 2  # test_p0_passed, test_p1_passed


def test_combined_multiple_statuses_and_priorities(setup_multi_filter_test_data):
    """Test combining multiple statuses with multiple priorities."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED,FAILED&priorities=P0,P1,P2"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should return PASSED or FAILED tests with P0, P1, or P2 priority
    assert all(t['status'] in ['PASSED', 'FAILED'] for t in tests)
    assert all(t['priority'] in ['P0', 'P1', 'P2'] for t in tests)
    assert len(tests) == 5  # p0_passed, p0_failed, p1_passed, p1_failed, p2_passed


def test_combined_with_search_filter(setup_multi_filter_test_data):
    """Test combining status/priority filters with search."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED&priorities=P0&search=test_p0_passed"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should return only test_p0_passed
    assert len(tests) == 1
    assert tests[0]['test_name'] == 'test_p0_passed'


# CSV Parsing Tests

def test_csv_parsing_with_spaces(setup_multi_filter_test_data):
    """Test that spaces in CSV are handled correctly."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=P0, P1, P2"  # With spaces
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should work despite spaces
    assert len(tests) == 7  # 3 P0 + 3 P1 + 1 P2


def test_csv_parsing_empty_values(setup_multi_filter_test_data):
    """Test that empty CSV values are ignored."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?priorities=P0,,P1,"  # Empty values
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should ignore empty values and work correctly
    assert len(tests) == 6  # 3 P0 + 3 P1


# Trends Endpoint Multi-Select Tests

def test_trends_multi_select_priority(setup_multi_filter_test_data):
    """Test multi-select priority filter in trends endpoint."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/trends/{data['release'].name}/{data['module'].name}?priorities=P0,P1"
    )

    assert response.status_code == 200
    result = response.json()
    trends = result['items']

    # Should only return trends for P0 and P1 tests
    assert all(t['priority'] in ['P0', 'P1'] for t in trends)


def test_trends_priority_case_insensitive(setup_multi_filter_test_data):
    """Test that trends priority filter is case-insensitive."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/trends/{data['release'].name}/{data['module'].name}?priorities=p0,p1,p2"
    )

    assert response.status_code == 200
    # Should work with lowercase


def test_trends_priority_with_unknown(setup_multi_filter_test_data):
    """Test trends filter with UNKNOWN priority."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/trends/{data['release'].name}/{data['module'].name}?priorities=UNKNOWN"
    )

    assert response.status_code == 200
    result = response.json()
    trends = result['items']

    # Should return trends for tests with UNKNOWN priority
    assert all(t['priority'] is None or t['priority'] == 'UNKNOWN' for t in trends)


# Edge Cases

def test_empty_filter_parameters(setup_multi_filter_test_data):
    """Test that empty filter parameters are handled correctly."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=&priorities="
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should return all tests (no filters applied)
    assert len(tests) == 9


def test_no_filter_parameters(setup_multi_filter_test_data):
    """Test behavior when no filter parameters provided."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
    )

    assert response.status_code == 200
    result = response.json()
    tests = result['items']

    # Should return all tests
    assert len(tests) == 9


def test_pagination_with_filters(setup_multi_filter_test_data):
    """Test that pagination works with filters."""
    data = setup_multi_filter_test_data
    response = client.get(
        f"/api/v1/jobs/{data['release'].name}/{data['module'].name}/{data['job'].job_id}/tests"
        f"?statuses=PASSED&limit=2&skip=0"
    )

    assert response.status_code == 200
    result = response.json()

    assert 'metadata' in result
    assert result['metadata']['limit'] == 2
    assert result['metadata']['skip'] == 0
    assert len(result['items']) <= 2
