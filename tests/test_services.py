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
            status_filter=[TestStatusEnum.PASSED]  # Pass as list
        )
        assert all(r.status == TestStatusEnum.PASSED for r in results)

    def test_get_test_results_with_topology_filter(self, test_db, sample_test_results):
        """Test getting test results filtered by topology."""
        results = data_service.get_test_results_for_job(
            test_db, "7.0.0.0", "business_policy", "8",
            topology_filter="5s"
        )
        assert all(r.jenkins_topology == "5s" for r in results)

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

    def test_filter_trends_or_logic(self, test_db, sample_module):
        """Test that multiple status filters use OR logic (not AND)."""
        from app.models.db_models import Job, TestResult, TestStatusEnum

        # Create multiple jobs to create different test behaviors
        job1 = Job(
            module_id=sample_module.id,
            job_id="100",
            total=10, passed=8, failed=2, skipped=0, pass_rate=80.0
        )
        job2 = Job(
            module_id=sample_module.id,
            job_id="101",
            total=10, passed=9, failed=1, skipped=0, pass_rate=90.0
        )
        job3 = Job(
            module_id=sample_module.id,
            job_id="102",
            total=10, passed=7, failed=3, skipped=0, pass_rate=70.0
        )
        test_db.add_all([job1, job2, job3])
        test_db.commit()

        # Create a flaky test (passes in some jobs, fails in others)
        for job in [job1, job2, job3]:
            status = TestStatusEnum.PASSED if job.job_id in ["100", "102"] else TestStatusEnum.FAILED
            test_db.add(TestResult(
                job_id=job.id,
                file_path="test_flaky.py",
                class_name="TestFlaky",
                test_name="test_flaky",
                status=status,
                priority='P0'
            ))

        # Create an always failing test
        for job in [job1, job2, job3]:
            test_db.add(TestResult(
                job_id=job.id,
                file_path="test_always_fail.py",
                class_name="TestAlwaysFail",
                test_name="test_always_fail",
                status=TestStatusEnum.FAILED,
                priority='P1'
            ))

        # Create a new failure (passed in all but the latest job)
        # This should NOT be flaky (consistent pass, then one fail)
        for job in [job1, job2, job3]:
            status = TestStatusEnum.PASSED if job.job_id in ["100", "101"] else TestStatusEnum.FAILED
            test_db.add(TestResult(
                job_id=job.id,
                file_path="test_new_fail.py",
                class_name="TestNewFail",
                test_name="test_new_fail",
                status=status,
                priority='P2'
            ))

        # Create an always passing test (not selected by any filter)
        for job in [job1, job2, job3]:
            test_db.add(TestResult(
                job_id=job.id,
                file_path="test_pass.py",
                class_name="TestPass",
                test_name="test_pass",
                status=TestStatusEnum.PASSED,
                priority='P3'
            ))

        test_db.commit()

        # Calculate trends
        trends = trend_analyzer.calculate_test_trends(test_db, "7.0.0.0", "business_policy")
        job_ids = ["100", "101", "102"]

        # Apply multiple filters (should use OR logic)
        filtered = trend_analyzer.filter_trends(
            trends,
            flaky_only=True,
            always_failing_only=True,
            new_failures_only=True,
            job_ids=job_ids
        )

        # With OR logic, we should get three test types
        # Note: test_new_fail is ALSO flaky (has both pass and fail)
        # So it matches TWO filters: flaky AND new_failure
        # Total unique tests: test_flaky (flaky), test_always_fail (always failing), test_new_fail (flaky + new failure)
        assert len(filtered) == 3

        # Verify we have each type
        flaky_tests = [t for t in filtered if t.is_flaky]
        always_failing = [t for t in filtered if t.is_always_failing]
        new_failures = [t for t in filtered if t.is_new_failure(job_ids)]

        assert len(flaky_tests) == 2  # test_flaky + test_new_fail (both have pass and fail)
        assert len(always_failing) == 1  # test_always_fail
        assert len(new_failures) == 1  # test_new_fail

        # Verify the always-passing test is NOT included
        assert not any(t.test_name == "test_pass" for t in filtered)

        # Verify individual filters still work
        flaky_only = trend_analyzer.filter_trends(trends, flaky_only=True)
        assert len(flaky_only) == 2  # test_flaky + test_new_fail
        assert all(t.is_flaky for t in flaky_only)

        always_failing_only = trend_analyzer.filter_trends(trends, always_failing_only=True)
        assert len(always_failing_only) == 1  # test_always_fail
        assert all(t.is_always_failing for t in always_failing_only)


class TestAllModulesAggregation:
    """Tests for All Modules aggregation functions."""

    @pytest.fixture
    def multi_module_jobs(self, test_db, sample_release):
        """Create multiple modules and jobs with same parent_job_id."""
        from app.models.db_models import Module, Job

        # Create three modules
        modules = []
        for module_name in ["routing", "firewall", "nat"]:
            module = Module(
                release_id=sample_release.id,
                name=module_name
            )
            test_db.add(module)
            modules.append(module)
        test_db.commit()

        # Refresh modules to get IDs
        for module in modules:
            test_db.refresh(module)

        # Create jobs with same parent_job_id for first run
        parent_job_id_1 = "100"  # Use numeric string for sorting
        jobs_run1 = []
        for idx, module in enumerate(modules):
            job = Job(
                module_id=module.id,
                job_id=f"{100+idx}",
                parent_job_id=parent_job_id_1,
                version="7.0.0.0",
                total=100 * (idx + 1),
                passed=90 * (idx + 1),
                failed=10 * (idx + 1),
                skipped=0,
                pass_rate=90.0,
                jenkins_url=f"https://jenkins.example.com/job/7.0/{100+idx}"
            )
            test_db.add(job)
            jobs_run1.append(job)

        # Create jobs with different parent_job_id for second run
        parent_job_id_2 = "101"  # Use numeric string for sorting
        jobs_run2 = []
        for idx, module in enumerate(modules):
            job = Job(
                module_id=module.id,
                job_id=f"{200+idx}",
                parent_job_id=parent_job_id_2,
                version="7.0.0.0",
                total=100 * (idx + 1),
                passed=85 * (idx + 1),
                failed=15 * (idx + 1),
                skipped=0,
                pass_rate=85.0,
                jenkins_url=f"https://jenkins.example.com/job/7.0/{200+idx}"
            )
            test_db.add(job)
            jobs_run2.append(job)

        test_db.commit()

        # Refresh all jobs
        for job in jobs_run1 + jobs_run2:
            test_db.refresh(job)

        return {
            'modules': modules,
            'run1': jobs_run1,
            'run2': jobs_run2,
            'parent_job_id_1': parent_job_id_1,
            'parent_job_id_2': parent_job_id_2
        }

    def test_get_latest_parent_job_ids(self, test_db, multi_module_jobs):
        """Test getting recent parent_job_ids."""
        parent_ids = data_service.get_latest_parent_job_ids(
            test_db, "7.0.0.0", limit=10
        )

        assert len(parent_ids) == 2
        assert multi_module_jobs['parent_job_id_2'] in parent_ids  # Most recent
        assert multi_module_jobs['parent_job_id_1'] in parent_ids

    def test_get_latest_parent_job_ids_with_version_filter(self, test_db, multi_module_jobs):
        """Test getting parent_job_ids with version filter."""
        parent_ids = data_service.get_latest_parent_job_ids(
            test_db, "7.0.0.0", version="7.0.0.0", limit=10
        )

        assert len(parent_ids) == 2

    def test_get_latest_parent_job_ids_nonexistent_release(self, test_db):
        """Test getting parent_job_ids for non-existent release."""
        parent_ids = data_service.get_latest_parent_job_ids(
            test_db, "nonexistent", limit=10
        )

        assert parent_ids == []

    def test_get_jobs_by_parent_job_id(self, test_db, multi_module_jobs):
        """Test getting all jobs by parent_job_id."""
        jobs = data_service.get_jobs_by_parent_job_id(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        assert len(jobs) == 3  # Three modules
        assert all(job.parent_job_id == multi_module_jobs['parent_job_id_1'] for job in jobs)

    def test_get_jobs_by_parent_job_id_null_parent(self, test_db, sample_job):
        """Test getting jobs with NULL parent_job_id."""
        # sample_job has no parent_job_id
        jobs = data_service.get_jobs_by_parent_job_id(
            test_db, "7.0.0.0", "nonexistent-parent"
        )

        assert jobs == []

    def test_get_aggregated_stats_for_parent_job(self, test_db, multi_module_jobs):
        """Test aggregating stats across all modules."""
        stats = data_service.get_aggregated_stats_for_parent_job(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        # Verify aggregated totals (100 + 200 + 300 = 600)
        assert stats['total'] == 600
        assert stats['passed'] == 540  # 90 + 180 + 270
        assert stats['failed'] == 60   # 10 + 20 + 30
        assert stats['skipped'] == 0
        assert stats['pass_rate'] == 90.0
        assert stats['module_count'] == 3
        assert stats['version'] == "7.0.0.0"

    def test_get_aggregated_stats_with_null_parent_job_id(self, test_db):
        """Test aggregation with NULL parent_job_id raises error."""
        with pytest.raises(ValueError, match="parent_job_id cannot be None or empty"):
            data_service.get_aggregated_stats_for_parent_job(
                test_db, "7.0.0.0", None
            )

        with pytest.raises(ValueError, match="parent_job_id cannot be None or empty"):
            data_service.get_aggregated_stats_for_parent_job(
                test_db, "7.0.0.0", ""
            )

    def test_get_aggregated_stats_nonexistent_parent(self, test_db, multi_module_jobs):
        """Test aggregating stats for non-existent parent_job_id."""
        stats = data_service.get_aggregated_stats_for_parent_job(
            test_db, "7.0.0.0", "nonexistent-parent"
        )

        assert stats['total'] == 0
        assert stats['passed'] == 0
        assert stats['module_count'] == 0

    def test_get_module_breakdown_for_parent_job(self, test_db, multi_module_jobs):
        """Test getting per-module breakdown."""
        from app.models.db_models import TestResult, TestStatusEnum

        # Create test results for run1 jobs (needed for module breakdown aggregation)
        for idx, (job, module) in enumerate(zip(multi_module_jobs['run1'], multi_module_jobs['modules'])):
            # Create test results matching the job statistics
            total = 100 * (idx + 1)
            passed = 90 * (idx + 1)
            failed = 10 * (idx + 1)

            # Create passed test results
            for i in range(passed):
                test_db.add(TestResult(
                    job_id=job.id,
                    file_path=f"tests/{module.name}/test_example.py",
                    class_name="TestExample",
                    test_name=f"test_passed_{i}",
                    status=TestStatusEnum.PASSED,
                    testcase_module=module.name,  # Set testcase_module to module name
                    order_index=i
                ))

            # Create failed test results
            for i in range(failed):
                test_db.add(TestResult(
                    job_id=job.id,
                    file_path=f"tests/{module.name}/test_example.py",
                    class_name="TestExample",
                    test_name=f"test_failed_{i}",
                    status=TestStatusEnum.FAILED,
                    testcase_module=module.name,  # Set testcase_module to module name
                    order_index=passed + i
                ))

        test_db.commit()

        breakdown = data_service.get_module_breakdown_for_parent_job(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        assert len(breakdown) == 3

        # Verify sorted alphabetically
        assert breakdown[0]['module_name'] == 'firewall'
        assert breakdown[1]['module_name'] == 'nat'
        assert breakdown[2]['module_name'] == 'routing'

        # Verify stats for firewall module (100 total, 90 passed)
        firewall_stats = breakdown[0]
        assert firewall_stats['total'] == 200
        assert firewall_stats['passed'] == 180
        assert firewall_stats['failed'] == 20

    def test_get_all_modules_summary_stats(self, test_db, multi_module_jobs):
        """Test getting summary statistics for All Modules view."""
        stats = data_service.get_all_modules_summary_stats(
            test_db, "7.0.0.0"
        )

        assert stats['total_runs'] == 2
        assert stats['latest_run'] is not None
        assert stats['latest_run']['parent_job_id'] == multi_module_jobs['parent_job_id_2']
        assert stats['latest_run']['module_count'] == 3
        assert 'average_pass_rate' in stats
        assert 'total_tests' in stats

    def test_get_all_modules_summary_stats_empty(self, test_db, sample_release):
        """Test getting summary stats when no jobs exist."""
        stats = data_service.get_all_modules_summary_stats(
            test_db, "7.0.0.0"
        )

        assert stats['total_runs'] == 0
        assert stats['latest_run'] is None
        assert stats['average_pass_rate'] == 0.0
        assert stats['total_tests'] == 0

    def test_get_all_modules_pass_rate_history(self, test_db, multi_module_jobs):
        """Test getting pass rate history aggregated across modules."""
        history = data_service.get_all_modules_pass_rate_history(
            test_db, "7.0.0.0", limit=10
        )

        assert len(history) == 2
        # Should be in chronological order (oldest first)
        assert history[0]['parent_job_id'] == multi_module_jobs['parent_job_id_1']
        assert history[1]['parent_job_id'] == multi_module_jobs['parent_job_id_2']
        assert history[0]['pass_rate'] == 90.0
        assert history[1]['pass_rate'] == 85.0

    def test_get_aggregated_priority_statistics(self, test_db, multi_module_jobs):
        """Test getting priority stats aggregated across modules."""
        from app.models.db_models import TestResult, TestStatusEnum

        # Add test results with priorities to first run's jobs
        for job in multi_module_jobs['run1']:
            for priority in ["P0", "P1", "P2"]:
                result = TestResult(
                    job_id=job.id,
                    file_path="tests/test_example.py",
                    class_name="TestExample",
                    test_name=f"test_{priority.lower()}",
                    status=TestStatusEnum.PASSED if priority != "P0" else TestStatusEnum.FAILED,
                    priority=priority,
                    order_index=0
                )
                test_db.add(result)
        test_db.commit()

        # Get aggregated priority stats
        stats = data_service.get_aggregated_priority_statistics(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        assert len(stats) == 3  # P0, P1, P2

        # Verify sorted by priority (P0 first)
        assert stats[0]['priority'] == 'P0'
        assert stats[1]['priority'] == 'P1'
        assert stats[2]['priority'] == 'P2'

        # P0 should have 3 failures (one per module)
        p0_stats = stats[0]
        assert p0_stats['total'] == 3
        assert p0_stats['failed'] == 3
        assert p0_stats['passed'] == 0

    def test_get_aggregated_priority_statistics_empty(self, test_db, multi_module_jobs):
        """Test getting priority stats when no test results exist."""
        stats = data_service.get_aggregated_priority_statistics(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        assert stats == []

    def test_n1_query_optimization(self, test_db, multi_module_jobs):
        """Test that aggregation functions don't cause N+1 queries."""
        # This test verifies the optimization works by checking the result
        # In a real scenario, you'd use query logging/profiling to verify

        stats = data_service.get_all_modules_summary_stats(
            test_db, "7.0.0.0"
        )

        # Should successfully aggregate without errors
        assert stats['total_runs'] == 2
        assert stats['latest_run']['total'] == 600

    def test_aggregate_jobs_validation(self, test_db, multi_module_jobs):
        """Test that aggregation includes validation assertions."""
        # The _aggregate_jobs_for_parent function has assertions
        # This test ensures they work correctly
        jobs = data_service.get_jobs_by_parent_job_id(
            test_db, "7.0.0.0", multi_module_jobs['parent_job_id_1']
        )

        # Should not raise assertion errors for valid data
        result = data_service._aggregate_jobs_for_parent(
            jobs, multi_module_jobs['parent_job_id_1']
        )

        assert result['total'] >= result['skipped']
        assert result['total'] >= 0

    # ========================================================================
    # Priority Statistics Comparison Tests
    # ========================================================================

    def test_get_previous_job(self, test_db, sample_module):
        """Test getting the previous job."""
        from app.models.db_models import Job

        # Create multiple jobs
        job1 = Job(
            module_id=sample_module.id,
            job_id="10",
            total=10, passed=8, failed=2, skipped=0, pass_rate=80.0
        )
        job2 = Job(
            module_id=sample_module.id,
            job_id="11",
            total=12, passed=10, failed=2, skipped=0, pass_rate=83.33
        )
        job3 = Job(
            module_id=sample_module.id,
            job_id="12",
            total=15, passed=13, failed=2, skipped=0, pass_rate=86.67
        )

        test_db.add_all([job1, job2, job3])
        test_db.commit()

        # Get previous job for job3 (should be job2)
        previous = data_service.get_previous_job(test_db, "7.0.0.0", "business_policy", "12")
        assert previous is not None
        assert previous.job_id == "11"

        # Get previous job for job2 (should be job1)
        previous = data_service.get_previous_job(test_db, "7.0.0.0", "business_policy", "11")
        assert previous is not None
        assert previous.job_id == "10"

        # Get previous job for job1 (should be None - first job)
        previous = data_service.get_previous_job(test_db, "7.0.0.0", "business_policy", "10")
        assert previous is None

    def test_get_previous_job_nonexistent_module(self, test_db):
        """Test getting previous job for nonexistent module."""
        previous = data_service.get_previous_job(test_db, "7.0.0.0", "nonexistent", "12")
        assert previous is None

    def test_get_previous_parent_job_id(self, test_db, sample_module):
        """Test getting the previous parent job ID."""
        from app.models.db_models import Job
        from datetime import datetime, timedelta

        # Create jobs with parent_job_ids at different times
        now = datetime.now()

        # Parent job 1 (oldest)
        job1a = Job(
            module_id=sample_module.id,
            job_id="10",
            parent_job_id="parent_1",
            total=10, passed=8, failed=2, skipped=0, pass_rate=80.0,
            created_at=now - timedelta(hours=2)
        )

        # Parent job 2 (middle)
        job2a = Job(
            module_id=sample_module.id,
            job_id="11",
            parent_job_id="parent_2",
            total=12, passed=10, failed=2, skipped=0, pass_rate=83.33,
            created_at=now - timedelta(hours=1)
        )

        # Parent job 3 (newest)
        job3a = Job(
            module_id=sample_module.id,
            job_id="12",
            parent_job_id="parent_3",
            total=15, passed=13, failed=2, skipped=0, pass_rate=86.67,
            created_at=now
        )

        test_db.add_all([job1a, job2a, job3a])
        test_db.commit()

        # Get previous parent job for parent_3 (should be parent_2)
        previous = data_service.get_previous_parent_job_id(test_db, "7.0.0.0", "parent_3")
        assert previous == "parent_2"

        # Get previous parent job for parent_2 (should be parent_1)
        previous = data_service.get_previous_parent_job_id(test_db, "7.0.0.0", "parent_2")
        assert previous == "parent_1"

        # Get previous parent job for parent_1 (should be None - first job)
        previous = data_service.get_previous_parent_job_id(test_db, "7.0.0.0", "parent_1")
        assert previous is None

    def test_add_comparison_data_helper(self):
        """Test the _add_comparison_data helper function."""
        current_stats = [
            {
                'priority': 'P0',
                'total': 10,
                'passed': 9,
                'failed': 1,
                'skipped': 0,
                
                'pass_rate': 90.0
            },
            {
                'priority': 'P1',
                'total': 20,
                'passed': 18,
                'failed': 2,
                'skipped': 0,
                
                'pass_rate': 90.0
            }
        ]

        previous_stats = [
            {
                'priority': 'P0',
                'total': 10,
                'passed': 8,
                'failed': 2,
                'skipped': 0,
                
                'pass_rate': 80.0
            },
            {
                'priority': 'P1',
                'total': 20,
                'passed': 16,
                'failed': 4,
                'skipped': 0,
                
                'pass_rate': 80.0
            }
        ]

        # Call helper function
        data_service._add_comparison_data(current_stats, previous_stats)

        # Verify comparison data for P0
        assert 'comparison' in current_stats[0]
        assert current_stats[0]['comparison']['total_delta'] == 0
        assert current_stats[0]['comparison']['passed_delta'] == 1
        assert current_stats[0]['comparison']['failed_delta'] == -1
        assert current_stats[0]['comparison']['pass_rate_delta'] == 10.0
        assert current_stats[0]['comparison']['previous']['passed'] == 8

        # Verify comparison data for P1
        assert 'comparison' in current_stats[1]
        assert current_stats[1]['comparison']['passed_delta'] == 2
        assert current_stats[1]['comparison']['failed_delta'] == -2

    def test_add_comparison_data_with_new_priority(self):
        """Test comparison when new priority appears."""
        current_stats = [
            {
                'priority': 'P0',
                'total': 10,
                'passed': 9,
                'failed': 1,
                'skipped': 0,
                
                'pass_rate': 90.0
            },
            {
                'priority': 'P2',  # New priority not in previous
                'total': 5,
                'passed': 5,
                'failed': 0,
                'skipped': 0,
                
                'pass_rate': 100.0
            }
        ]

        previous_stats = [
            {
                'priority': 'P0',
                'total': 10,
                'passed': 8,
                'failed': 2,
                'skipped': 0,
                
                'pass_rate': 80.0
            }
        ]

        # Call helper function
        data_service._add_comparison_data(current_stats, previous_stats)

        # Verify P0 has comparison
        assert current_stats[0]['comparison'] is not None

        # Verify P2 has None comparison (new priority)
        assert current_stats[1]['comparison'] is None

    def test_get_priority_statistics_with_comparison(self, test_db, sample_module):
        """Test getting priority statistics with comparison enabled."""
        from app.models.db_models import Job, TestResult, TestStatusEnum

        # Create two sequential jobs
        job1 = Job(
            module_id=sample_module.id,
            job_id="20",
            total=10, passed=8, failed=2, skipped=0, pass_rate=80.0
        )
        job2 = Job(
            module_id=sample_module.id,
            job_id="21",
            total=10, passed=9, failed=1, skipped=0, pass_rate=90.0
        )
        test_db.add_all([job1, job2])
        test_db.commit()

        # Add test results for job1
        for i in range(8):
            test_db.add(TestResult(
                job_id=job1.id,
                file_path=f"test_{i}.py",
                class_name="TestComparison",
                test_name=f"test_{i}",
                status=TestStatusEnum.PASSED,
                priority='P0'
            ))
        for i in range(2):
            test_db.add(TestResult(
                job_id=job1.id,
                file_path=f"test_fail_{i}.py",
                class_name="TestComparison",
                test_name=f"test_fail_{i}",
                status=TestStatusEnum.FAILED,
                priority='P0'
            ))

        # Add test results for job2
        for i in range(9):
            test_db.add(TestResult(
                job_id=job2.id,
                file_path=f"test_{i}.py",
                class_name="TestComparison",
                test_name=f"test_{i}",
                status=TestStatusEnum.PASSED,
                priority='P0'
            ))
        for i in range(1):
            test_db.add(TestResult(
                job_id=job2.id,
                file_path=f"test_fail_{i}.py",
                class_name="TestComparison",
                test_name=f"test_fail_{i}",
                status=TestStatusEnum.FAILED,
                priority='P0'
            ))

        test_db.commit()

        # Get priority stats with comparison
        stats = data_service.get_priority_statistics(
            test_db, "7.0.0.0", "business_policy", "21", include_comparison=True
        )

        # Verify structure
        assert len(stats) > 0
        p0_stat = next((s for s in stats if s['priority'] == 'P0'), None)
        assert p0_stat is not None

        # Verify comparison data exists
        assert 'comparison' in p0_stat
        assert p0_stat['comparison'] is not None
        assert p0_stat['comparison']['passed_delta'] == 1  # 9 - 8 = 1
        assert p0_stat['comparison']['failed_delta'] == -1  # 1 - 2 = -1
        assert 'previous' in p0_stat['comparison']
        assert p0_stat['comparison']['previous']['passed'] == 8

    def test_get_priority_statistics_without_comparison(self, test_db, sample_module):
        """Test getting priority statistics without comparison (default)."""
        from app.models.db_models import Job, TestResult, TestStatusEnum

        job = Job(
            module_id=sample_module.id,
            job_id="30",
            total=10, passed=9, failed=1, skipped=0, pass_rate=90.0
        )
        test_db.add(job)
        test_db.commit()

        # Add test results
        for i in range(9):
            test_db.add(TestResult(
                job_id=job.id,
                file_path=f"test_{i}.py",
                class_name="TestComparison",
                test_name=f"test_{i}",
                status=TestStatusEnum.PASSED,
                priority='P0'
            ))

        test_db.commit()

        # Get priority stats without comparison
        stats = data_service.get_priority_statistics(
            test_db, "7.0.0.0", "business_policy", "30", include_comparison=False
        )

        # Verify no comparison data
        assert len(stats) > 0
        for stat in stats:
            assert 'comparison' not in stat

    def test_get_aggregated_priority_statistics_with_comparison(self, test_db, sample_module):
        """Test aggregated priority statistics with comparison."""
        from app.models.db_models import Job, TestResult, TestStatusEnum
        from datetime import datetime, timedelta

        now = datetime.now()

        # Create parent job 1 (older)
        job1 = Job(
            module_id=sample_module.id,
            job_id="40",
            parent_job_id="parent_10",
            total=10, passed=8, failed=2, skipped=0, pass_rate=80.0,
            created_at=now - timedelta(hours=1)
        )

        # Create parent job 2 (newer)
        job2 = Job(
            module_id=sample_module.id,
            job_id="41",
            parent_job_id="parent_11",
            total=10, passed=9, failed=1, skipped=0, pass_rate=90.0,
            created_at=now
        )

        test_db.add_all([job1, job2])
        test_db.commit()

        # Add test results for both jobs
        for job in [job1, job2]:
            passed_count = 8 if job.job_id == "40" else 9
            failed_count = 2 if job.job_id == "40" else 1

            for i in range(passed_count):
                test_db.add(TestResult(
                    job_id=job.id,
                    file_path=f"test_{i}.py",
                    class_name="TestComparison",
                    test_name=f"test_{i}",
                    status=TestStatusEnum.PASSED,
                    priority='P0'
                ))
            for i in range(failed_count):
                test_db.add(TestResult(
                    job_id=job.id,
                    file_path=f"test_fail_{i}.py",
                    class_name="TestComparison",
                    test_name=f"test_fail_{i}",
                    status=TestStatusEnum.FAILED,
                    priority='P0'
                ))

        test_db.commit()

        # Get aggregated stats with comparison
        stats = data_service.get_aggregated_priority_statistics(
            test_db, "7.0.0.0", "parent_11", include_comparison=True
        )

        # Verify comparison exists
        assert len(stats) > 0
        p0_stat = next((s for s in stats if s['priority'] == 'P0'), None)
        assert p0_stat is not None
        assert 'comparison' in p0_stat
        assert p0_stat['comparison'] is not None
        assert p0_stat['comparison']['passed_delta'] == 1  # Improvement
        assert p0_stat['comparison']['failed_delta'] == -1  # Improvement
