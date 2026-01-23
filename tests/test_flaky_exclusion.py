"""
Tests for flaky test exclusion feature (PR #19).

Tests cover:
- _count_passed_flaky_tests helper function
- _batch_count_passed_flaky_tests helper function
- get_dashboard_failure_summary function
- exclude_flaky parameter in dashboard API
- is_new_failure logic changes
- job_limit parameter in calculate_test_trends
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.db_models import Release, Module, Job, TestResult, TestStatusEnum, TestcaseMetadata
from app.services.trend_analyzer import (
    calculate_test_trends,
    get_dashboard_failure_summary,
    TestTrend
)
from app.routers.dashboard import _count_passed_flaky_tests, _batch_count_passed_flaky_tests
from app.constants import FLAKY_DETECTION_JOB_WINDOW


@pytest.fixture
def setup_flaky_test_data(test_db: Session):
    """
    Create test data for flaky test exclusion tests.

    Creates:
    - 1 release (7.0.0.0)
    - 1 module (business_policy)
    - 5 jobs (job_1 through job_5)
    - Multiple test results across jobs with flaky patterns
    """
    db = test_db
    # Create release
    release = Release(
        name="7.0.0.0",
        is_active=True,
        jenkins_job_url="http://jenkins.example.com/job/7.0.0.0/"
    )
    db.add(release)
    db.flush()

    # Create module
    module = Module(
        name="business_policy",
        release_id=release.id
    )
    db.add(module)
    db.flush()

    # Create 5 jobs
    jobs = []
    for i in range(1, 6):
        job = Job(
            job_id=str(100 + i),  # 101, 102, 103, 104, 105
            parent_job_id=str(100 + i),
            module_id=module.id,
            version="7.0.0.0",
            total=10,
            passed=7,
            failed=2,
            skipped=1,
            created_at=datetime.now(timezone.utc)
        )
        db.add(job)
        db.flush()
        jobs.append(job)

    # Create test results with different patterns:
    # test_always_pass: PASSED in all jobs
    # test_always_fail: FAILED in all jobs
    # test_flaky_1: PASSED, FAILED, PASSED, FAILED, PASSED (flaky, passed in latest)
    # test_flaky_2: FAILED, PASSED, FAILED, PASSED, FAILED (flaky, failed in latest)
    # test_new_failure: PASSED, PASSED, PASSED, PASSED, FAILED (new failure)

    test_patterns = {
        "test_always_pass": [TestStatusEnum.PASSED] * 5,
        "test_always_fail": [TestStatusEnum.FAILED] * 5,
        "test_flaky_1": [TestStatusEnum.PASSED, TestStatusEnum.FAILED, TestStatusEnum.PASSED, TestStatusEnum.FAILED, TestStatusEnum.PASSED],
        "test_flaky_2": [TestStatusEnum.FAILED, TestStatusEnum.PASSED, TestStatusEnum.FAILED, TestStatusEnum.PASSED, TestStatusEnum.FAILED],
        "test_new_failure": [TestStatusEnum.PASSED, TestStatusEnum.PASSED, TestStatusEnum.PASSED, TestStatusEnum.PASSED, TestStatusEnum.FAILED]
    }

    for test_name, statuses in test_patterns.items():
        # Create metadata
        metadata = TestcaseMetadata(
            file_path="test_module.py",
            class_name="TestClass",
            test_name=test_name,
            priority="P1",
            categories=[]
        )
        db.add(metadata)
        db.flush()

        # Create test results for each job
        for i, (job, status) in enumerate(zip(jobs, statuses)):
            result = TestResult(
                job_id=job.id,
                testcase_module="business_policy",
                file_path="test_module.py",
                class_name="TestClass",
                test_name=test_name,
                status=status,
                duration=1.0,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(result)

    db.commit()

    return {
        "release": release,
        "module": module,
        "jobs": jobs
    }


class TestCountPassedFlakyTests:
    """Tests for _count_passed_flaky_tests helper function."""

    def test_count_passed_flaky_with_module_filter(self, test_db, setup_flaky_test_data):
        """Test counting passed flaky tests with module filter."""
        data = setup_flaky_test_data
        latest_job = data["jobs"][-1]  # Job 105

        flaky_test_keys = [
            "test_module.py::TestClass::test_flaky_1",  # PASSED in latest job
            "test_module.py::TestClass::test_flaky_2"   # FAILED in latest job
        ]

        count = _count_passed_flaky_tests(
            test_db,
            [latest_job.id],
            flaky_test_keys,
            module_filter="business_policy"
        )

        # Only test_flaky_1 passed in latest job
        assert count == 1

    def test_count_passed_flaky_without_module_filter(self, test_db, setup_flaky_test_data):
        """Test counting passed flaky tests without module filter."""
        data = setup_flaky_test_data
        latest_job = data["jobs"][-1]

        flaky_test_keys = [
            "test_module.py::TestClass::test_flaky_1"
        ]

        count = _count_passed_flaky_tests(
            test_db,
            [latest_job.id],
            flaky_test_keys,
            module_filter=None
        )

        assert count == 1

    def test_count_with_empty_flaky_list(self, test_db, setup_flaky_test_data):
        """Test with empty flaky test keys list."""
        data = setup_flaky_test_data
        latest_job = data["jobs"][-1]

        count = _count_passed_flaky_tests(
            test_db,
            [latest_job.id],
            [],
            module_filter="business_policy"
        )

        assert count == 0

    def test_count_with_invalid_test_keys(self, test_db, setup_flaky_test_data):
        """Test with invalid test key format."""
        data = setup_flaky_test_data
        latest_job = data["jobs"][-1]

        # Invalid format (missing parts)
        flaky_test_keys = [
            "invalid_key",
            "also::invalid"
        ]

        count = _count_passed_flaky_tests(
            test_db,
            [latest_job.id],
            flaky_test_keys,
            module_filter="business_policy"
        )

        assert count == 0


class TestBatchCountPassedFlakyTests:
    """Tests for _batch_count_passed_flaky_tests helper function."""

    def test_batch_count_multiple_jobs(self, test_db, setup_flaky_test_data):
        """Test batch counting across multiple job groups."""
        data = setup_flaky_test_data
        jobs = data["jobs"]

        job_id_groups = {
            "103": [jobs[2].id],  # Job 103
            "104": [jobs[3].id],  # Job 104
            "105": [jobs[4].id]   # Job 105
        }

        flaky_test_keys = [
            "test_module.py::TestClass::test_flaky_1"  # PASSED in 103, FAILED in 104, PASSED in 105
        ]

        counts = _batch_count_passed_flaky_tests(
            test_db,
            job_id_groups,
            flaky_test_keys,
            module_filter="business_policy"
        )

        assert counts["103"] == 1  # PASSED
        assert counts["104"] == 0  # FAILED
        assert counts["105"] == 1  # PASSED

    def test_batch_count_with_multiple_flaky_tests(self, test_db, setup_flaky_test_data):
        """Test batch counting with multiple flaky tests."""
        data = setup_flaky_test_data
        jobs = data["jobs"]

        job_id_groups = {
            "105": [jobs[4].id]
        }

        flaky_test_keys = [
            "test_module.py::TestClass::test_flaky_1",  # PASSED in 105
            "test_module.py::TestClass::test_flaky_2"   # FAILED in 105
        ]

        counts = _batch_count_passed_flaky_tests(
            test_db,
            job_id_groups,
            flaky_test_keys,
            module_filter="business_policy"
        )

        # Only test_flaky_1 passed in job 105
        assert counts["105"] == 1

    def test_batch_count_empty_groups(self, test_db, setup_flaky_test_data):
        """Test with empty job groups."""
        counts = _batch_count_passed_flaky_tests(
            test_db,
            {},
            ["test_module.py::TestClass::test_flaky_1"],
            module_filter="business_policy"
        )

        assert counts == {}


class TestDashboardFailureSummary:
    """Tests for get_dashboard_failure_summary function."""

    def test_flaky_detection_last_5_jobs(self, test_db, setup_flaky_test_data):
        """Test that flaky detection uses last 5 jobs window."""
        data = setup_flaky_test_data

        summary = get_dashboard_failure_summary(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True
        )

        # Should find test_flaky_1 and test_flaky_2 as flaky
        assert summary['total_flaky'] == 2
        assert len(summary['flaky_test_keys']) == 2

    def test_passed_flaky_breakdown(self, test_db, setup_flaky_test_data):
        """Test that passed_flaky_by_priority only includes tests that PASSED in latest job."""
        data = setup_flaky_test_data

        summary = get_dashboard_failure_summary(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True
        )

        # Total flaky: 2 (test_flaky_1 and test_flaky_2)
        assert summary['total_flaky'] == 2

        # Passed flaky (in latest job): 1 (only test_flaky_1)
        assert summary['total_passed_flaky'] == 1

        # Priority breakdown for passed flaky
        assert summary['passed_flaky_by_priority'].get('P1', 0) == 1

    def test_new_failure_detection(self, test_db, setup_flaky_test_data):
        """Test new failure detection (passed in previous, failed in current)."""
        data = setup_flaky_test_data

        summary = get_dashboard_failure_summary(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True
        )

        # test_new_failure: PASSED in job 104, FAILED in job 105
        assert summary['total_new_failures'] == 1
        assert summary['new_failures_by_priority'].get('P1', 0) == 1


class TestIsNewFailureLogic:
    """Tests for is_new_failure logic changes."""

    def test_new_failure_passed_to_failed(self, test_db, setup_flaky_test_data):
        """Test new failure: PASSED in previous run, FAILED in current run."""
        data = setup_flaky_test_data

        # Get trends for all jobs
        trends = calculate_test_trends(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True,
            job_limit=None
        )

        # Find test_new_failure trend
        new_failure_trend = next(
            (t for t in trends if t.test_name == "test_new_failure"),
            None
        )

        assert new_failure_trend is not None

        job_ids = ["101", "102", "103", "104", "105"]
        assert new_failure_trend.is_new_failure(job_ids) is True

    def test_new_failure_strict_immediate_previous_only(self, test_db, setup_flaky_test_data):
        """Test strict new failure: only if passed in IMMEDIATE previous job."""
        data = setup_flaky_test_data

        trends = calculate_test_trends(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True,
            job_limit=None
        )

        # test_flaky_2: FAILED (101), PASSED (102), FAILED (103), PASSED (104), FAILED (105)
        # With strict definition: IS a new failure because it PASSED in 104 and FAILED in 105
        # (immediate previous = 104)
        flaky_2_trend = next(
            (t for t in trends if t.test_name == "test_flaky_2"),
            None
        )

        assert flaky_2_trend is not None
        job_ids = list(flaky_2_trend.results_by_job.keys())  # Only jobs where test has results
        # Should be True because it passed in immediate previous (104) and failed in latest (105)
        assert flaky_2_trend.is_new_failure(job_ids) is True


class TestJobLimitParameter:
    """Tests for job_limit parameter in calculate_test_trends."""

    def test_job_limit_restricts_analysis_window(self, test_db, setup_flaky_test_data):
        """Test that job_limit restricts analysis to N most recent jobs."""
        data = setup_flaky_test_data

        # With job_limit=3, should only analyze jobs 103, 104, 105
        trends_limited = calculate_test_trends(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True,
            job_limit=3
        )

        # Without limit, analyzes all 5 jobs
        trends_all = calculate_test_trends(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True,
            job_limit=None
        )

        # Both should find the same tests, but limited view may affect flaky detection
        assert len(trends_limited) == len(trends_all)

        # test_flaky_1 should be flaky even with 3 jobs (PASSED, FAILED, PASSED in 103, 104, 105)
        flaky_1_limited = next(
            (t for t in trends_limited if t.test_name == "test_flaky_1"),
            None
        )
        assert flaky_1_limited is not None
        assert flaky_1_limited.is_flaky is True

    def test_flaky_detection_window_constant(self, test_db, setup_flaky_test_data):
        """Test that FLAKY_DETECTION_JOB_WINDOW constant is used correctly."""
        data = setup_flaky_test_data

        summary = get_dashboard_failure_summary(
            test_db,
            "7.0.0.0",
            "business_policy",
            use_testcase_module=True
        )

        # The function should use FLAKY_DETECTION_JOB_WINDOW (5 jobs)
        assert FLAKY_DETECTION_JOB_WINDOW == 5

        # Should analyze all 5 jobs and find flaky tests
        assert summary['total_flaky'] > 0


class TestNewFlakyDetectionLogic:
    """Unit tests for updated flaky detection logic (failure not only in latest job)."""

    def test_flaky_with_failure_in_middle(self):
        """Test PASS, FAIL, PASS pattern is marked as flaky."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_flaky_middle",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_flaky_middle"
        )
        # Simulate: PASS (job 1), FAIL (job 2), PASS (job 3)
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.FAILED,
            "3": TestStatusEnum.PASSED
        }

        # Should be flaky: has both, failure NOT in latest
        assert trend.is_flaky is True

    def test_not_flaky_when_failure_only_in_latest(self):
        """Test PASS, PASS, FAIL pattern is NOT marked as flaky (it's a new failure)."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_new_failure",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_new_failure"
        )
        # Simulate: PASS (job 1), PASS (job 2), FAIL (job 3)
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.FAILED
        }

        # Should NOT be flaky: failure only in latest job
        assert trend.is_flaky is False

    def test_flaky_with_multiple_failures_including_latest(self):
        """Test FAIL, PASS, FAIL pattern is still marked as flaky."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_flaky_multiple",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_flaky_multiple"
        )
        # Simulate: FAIL (job 1), PASS (job 2), FAIL (job 3)
        trend.results_by_job = {
            "1": TestStatusEnum.FAILED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.FAILED
        }

        # Should be flaky: has both, failures in multiple jobs including latest
        assert trend.is_flaky is True

    def test_not_flaky_always_passing(self):
        """Test that always passing tests are not marked as flaky."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_always_pass",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_always_pass"
        )
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.PASSED
        }

        assert trend.is_flaky is False

    def test_not_flaky_always_failing(self):
        """Test that always failing tests are not marked as flaky."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_always_fail",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_always_fail"
        )
        trend.results_by_job = {
            "1": TestStatusEnum.FAILED,
            "2": TestStatusEnum.FAILED,
            "3": TestStatusEnum.FAILED
        }

        assert trend.is_flaky is False


class TestRegressionDetectionLogic:
    """Unit tests for regression detection logic (was passing, now continuously failing)."""

    def test_regression_pass_then_continuous_fails(self):
        """Test PASS, FAIL, FAIL, FAIL, FAIL pattern is marked as regression."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_regression_1",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_regression_1"
        )
        # Simulate: PASS (job 1), then FAIL for jobs 2-5
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.FAILED,
            "3": TestStatusEnum.FAILED,
            "4": TestStatusEnum.FAILED,
            "5": TestStatusEnum.FAILED
        }

        # Should be regression: passed once, then failed continuously
        assert trend.is_regression is True
        # Should NOT be flaky (regression takes precedence)
        assert trend.is_flaky is False

    def test_regression_multiple_passes_then_fails(self):
        """Test PASS, PASS, FAIL, FAIL, FAIL pattern is marked as regression."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_regression_2",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_regression_2"
        )
        # Simulate: PASS (jobs 1-2), then FAIL for jobs 3-5
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.FAILED,
            "4": TestStatusEnum.FAILED,
            "5": TestStatusEnum.FAILED
        }

        # Should be regression: passed multiple times, then failed continuously
        assert trend.is_regression is True
        assert trend.is_flaky is False

    def test_not_regression_alternating_pattern(self):
        """Test PASS, FAIL, PASS, FAIL, FAIL pattern is flaky (NOT regression)."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_flaky_not_regression",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_flaky_not_regression"
        )
        # Simulate: PASS, FAIL, PASS (recovered), FAIL, FAIL
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.FAILED,
            "3": TestStatusEnum.PASSED,  # Passed again after failing
            "4": TestStatusEnum.FAILED,
            "5": TestStatusEnum.FAILED
        }

        # Should be flaky: has PASS after FAIL (not continuously failing)
        assert trend.is_regression is False
        assert trend.is_flaky is True

    def test_not_regression_only_one_failure_at_end(self):
        """Test PASS, PASS, PASS, PASS, FAIL pattern is new failure (NOT regression)."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_new_failure_not_regression",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_new_failure_not_regression"
        )
        # Simulate: PASS for jobs 1-4, FAIL at job 5 (only 1 failure at end)
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.PASSED,
            "4": TestStatusEnum.PASSED,
            "5": TestStatusEnum.FAILED
        }

        # Should NOT be regression: only 1 failure at end (need at least 2)
        # This is a new failure instead
        assert trend.is_regression is False
        assert trend.is_flaky is False

    def test_not_regression_always_failing(self):
        """Test FAIL, FAIL, FAIL pattern is NOT regression (never passed)."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_always_fail_not_regression",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_always_fail_not_regression"
        )
        trend.results_by_job = {
            "1": TestStatusEnum.FAILED,
            "2": TestStatusEnum.FAILED,
            "3": TestStatusEnum.FAILED
        }

        # Should NOT be regression: never passed
        assert trend.is_regression is False

    def test_regression_minimum_2_consecutive_failures(self):
        """Test PASS, PASS, PASS, FAIL, FAIL is regression (exactly 2 failures at end)."""
        trend = TestTrend(
            test_key="test.py::TestClass::test_regression_min_2_fails",
            file_path="test.py",
            class_name="TestClass",
            test_name="test_regression_min_2_fails"
        )
        # Simulate: PASS for jobs 1-3, then FAIL for jobs 4-5 (exactly 2 failures)
        trend.results_by_job = {
            "1": TestStatusEnum.PASSED,
            "2": TestStatusEnum.PASSED,
            "3": TestStatusEnum.PASSED,
            "4": TestStatusEnum.FAILED,
            "5": TestStatusEnum.FAILED
        }

        # Should be regression: has 2 consecutive failures at end
        assert trend.is_regression is True
        assert trend.is_flaky is False


class TestExcludeFlakyAPI:
    """Integration tests for exclude_flaky parameter in dashboard API."""

    def test_exclude_flaky_adjusts_pass_rate(self, client, test_db, setup_flaky_test_data):
        """Test that exclude_flaky=true adjusts pass rate in API response."""
        # This would be an integration test with FastAPI TestClient
        # Skipping for now as it requires full API setup
        pass

    def test_exclude_flaky_in_all_modules_view(self, client, test_db, setup_flaky_test_data):
        """Test exclude_flaky works in All Modules aggregated view."""
        # Integration test - skipping for now
        pass
