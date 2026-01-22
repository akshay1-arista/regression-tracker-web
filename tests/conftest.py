"""
Pytest configuration and fixtures for testing.
"""
import sys
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TESTS_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.models.db_models import Base
from app.database import get_db_context


@pytest.fixture(scope="session", autouse=True)
def initialize_cache():
    """
    Initialize FastAPI cache for all tests.

    This fixture runs once per test session and initializes the FastAPI-Cache2
    backend with an in-memory cache. Without this, any endpoint using the
    @cache decorator will fail with 'You must call init first!' error.
    """
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.inmemory import InMemoryBackend

    FastAPICache.init(InMemoryBackend())
    yield
    # Cleanup: Reset cache after all tests
    FastAPICache.reset()


@pytest.fixture(scope="function")
def test_db():
    """
    Create a temporary in-memory database for testing.
    Each test gets a fresh database.
    """
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session factory
    TestSessionLocal = sessionmaker(bind=engine)

    # Create session
    session = TestSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def sample_release(test_db):
    """Create a sample release for testing."""
    from app.models.db_models import Release

    release = Release(
        name="7.0.0.0",
        is_active=True,
        jenkins_job_url="https://jenkins.example.com/job/7.0.0.0"
    )
    test_db.add(release)
    test_db.commit()
    test_db.refresh(release)

    return release


@pytest.fixture(scope="function")
def sample_module(test_db, sample_release):
    """Create a sample module for testing."""
    from app.models.db_models import Module

    module = Module(
        release_id=sample_release.id,
        name="business_policy"
    )
    test_db.add(module)
    test_db.commit()
    test_db.refresh(module)

    return module


@pytest.fixture(scope="function")
def sample_job(test_db, sample_module):
    """Create a sample job for testing."""
    from app.models.db_models import Job

    job = Job(
        module_id=sample_module.id,
        job_id="8",
        total=10,
        passed=7,
        failed=2,
        skipped=1,
        pass_rate=70.0,  # 7 passed / 10 total = 70.0%
        jenkins_url="https://jenkins.example.com/job/7.0.0.0/8"
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)

    return job


@pytest.fixture(scope="function")
def sample_test_results(test_db, sample_job):
    """Create sample test results for testing."""
    from app.models.db_models import TestResult, TestStatusEnum

    results = [
        TestResult(
            job_id=sample_job.id,
            file_path="tests/test_policy.py",
            class_name="TestBusinessPolicy",
            test_name="test_create_policy",
            status=TestStatusEnum.PASSED,
            setup_ip="10.0.0.1",
            topology="5s",
            order_index=0
        ),
        TestResult(
            job_id=sample_job.id,
            file_path="tests/test_policy.py",
            class_name="TestBusinessPolicy",
            test_name="test_delete_policy",
            status=TestStatusEnum.FAILED,
            setup_ip="10.0.0.1",
            topology="5s",
            order_index=1,
            failure_message="AssertionError: Policy not deleted"
        ),
        TestResult(
            job_id=sample_job.id,
            file_path="tests/test_policy.py",
            class_name="TestBusinessPolicy",
            test_name="test_update_policy",
            status=TestStatusEnum.PASSED,
            setup_ip="10.0.0.2",
            topology="others",
            order_index=2,
            was_rerun=True,
            rerun_still_failed=False
        )
    ]

    for result in results:
        test_db.add(result)

    test_db.commit()

    for result in results:
        test_db.refresh(result)

    return results


@pytest.fixture(scope="function")
def override_get_db(test_db):
    """
    Override FastAPI's database dependency to use the test database.

    This fixture allows integration tests using TestClient to share the same
    database session as the test fixtures (sample_release, sample_module, etc.).

    Usage in test files:
        def test_endpoint(client, sample_module, override_get_db):
            # client will now use the same DB as sample_module
            response = client.get("/api/v1/endpoint")
    """
    from app.main import app
    from app.database import get_db_context

    def get_test_db():
        try:
            yield test_db
        finally:
            pass  # Don't close test_db here, conftest handles it

    app.dependency_overrides[get_db_context] = get_test_db
    yield
    # Cleanup: Remove override after test
    app.dependency_overrides.clear()
