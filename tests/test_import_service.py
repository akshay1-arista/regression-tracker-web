"""
Tests for import service.
"""
import sys
from pathlib import Path
import pytest

# Add parent to path
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TESTS_DIR.parent
PARSER_DIR = PROJECT_DIR.parent / "regression_tracker"
sys.path.insert(0, str(PARSER_DIR))

from app.services.import_service import (
    convert_test_status,
    calculate_job_statistics,
    get_or_create_release,
    get_or_create_module,
    get_or_create_job
)
from app.models.db_models import Release, Module, Job, TestStatusEnum
from models import TestStatus as ParsedTestStatus, TestResult as ParsedTestResult


class TestConvertTestStatus:
    """Tests for convert_test_status function."""

    def test_convert_passed(self):
        """Test converting PASSED status."""
        result = convert_test_status(ParsedTestStatus.PASSED)
        assert result == TestStatusEnum.PASSED

    def test_convert_failed(self):
        """Test converting FAILED status."""
        result = convert_test_status(ParsedTestStatus.FAILED)
        assert result == TestStatusEnum.FAILED

    def test_convert_skipped(self):
        """Test converting SKIPPED status."""
        result = convert_test_status(ParsedTestStatus.SKIPPED)
        assert result == TestStatusEnum.SKIPPED

    def test_convert_error(self):
        """Test converting ERROR status."""
        result = convert_test_status(ParsedTestStatus.ERROR)
        assert result == TestStatusEnum.ERROR


class TestCalculateJobStatistics:
    """Tests for calculate_job_statistics function."""

    def test_calculate_all_passed(self):
        """Test statistics when all tests pass."""
        results = [
            ParsedTestResult(
                setup_ip="10.0.0.1",
                status=ParsedTestStatus.PASSED,
                file_path="test.py",
                class_name="TestClass",
                test_name=f"test_{i}",
                topology="5s"
            )
            for i in range(10)
        ]

        stats = calculate_job_statistics(results)

        assert stats['total'] == 10
        assert stats['passed'] == 10
        assert stats['failed'] == 0
        assert stats['skipped'] == 0
        assert stats['error'] == 0
        assert stats['pass_rate'] == 100.0

    def test_calculate_mixed_results(self):
        """Test statistics with mixed results."""
        results = [
            ParsedTestResult("10.0.0.1", ParsedTestStatus.PASSED, "test.py", "C", f"t{i}", "5s")
            for i in range(7)
        ] + [
            ParsedTestResult("10.0.0.1", ParsedTestStatus.FAILED, "test.py", "C", f"t{i}", "5s")
            for i in range(2)
        ] + [
            ParsedTestResult("10.0.0.1", ParsedTestStatus.SKIPPED, "test.py", "C", "t_skip", "5s")
        ]

        stats = calculate_job_statistics(results)

        assert stats['total'] == 10
        assert stats['passed'] == 7
        assert stats['failed'] == 2
        assert stats['skipped'] == 1
        assert stats['error'] == 0
        # Pass rate excludes skipped: 7/(10-1) = 77.78%
        assert stats['pass_rate'] == 77.78

    def test_calculate_with_skipped_only(self):
        """Test statistics when all tests are skipped."""
        results = [
            ParsedTestResult("10.0.0.1", ParsedTestStatus.SKIPPED, "test.py", "C", f"t{i}", "5s")
            for i in range(5)
        ]

        stats = calculate_job_statistics(results)

        assert stats['total'] == 5
        assert stats['skipped'] == 5
        assert stats['pass_rate'] == 100.0  # All skipped = 100%

    def test_calculate_empty_results(self):
        """Test statistics with no results."""
        stats = calculate_job_statistics([])

        assert stats['total'] == 0
        assert stats['passed'] == 0
        assert stats['pass_rate'] == 0.0


class TestGetOrCreateRelease:
    """Tests for get_or_create_release function."""

    def test_create_new_release(self, test_db):
        """Test creating a new release."""
        release = get_or_create_release(test_db, "7.0.0.0", "https://jenkins.example.com")

        assert release.id is not None
        assert release.name == "7.0.0.0"
        assert release.jenkins_job_url == "https://jenkins.example.com"
        assert release.is_active is True

    def test_get_existing_release(self, test_db, sample_release):
        """Test getting an existing release."""
        release = get_or_create_release(test_db, "7.0.0.0")

        assert release.id == sample_release.id
        assert release.name == "7.0.0.0"

        # Should not create duplicate
        count = test_db.query(Release).filter(Release.name == "7.0.0.0").count()
        assert count == 1


class TestGetOrCreateModule:
    """Tests for get_or_create_module function."""

    def test_create_new_module(self, test_db, sample_release):
        """Test creating a new module."""
        module = get_or_create_module(test_db, sample_release, "business_policy")

        assert module.id is not None
        assert module.name == "business_policy"
        assert module.release_id == sample_release.id

    def test_get_existing_module(self, test_db, sample_release, sample_module):
        """Test getting an existing module."""
        module = get_or_create_module(test_db, sample_release, "business_policy")

        assert module.id == sample_module.id
        assert module.name == "business_policy"

        # Should not create duplicate
        count = test_db.query(Module).filter(
            Module.release_id == sample_release.id,
            Module.name == "business_policy"
        ).count()
        assert count == 1


class TestGetOrCreateJob:
    """Tests for get_or_create_job function."""

    def test_create_new_job(self, test_db, sample_module):
        """Test creating a new job."""
        job = get_or_create_job(test_db, sample_module, "8", "https://jenkins.example.com/8")

        assert job.id is not None
        assert job.job_id == "8"
        assert job.module_id == sample_module.id
        assert job.jenkins_url == "https://jenkins.example.com/8"

    def test_get_existing_job(self, test_db, sample_module, sample_job):
        """Test getting an existing job."""
        job = get_or_create_job(test_db, sample_module, "8")

        assert job.id == sample_job.id
        assert job.job_id == "8"

        # Should not create duplicate
        count = test_db.query(Job).filter(
            Job.module_id == sample_module.id,
            Job.job_id == "8"
        ).count()
        assert count == 1


class TestImportIntegration:
    """Integration tests for the full import workflow."""

    def test_import_creates_hierarchy(self, test_db):
        """Test that import creates the full release/module/job hierarchy."""
        # Create release
        release = get_or_create_release(test_db, "7.0.0.0")

        # Create module
        module = get_or_create_module(test_db, release, "business_policy")

        # Create job
        job = get_or_create_job(test_db, module, "8")

        # Verify hierarchy
        assert job.module.release.name == "7.0.0.0"
        assert job.module.name == "business_policy"
        assert job.job_id == "8"

    def test_import_idempotent(self, test_db):
        """Test that running import multiple times is idempotent."""
        # First import
        release1 = get_or_create_release(test_db, "7.0.0.0")
        module1 = get_or_create_module(test_db, release1, "business_policy")
        job1 = get_or_create_job(test_db, module1, "8")

        # Second import with same data
        release2 = get_or_create_release(test_db, "7.0.0.0")
        module2 = get_or_create_module(test_db, release2, "business_policy")
        job2 = get_or_create_job(test_db, module2, "8")

        # Should return same objects
        assert release1.id == release2.id
        assert module1.id == module2.id
        assert job1.id == job2.id

        # Verify no duplicates
        assert test_db.query(Release).count() == 1
        assert test_db.query(Module).count() == 1
        assert test_db.query(Job).count() == 1
