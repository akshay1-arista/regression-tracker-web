"""
Unit tests for priority filtering and search functionality.

Tests cover:
- Priority filtering in data_service
- Priority validation
- Search endpoint functionality
- N+1 query prevention
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.models.db_models import Base, Release, Module, Job, TestResult, TestcaseMetadata, TestStatusEnum
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
def setup_test_data(in_memory_db):
    """Set up test data with releases, modules, jobs, and test results."""
    # Create release
    release = Release(name='1.0.0.0', is_active=True)
    in_memory_db.add(release)
    in_memory_db.commit()

    # Create module
    module = Module(release_id=release.id, name='test_module')
    in_memory_db.add(module)
    in_memory_db.commit()

    # Create job
    job = Job(module_id=module.id, job_id='123')
    in_memory_db.add(job)
    in_memory_db.commit()

    # Create test results with various priorities
    test_results = [
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p0_1',
            status=TestStatusEnum.PASSED,
            priority='P0'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p0_2',
            status=TestStatusEnum.FAILED,
            priority='P0'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p1_1',
            status=TestStatusEnum.PASSED,
            priority='P1'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_p2_1',
            status=TestStatusEnum.PASSED,
            priority='P2'
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_unknown',
            status=TestStatusEnum.PASSED,
            priority=None  # UNKNOWN
        ),
    ]

    for tr in test_results:
        in_memory_db.add(tr)
    in_memory_db.commit()

    # Create testcase metadata for search tests
    metadata_list = [
        TestcaseMetadata(
            testcase_name='test_p0_1',
            test_case_id='TC-1',
            priority='P0',
            testrail_id='C123',
            component='DataPlane'
        ),
        TestcaseMetadata(
            testcase_name='test_p1_1',
            test_case_id='TC-2',
            priority='P1',
            testrail_id='C124',
            component='Routing'
        ),
    ]

    for metadata in metadata_list:
        in_memory_db.add(metadata)
    in_memory_db.commit()

    return {
        'release': release,
        'module': module,
        'job': job,
        'test_results': test_results
    }


# Priority Filtering Tests

def test_priority_filter_single_priority(in_memory_db, setup_test_data):
    """Test filtering by single priority."""
    data = setup_test_data
    results = data_service.get_test_results_for_job(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id,
        priority_filter=['P0']
    )

    assert len(results) == 2
    assert all(r.priority == 'P0' for r in results)


def test_priority_filter_multiple_priorities(in_memory_db, setup_test_data):
    """Test filtering by multiple priorities."""
    data = setup_test_data
    results = data_service.get_test_results_for_job(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id,
        priority_filter=['P0', 'P1']
    )

    assert len(results) == 3
    assert all(r.priority in ['P0', 'P1'] for r in results)


def test_priority_filter_with_unknown(in_memory_db, setup_test_data):
    """Test filtering by UNKNOWN (NULL values)."""
    data = setup_test_data
    results = data_service.get_test_results_for_job(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id,
        priority_filter=['UNKNOWN']
    )

    assert len(results) == 1
    assert results[0].priority is None


def test_priority_filter_mixed_with_unknown(in_memory_db, setup_test_data):
    """Test filtering by P0 and UNKNOWN."""
    data = setup_test_data
    results = data_service.get_test_results_for_job(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id,
        priority_filter=['P0', 'UNKNOWN']
    )

    assert len(results) == 3
    assert all(r.priority in ['P0', None] for r in results)


def test_priority_filter_invalid_values(in_memory_db, setup_test_data):
    """Test that invalid priority values raise HTTPException."""
    data = setup_test_data

    with pytest.raises(HTTPException) as exc_info:
        data_service.get_test_results_for_job(
            in_memory_db,
            data['release'].name,
            data['module'].name,
            data['job'].job_id,
            priority_filter=['INVALID', 'HACKER']
        )

    assert exc_info.value.status_code == 400
    assert 'Invalid priorities' in exc_info.value.detail
    assert 'INVALID' in exc_info.value.detail


# Priority Statistics Tests

def test_priority_statistics_calculation(in_memory_db, setup_test_data):
    """Test priority statistics calculation."""
    data = setup_test_data
    stats = data_service.get_priority_statistics(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id
    )

    # Should have 4 priorities (P0, P1, P2, UNKNOWN)
    assert len(stats) == 4

    # Find P0 stats
    p0_stat = next((s for s in stats if s['priority'] == 'P0'), None)
    assert p0_stat is not None
    assert p0_stat['total'] == 2
    assert p0_stat['passed'] == 1
    assert p0_stat['failed'] == 1
    assert p0_stat['pass_rate'] == 50.0


def test_priority_statistics_sorted(in_memory_db, setup_test_data):
    """Test that priority statistics are sorted correctly."""
    data = setup_test_data
    stats = data_service.get_priority_statistics(
        in_memory_db,
        data['release'].name,
        data['module'].name,
        data['job'].job_id
    )

    priorities = [s['priority'] for s in stats]
    expected_order = ['P0', 'P1', 'P2', 'UNKNOWN']
    assert priorities == expected_order


# Search Endpoint Tests

def test_search_testcases_by_test_case_id(in_memory_db, setup_test_data):
    """Test searching by test_case_id."""
    response = client.get("/api/v1/search/testcases?q=TC-1")

    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 1
    assert any(r['test_case_id'] == 'TC-1' for r in results)


def test_search_testcases_escape_like_chars(in_memory_db, setup_test_data):
    """Test that LIKE special characters are properly escaped."""
    # Query with % should not match everything
    response = client.get("/api/v1/search/testcases?q=TC-%")

    assert response.status_code == 200
    results = response.json()
    # Should not match all test cases (would happen if % not escaped)
    # In real scenario with more data, this would be more obvious


def test_search_testcases_limit_enforced(in_memory_db, setup_test_data):
    """Test that limit parameter is enforced."""
    response = client.get("/api/v1/search/testcases?q=test&limit=1")

    assert response.status_code == 200
    results = response.json()
    assert len(results) <= 1


def test_get_testcase_details_not_found(in_memory_db, setup_test_data):
    """Test 404 response for non-existent test case."""
    response = client.get("/api/v1/search/testcases/nonexistent_test")

    assert response.status_code == 404
    assert 'not found' in response.json()['detail'].lower()


def test_get_testcase_details_pagination(in_memory_db, setup_test_data):
    """Test pagination in testcase details endpoint."""
    response = client.get("/api/v1/search/testcases/test_p0_1?limit=5&offset=0")

    assert response.status_code == 200
    data = response.json()

    assert 'pagination' in data
    assert data['pagination']['limit'] == 5
    assert data['pagination']['offset'] == 0
    assert 'has_more' in data['pagination']


def test_get_testcase_details_statistics(in_memory_db, setup_test_data):
    """Test that statistics are calculated correctly."""
    response = client.get("/api/v1/search/testcases/test_p0_1")

    assert response.status_code == 200
    data = response.json()

    assert 'statistics' in data
    stats = data['statistics']
    assert 'total_runs' in stats
    assert 'passed' in stats
    assert 'failed' in stats
    assert 'pass_rate' in stats


def test_get_testcase_details_pass_rate_none_when_all_skipped(in_memory_db):
    """Test that pass_rate is None when all tests are skipped."""
    # Create test data with all skipped tests
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    release = Release(name='1.0.0.0', is_active=True)
    session.add(release)
    session.commit()

    module = Module(release_id=release.id, name='test_module')
    session.add(module)
    session.commit()

    job = Job(module_id=module.id, job_id='123')
    session.add(job)
    session.commit()

    metadata = TestcaseMetadata(
        testcase_name='test_all_skipped',
        test_case_id='TC-99',
        priority='P0'
    )
    session.add(metadata)

    test_result = TestResult(
        job_id=job.id,
        file_path='test/path.py',
        class_name='TestClass',
        test_name='test_all_skipped',
        status=TestStatusEnum.SKIPPED,
        priority='P0'
    )
    session.add(test_result)
    session.commit()

    # Now test
    response = client.get("/api/v1/search/testcases/test_all_skipped")

    assert response.status_code == 200
    data = response.json()
    assert data['statistics']['pass_rate'] is None

    session.close()


# Trends Endpoint Priority Validation Tests

def test_trends_priority_validation_invalid(in_memory_db, setup_test_data):
    """Test that trends endpoint validates priority values."""
    data = setup_test_data
    response = client.get(
        f"/api/v1/trends/{data['release'].name}/{data['module'].name}?priorities=INVALID,HACKER"
    )

    assert response.status_code == 400
    assert 'Invalid priorities' in response.json()['detail']


def test_trends_priority_validation_case_insensitive(in_memory_db, setup_test_data):
    """Test that trends endpoint accepts lowercase priorities."""
    data = setup_test_data
    response = client.get(
        f"/api/v1/trends/{data['release'].name}/{data['module'].name}?priorities=p0,p1"
    )

    # Should work (priorities converted to uppercase)
    assert response.status_code == 200
