"""
Tests for database models.
"""
import pytest
from datetime import datetime
from app.models.db_models import (
    Release, Module, Job, TestResult, AppSettings,
    JenkinsPollingLog, TestStatusEnum
)


class TestRelease:
    """Tests for Release model."""

    def test_create_release(self, test_db):
        """Test creating a release."""
        release = Release(
            name="7.0.0.0",
            is_active=True,
            jenkins_job_url="https://jenkins.example.com/job/7.0.0.0"
        )
        test_db.add(release)
        test_db.commit()

        # Verify
        assert release.id is not None
        assert release.name == "7.0.0.0"
        assert release.is_active is True
        assert release.created_at is not None

    def test_release_unique_name(self, test_db, sample_release):
        """Test that release names must be unique."""
        duplicate = Release(name="7.0.0.0")
        test_db.add(duplicate)

        with pytest.raises(Exception):  # IntegrityError
            test_db.commit()

    def test_release_modules_relationship(self, test_db, sample_release, sample_module):
        """Test relationship between release and modules."""
        assert len(sample_release.modules) == 1
        assert sample_release.modules[0].name == "business_policy"

    def test_release_cascade_delete(self, test_db, sample_release, sample_module):
        """Test that deleting a release cascades to modules."""
        release_id = sample_release.id

        test_db.delete(sample_release)
        test_db.commit()

        # Verify module was also deleted
        module = test_db.query(Module).filter(Module.release_id == release_id).first()
        assert module is None


class TestModule:
    """Tests for Module model."""

    def test_create_module(self, test_db, sample_release):
        """Test creating a module."""
        module = Module(
            release_id=sample_release.id,
            name="business_policy"
        )
        test_db.add(module)
        test_db.commit()

        assert module.id is not None
        assert module.name == "business_policy"
        assert module.release_id == sample_release.id

    def test_module_unique_constraint(self, test_db, sample_release, sample_module):
        """Test unique constraint on (release_id, name)."""
        duplicate = Module(
            release_id=sample_release.id,
            name="business_policy"
        )
        test_db.add(duplicate)

        with pytest.raises(Exception):  # IntegrityError
            test_db.commit()

    def test_module_jobs_relationship(self, test_db, sample_module, sample_job):
        """Test relationship between module and jobs."""
        assert len(sample_module.jobs) == 1
        assert sample_module.jobs[0].job_id == "8"


class TestJob:
    """Tests for Job model."""

    def test_create_job(self, test_db, sample_module):
        """Test creating a job."""
        job = Job(
            module_id=sample_module.id,
            job_id="8",
            total=100,
            passed=80,
            failed=15,
            skipped=5,
            error=0,
            pass_rate=84.21
        )
        test_db.add(job)
        test_db.commit()

        assert job.id is not None
        assert job.job_id == "8"
        assert job.total == 100
        assert job.pass_rate == 84.21

    def test_job_unique_constraint(self, test_db, sample_module, sample_job):
        """Test unique constraint on (module_id, job_id)."""
        duplicate = Job(
            module_id=sample_module.id,
            job_id="8"
        )
        test_db.add(duplicate)

        with pytest.raises(Exception):  # IntegrityError
            test_db.commit()

    def test_job_test_results_relationship(self, test_db, sample_job, sample_test_results):
        """Test relationship between job and test results."""
        assert len(sample_job.test_results) == 3


class TestTestResult:
    """Tests for TestResult model."""

    def test_create_test_result(self, test_db, sample_job):
        """Test creating a test result."""
        result = TestResult(
            job_id=sample_job.id,
            file_path="tests/test_example.py",
            class_name="TestExample",
            test_name="test_something",
            status=TestStatusEnum.PASSED,
            setup_ip="10.0.0.1",
            topology="5s",
            order_index=0
        )
        test_db.add(result)
        test_db.commit()

        assert result.id is not None
        assert result.test_name == "test_something"
        assert result.status == TestStatusEnum.PASSED

    def test_test_key_property(self, test_db, sample_test_results):
        """Test test_key property."""
        result = sample_test_results[0]
        expected_key = "tests/test_policy.py::TestBusinessPolicy::test_create_policy"
        assert result.test_key == expected_key

    def test_rerun_flags(self, test_db, sample_test_results):
        """Test rerun tracking flags."""
        # First result: not rerun
        assert sample_test_results[0].was_rerun is False
        assert sample_test_results[0].rerun_still_failed is False

        # Third result: was rerun and passed
        assert sample_test_results[2].was_rerun is True
        assert sample_test_results[2].rerun_still_failed is False

    def test_failure_message(self, test_db, sample_test_results):
        """Test failure message storage."""
        failed_result = sample_test_results[1]
        assert failed_result.status == TestStatusEnum.FAILED
        assert failed_result.failure_message == "AssertionError: Policy not deleted"


class TestAppSettings:
    """Tests for AppSettings model."""

    def test_create_setting(self, test_db):
        """Test creating a setting."""
        setting = AppSettings(
            key="AUTO_UPDATE_ENABLED",
            value="true",
            description="Enable automatic polling"
        )
        test_db.add(setting)
        test_db.commit()

        assert setting.id is not None
        assert setting.key == "AUTO_UPDATE_ENABLED"
        assert setting.value == "true"

    def test_unique_key_constraint(self, test_db):
        """Test unique constraint on key."""
        setting1 = AppSettings(key="TEST_KEY", value="value1")
        setting2 = AppSettings(key="TEST_KEY", value="value2")

        test_db.add(setting1)
        test_db.commit()

        test_db.add(setting2)
        with pytest.raises(Exception):  # IntegrityError
            test_db.commit()


class TestJenkinsPollingLog:
    """Tests for JenkinsPollingLog model."""

    def test_create_polling_log(self, test_db, sample_release):
        """Test creating a polling log entry."""
        log = JenkinsPollingLog(
            release_id=sample_release.id,
            status="success",
            modules_downloaded=5,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        test_db.add(log)
        test_db.commit()

        assert log.id is not None
        assert log.status == "success"
        assert log.modules_downloaded == 5

    def test_polling_log_with_error(self, test_db, sample_release):
        """Test polling log with error message."""
        log = JenkinsPollingLog(
            release_id=sample_release.id,
            status="failed",
            error_message="Connection timeout",
            started_at=datetime.utcnow()
        )
        test_db.add(log)
        test_db.commit()

        assert log.status == "failed"
        assert log.error_message == "Connection timeout"


class TestTestStatusEnum:
    """Tests for TestStatusEnum."""

    def test_enum_values(self):
        """Test enum has correct values."""
        assert TestStatusEnum.PASSED.value == "PASSED"
        assert TestStatusEnum.FAILED.value == "FAILED"
        assert TestStatusEnum.SKIPPED.value == "SKIPPED"
        assert TestStatusEnum.ERROR.value == "ERROR"

    def test_enum_comparison(self):
        """Test enum comparison."""
        assert TestStatusEnum.PASSED == TestStatusEnum.PASSED
        assert TestStatusEnum.PASSED != TestStatusEnum.FAILED
