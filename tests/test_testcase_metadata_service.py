"""
Unit tests for testcase metadata service.

Tests cover:
- CSV validation (missing columns, invalid structure)
- Priority validation (valid/invalid values)
- Import process (UPSERT, batching, backfill)
- Error handling
"""
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db_models import Base, TestcaseMetadata, TestResult, AppSettings, Job, Module, Release
from app.services import testcase_metadata_service


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
def sample_csv_valid():
    """Create a temporary valid CSV file for testing."""
    csv_content = """testcase_name,test_case_id,priority,testrail_id,component,automation_status
test_example_1,TC-1,P0,C123,DataPlane,Hapy Automated
test_example_2,TC-2,P1,C124,Routing,Hapy Automated
test_example_3,TC-3,P2,C125,BusinessPolicy,Hapy Automated
test_example_4,TC-4,P3,C126,DataPlane,Hapy Automated
,TC-5,P1,C127,Routing,Manual
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink()


@pytest.fixture
def sample_csv_missing_column():
    """Create a CSV with missing required column."""
    csv_content = """testcase_name,test_case_id,testrail_id,component,automation_status
test_example_1,TC-1,C123,DataPlane,Hapy Automated
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink()


@pytest.fixture
def sample_csv_invalid_priority():
    """Create a CSV with invalid priority values."""
    csv_content = """testcase_name,test_case_id,priority,testrail_id,component,automation_status
test_example_1,TC-1,High,C123,DataPlane,Hapy Automated
test_example_2,TC-2,Medium,C124,Routing,Hapy Automated
test_example_3,TC-3,P1,C125,BusinessPolicy,Hapy Automated
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink()


@pytest.fixture
def setup_test_results(in_memory_db):
    """Set up test results in the database."""
    # Create release, module, and job
    release = Release(name='1.0.0.0', is_active=True)
    in_memory_db.add(release)
    in_memory_db.commit()

    module = Module(release_id=release.id, name='test_module')
    in_memory_db.add(module)
    in_memory_db.commit()

    job = Job(module_id=module.id, job_id='123')
    in_memory_db.add(job)
    in_memory_db.commit()

    # Create test results
    test_results = [
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_example_1',
            status='PASSED',
            priority=None  # Will be backfilled
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_example_2',
            status='FAILED',
            priority=None
        ),
        TestResult(
            job_id=job.id,
            file_path='test/path.py',
            class_name='TestClass',
            test_name='test_unknown',  # Not in CSV
            status='PASSED',
            priority=None
        ),
    ]

    for tr in test_results:
        in_memory_db.add(tr)
    in_memory_db.commit()

    return test_results


# CSV Validation Tests

def test_validate_csv_structure_valid():
    """Test CSV validation with all required columns."""
    df = pd.DataFrame({
        'testcase_name': ['test1'],
        'test_case_id': ['TC-1'],
        'priority': ['P0'],
        'testrail_id': ['C123'],
        'component': ['DataPlane'],
        'automation_status': ['Automated']
    })

    # Should not raise exception
    testcase_metadata_service._validate_csv_structure(df)


def test_validate_csv_structure_missing_column():
    """Test CSV validation with missing required column."""
    df = pd.DataFrame({
        'testcase_name': ['test1'],
        'test_case_id': ['TC-1'],
        # Missing: priority, testrail_id, component, automation_status
    })

    with pytest.raises(ValueError) as exc_info:
        testcase_metadata_service._validate_csv_structure(df)

    assert 'CSV missing required columns' in str(exc_info.value)
    assert 'priority' in str(exc_info.value)


# Priority Validation Tests

def test_validate_priority_valid():
    """Test priority validation with valid values."""
    assert testcase_metadata_service._validate_and_normalize_priority('P0', 'test1') == 'P0'
    assert testcase_metadata_service._validate_and_normalize_priority('P1', 'test1') == 'P1'
    assert testcase_metadata_service._validate_and_normalize_priority('P2', 'test1') == 'P2'
    assert testcase_metadata_service._validate_and_normalize_priority('P3', 'test1') == 'P3'


def test_validate_priority_invalid():
    """Test priority validation with invalid values."""
    assert testcase_metadata_service._validate_and_normalize_priority('High', 'test1') is None
    assert testcase_metadata_service._validate_and_normalize_priority('Medium', 'test1') is None
    assert testcase_metadata_service._validate_and_normalize_priority('P4', 'test1') is None


def test_validate_priority_missing():
    """Test priority validation with missing values."""
    assert testcase_metadata_service._validate_and_normalize_priority(None, 'test1') is None
    assert testcase_metadata_service._validate_and_normalize_priority('', 'test1') is None
    assert testcase_metadata_service._validate_and_normalize_priority(pd.NA, 'test1') is None


# Import Tests

def test_import_file_not_found(in_memory_db):
    """Test import with non-existent CSV file."""
    non_existent_path = Path('/tmp/does_not_exist_12345.csv')

    with pytest.raises(FileNotFoundError) as exc_info:
        testcase_metadata_service.import_testcase_metadata(
            db=in_memory_db,
            csv_path=non_existent_path
        )

    assert 'CSV file not found' in str(exc_info.value)


def test_import_missing_columns(in_memory_db, sample_csv_missing_column):
    """Test import with CSV missing required columns."""
    with pytest.raises(ValueError) as exc_info:
        testcase_metadata_service.import_testcase_metadata(
            db=in_memory_db,
            csv_path=sample_csv_missing_column
        )

    assert 'CSV missing required columns' in str(exc_info.value)


def test_import_success_basic(in_memory_db, sample_csv_valid):
    """Test successful import with valid CSV."""
    result = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    # Check return statistics
    assert result['success'] is True
    assert result['metadata_rows_imported'] == 4  # Excludes empty testcase_name
    assert result['csv_total_rows'] == 5
    assert result['csv_filtered_rows'] == 4

    # Check database records
    metadata_count = in_memory_db.query(TestcaseMetadata).count()
    assert metadata_count == 4

    # Check specific record
    test1 = in_memory_db.query(TestcaseMetadata).filter(
        TestcaseMetadata.testcase_name == 'test_example_1'
    ).first()
    assert test1 is not None
    assert test1.test_case_id == 'TC-1'
    assert test1.priority == 'P0'
    assert test1.component == 'DataPlane'

    # Check import status was recorded
    setting = in_memory_db.query(AppSettings).filter(
        AppSettings.key == 'testcase_metadata_last_import'
    ).first()
    assert setting is not None
    assert setting.value is not None


def test_import_handles_invalid_priorities(in_memory_db, sample_csv_invalid_priority):
    """Test import handles invalid priority values gracefully."""
    result = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_invalid_priority
    )

    assert result['success'] is True
    assert result['invalid_priority_count'] == 2  # 'High' and 'Medium'

    # Check that invalid priorities were set to NULL
    high_priority = in_memory_db.query(TestcaseMetadata).filter(
        TestcaseMetadata.testcase_name == 'test_example_1'
    ).first()
    assert high_priority.priority is None

    # Check that valid priority was preserved
    p1_priority = in_memory_db.query(TestcaseMetadata).filter(
        TestcaseMetadata.testcase_name == 'test_example_3'
    ).first()
    assert p1_priority.priority == 'P1'


def test_import_upsert_updates_existing(in_memory_db, sample_csv_valid):
    """Test that import updates existing records (UPSERT)."""
    # First import
    result1 = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )
    assert result1['metadata_rows_imported'] == 4

    # Modify CSV and re-import
    csv_content_updated = """testcase_name,test_case_id,priority,testrail_id,component,automation_status
test_example_1,TC-1-UPDATED,P2,C123,DataPlane-Updated,Hapy Automated
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content_updated)
        updated_csv = Path(f.name)

    try:
        result2 = testcase_metadata_service.import_testcase_metadata(
            db=in_memory_db,
            csv_path=updated_csv
        )

        # Should still have only 1 record (upserted, not inserted)
        metadata_count = in_memory_db.query(TestcaseMetadata).count()
        assert metadata_count == 1

        # Check that record was updated
        test1 = in_memory_db.query(TestcaseMetadata).filter(
            TestcaseMetadata.testcase_name == 'test_example_1'
        ).first()
        assert test1.test_case_id == 'TC-1-UPDATED'
        assert test1.priority == 'P2'
        assert test1.component == 'DataPlane-Updated'

    finally:
        updated_csv.unlink()


def test_import_backfills_test_results(in_memory_db, sample_csv_valid, setup_test_results):
    """Test that import backfills priority into test results."""
    test_results = setup_test_results

    # Initially, all test results have NULL priority
    for tr in test_results:
        assert tr.priority is None

    # Run import
    result = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    # Refresh test results from DB
    in_memory_db.expire_all()

    # Check backfilled priorities
    tr1 = in_memory_db.query(TestResult).filter(
        TestResult.test_name == 'test_example_1'
    ).first()
    assert tr1.priority == 'P0'

    tr2 = in_memory_db.query(TestResult).filter(
        TestResult.test_name == 'test_example_2'
    ).first()
    assert tr2.priority == 'P1'

    # Unknown test should remain NULL
    tr_unknown = in_memory_db.query(TestResult).filter(
        TestResult.test_name == 'test_unknown'
    ).first()
    assert tr_unknown.priority is None

    # Check statistics
    assert result['test_results_updated'] == 2


# Import Status Tests

def test_get_import_status_never_imported(in_memory_db):
    """Test get_import_status when never imported."""
    status = testcase_metadata_service.get_import_status(in_memory_db)
    assert status is None


def test_get_import_status_after_import(in_memory_db, sample_csv_valid):
    """Test get_import_status after successful import."""
    # Run import
    testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    # Check status
    status = testcase_metadata_service.get_import_status(in_memory_db)
    assert status is not None
    assert status['last_import'] is not None
    assert status['total_metadata_records'] == 4
    assert status['test_results_with_priority'] == 0  # No test results in DB


# Search and Query Tests

def test_get_testcase_metadata_by_name(in_memory_db, sample_csv_valid):
    """Test getting metadata by testcase name."""
    testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    metadata = testcase_metadata_service.get_testcase_metadata_by_name(
        db=in_memory_db,
        testcase_name='test_example_1'
    )

    assert metadata is not None
    assert metadata.test_case_id == 'TC-1'
    assert metadata.priority == 'P0'


def test_get_testcase_metadata_by_name_not_found(in_memory_db):
    """Test getting metadata for non-existent test."""
    metadata = testcase_metadata_service.get_testcase_metadata_by_name(
        db=in_memory_db,
        testcase_name='does_not_exist'
    )
    assert metadata is None


def test_search_testcase_metadata(in_memory_db, sample_csv_valid):
    """Test searching metadata."""
    testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    # Search by test_case_id
    results = testcase_metadata_service.search_testcase_metadata(
        db=in_memory_db,
        query='TC-1'
    )
    assert len(results) == 1
    assert results[0].testcase_name == 'test_example_1'

    # Search by testcase_name
    results = testcase_metadata_service.search_testcase_metadata(
        db=in_memory_db,
        query='example_2'
    )
    assert len(results) == 1
    assert results[0].test_case_id == 'TC-2'


def test_get_priority_statistics(in_memory_db, sample_csv_valid):
    """Test getting priority distribution statistics."""
    testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid
    )

    stats = testcase_metadata_service.get_priority_statistics(in_memory_db)

    assert stats['P0'] == 1
    assert stats['P1'] == 1
    assert stats['P2'] == 1
    assert stats['P3'] == 1


# Configuration Tests

def test_csv_path_from_environment(in_memory_db, sample_csv_valid, monkeypatch):
    """Test that CSV path can be configured via environment variable."""
    monkeypatch.setenv('TESTCASE_CSV_PATH', str(sample_csv_valid))

    result = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db
    )

    assert result['success'] is True
    assert result['metadata_rows_imported'] == 4


# Job ID Logging Tests

def test_import_with_job_id_logging(in_memory_db, sample_csv_valid, caplog):
    """Test that job_id is included in log messages."""
    job_id = 'test-job-123'

    result = testcase_metadata_service.import_testcase_metadata(
        db=in_memory_db,
        csv_path=sample_csv_valid,
        job_id=job_id
    )

    assert result['success'] is True

    # Check that job_id appears in logs
    log_messages = [record.message for record in caplog.records]
    job_logged = any(f'[Job {job_id}]' in msg for msg in log_messages)
    assert job_logged, "Job ID should appear in log messages"
