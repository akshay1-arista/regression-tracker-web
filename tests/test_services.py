"""
Tests for service layer (data_service and trend_analyzer).
"""
import pytest

from app.services import data_service, trend_analyzer
from app.models.db_models import TestStatusEnum


class TestDataService:
    """Tests for data_service module."""

    def test_get_all_releases(self, test_db, sample_release):
        """Test getting all releases."""
        releases = data_service.get_all_releases(test_db)
        assert len(releases) >= 1
        assert releases[0].name == "7.0.0.0"

    def test_get_all_releases_active_only(self, test_db, sample_release):
        """Test getting only active releases."""
        releases = data_service.get_all_releases(test_db, active_only=True)
        assert all(r.is_active for r in releases)

    def test_get_release_by_name(self, test_db, sample_release):
        """Test getting a release by name."""
        release = data_service.get_release_by_name(test_db, "7.0.0.0")
        assert release is not None
        assert release.name == "7.0.0.0"

    def test_get_release_by_name_not_found(self, test_db):
        """Test getting non-existent release."""
        release = data_service.get_release_by_name(test_db, "nonexistent")
        assert release is None

    def test_get_modules_for_release(self, test_db, sample_module):
        """Test getting modules for a release."""
        modules = data_service.get_modules_for_release(test_db, "7.0.0.0")
        assert len(modules) >= 1
        assert modules[0].name == "business_policy"

    def test_get_module(self, test_db, sample_module):
        """Test getting a specific module."""
        module = data_service.get_module(test_db, "7.0.0.0", "business_policy")
        assert module is not None
        assert module.name == "business_policy"

    def test_get_jobs_for_module(self, test_db, sample_job):
        """Test getting jobs for a module."""
        jobs = data_service.get_jobs_for_module(test_db, "7.0.0.0", "business_policy")
        assert len(jobs) >= 1
        assert jobs[0].job_id == "8"

    def test_get_jobs_for_module_with_limit(self, test_db, sample_job):
        """Test getting jobs with limit."""
        jobs = data_service.get_jobs_for_module(test_db, "7.0.0.0", "business_policy", limit=1)
        assert len(jobs) <= 1

    def test_get_job(self, test_db, sample_job):
        """Test getting a specific job."""
        job = data_service.get_job(test_db, "7.0.0.0", "business_policy", "8")
        assert job is not None
        assert job.job_id == "8"

    def test_get_job_summary_stats(self, test_db, sample_job):
        """Test getting job summary statistics."""
        stats = data_service.get_job_summary_stats(test_db, "7.0.0.0", "business_policy")
        assert stats["total_jobs"] >= 1
        assert "latest_job" in stats
        assert "average_pass_rate" in stats

    def test_get_pass_rate_history(self, test_db, sample_job):
        """Test getting pass rate history."""
        history = data_service.get_pass_rate_history(test_db, "7.0.0.0", "business_policy")
        assert isinstance(history, list)
        assert len(history) >= 1
        assert "job_id" in history[0]
        assert "pass_rate" in history[0]

    def test_get_test_results_for_job(self, test_db, sample_test_results):
        """Test getting test results for a job."""
        results = data_service.get_test_results_for_job(test_db, "7.0.0.0", "business_policy", "8")
        assert len(results) == 3  # Sample data has 3 tests

    def test_get_test_results_with_status_filter(self, test_db, sample_test_results):
        """Test getting test results filtered by status."""
        results = data_service.get_test_results_for_job(
            test_db, "7.0.0.0", "business_policy", "8",
            status_filter=TestStatusEnum.PASSED
        )
        assert all(r.status == TestStatusEnum.PASSED for r in results)

    def test_get_test_results_with_topology_filter(self, test_db, sample_test_results):
        """Test getting test results filtered by topology."""
        results = data_service.get_test_results_for_job(
            test_db, "7.0.0.0", "business_policy", "8",
            topology_filter="5s"
        )
        assert all(r.topology == "5s" for r in results)

    def test_get_test_results_with_search(self, test_db, sample_test_results):
        """Test getting test results with search."""
        results = data_service.get_test_results_for_job(
            test_db, "7.0.0.0", "business_policy", "8",
            search="create"
        )
        assert len(results) >= 1
        assert any("create" in r.test_name.lower() for r in results)

    def test_get_test_results_grouped_by_topology(self, test_db, sample_test_results):
        """Test getting test results grouped by topology."""
        grouped = data_service.get_test_results_grouped_by_topology(
            test_db, "7.0.0.0", "business_policy", "8"
        )
        assert isinstance(grouped, dict)
        assert len(grouped) >= 1

    def test_get_test_results_by_class(self, test_db, sample_test_results):
        """Test getting test results grouped by class."""
        by_class = data_service.get_test_results_by_class(
            test_db, "7.0.0.0", "business_policy", "8"
        )
        assert isinstance(by_class, dict)
        assert "TestBusinessPolicy" in by_class

    def test_get_unique_topologies(self, test_db, sample_test_results):
        """Test getting unique topologies."""
        topologies = data_service.get_unique_topologies(test_db, "7.0.0.0", "business_policy", "8")
        assert isinstance(topologies, list)
        assert "5s" in topologies

    def test_get_database_statistics(self, test_db, sample_test_results):
        """Test getting database statistics."""
        stats = data_service.get_database_statistics(test_db)
        assert stats["releases"] >= 1
        assert stats["modules"] >= 1
        assert stats["jobs"] >= 1
        assert stats["test_results"] >= 3


class TestTrendAnalyzer:
    """Tests for trend_analyzer module."""

    def test_calculate_test_trends(self, test_db, sample_test_results):
        """Test calculating test trends."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        assert len(trends) == 3  # 3 unique tests in sample data

    def test_test_trend_properties(self, test_db, sample_test_results):
        """Test TestTrend class properties."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        trend = trends[0]

        # Test basic properties
        assert trend.test_key is not None
        assert trend.test_name is not None
        assert trend.class_name is not None
        assert trend.file_path is not None

        # Test computed properties
        assert isinstance(trend.is_flaky, bool)
        assert isinstance(trend.is_always_failing, bool)
        assert isinstance(trend.is_always_passing, bool)

    def test_test_trend_latest_status(self, test_db, sample_test_results):
        """Test getting latest status for a trend."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        trend = trends[0]
        assert trend.latest_status is not None

    def test_test_trend_rerun_info(self, test_db, sample_test_results):
        """Test rerun info tracking in trends."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        # Find the trend for the rerun test
        rerun_trend = next(
            (t for t in trends if t.test_name == "test_update_policy"),
            None
        )
        assert rerun_trend is not None
        assert "8" in rerun_trend.rerun_info_by_job
        assert rerun_trend.rerun_info_by_job["8"]["was_rerun"] is True

    def test_get_trends_by_class(self, test_db, sample_test_results):
        """Test grouping trends by class."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        by_class = trend_analyzer.get_trends_by_class(trends)

        assert isinstance(by_class, dict)
        assert "TestBusinessPolicy" in by_class
        assert len(by_class["TestBusinessPolicy"]) == 3

    def test_get_failure_summary(self, test_db, sample_test_results):
        """Test getting failure summary."""
        summary = trend_analyzer.get_failure_summary(test_db, "7.0.0.0", "business_policy")

        assert "total_unique_tests" in summary
        assert "flaky_count" in summary
        assert "always_failing_count" in summary
        assert "new_failures_count" in summary
        assert isinstance(summary["flaky_tests"], list)
        assert isinstance(summary["always_failing_tests"], list)
        assert isinstance(summary["new_failures"], list)

    def test_filter_trends_flaky_only(self, test_db, sample_test_results):
        """Test filtering trends for flaky tests only."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        filtered = trend_analyzer.filter_trends(trends, flaky_only=True)
        assert all(t.is_flaky for t in filtered)

    def test_filter_trends_always_failing_only(self, test_db, sample_test_results):
        """Test filtering trends for always-failing tests only."""
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        filtered = trend_analyzer.filter_trends(trends, always_failing_only=True)
        assert all(t.is_always_failing for t in filtered)
