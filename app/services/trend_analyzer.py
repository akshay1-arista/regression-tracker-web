"""
Trend analyzer service for calculating test trends from database data.
Adapts the existing analyzer.py logic to work with SQLAlchemy models.
"""
import logging
from typing import List, Dict, Optional
from collections import defaultdict
from sqlalchemy.orm import Session, joinedload

from app.models.db_models import TestResult, TestStatusEnum, Job, Module
from app.services.data_service import get_module
from app.constants import (
    FLAKY_DETECTION_JOB_WINDOW,
    TEST_STATUS_PASSED,
    TEST_STATUS_FAILED
)

logger = logging.getLogger(__name__)


class TestTrend:
    """
    Tracks a single test's status across multiple jobs.
    Matches the existing models.py TestTrend dataclass.
    """

    def __init__(
        self,
        test_key: str,
        file_path: str,
        class_name: str,
        test_name: str,
        priority: Optional[str] = None,
        topology_metadata: Optional[str] = None,
        test_state: Optional[str] = None
    ):
        self.test_key = test_key
        self.file_path = file_path
        self.class_name = class_name
        self.test_name = test_name
        self.priority = priority  # P0, P1, P2, P3, or None for UNKNOWN
        self.topology_metadata = topology_metadata  # Design topology from metadata CSV
        self.test_state = test_state  # Test state from metadata CSV (PROD, STAGING, etc.)
        self.results_by_job: Dict[str, TestStatusEnum] = {}
        self.rerun_info_by_job: Dict[str, Dict[str, bool]] = {}
        self.job_modules: Dict[str, str] = {}  # job_id -> Jenkins module name
        self.parent_job_ids: Dict[str, str] = {}  # job_id -> parent_job_id (for frontend filtering)

    @property
    def is_regression(self) -> bool:
        """
        Check if test is a regression (was passing, now continuously failing).

        A test is a regression if:
        - Has at least one PASSED status in history
        - Has at least 2 consecutive FAILures at the end of the sequence
        - Does NOT have any PASS after the first FAIL (once failing, stays failing)

        Examples:
        - PASS, FAIL, FAIL, FAIL, FAIL = Regression (passed once, then failed continuously)
        - PASS, PASS, FAIL, FAIL, FAIL = Regression (passed twice, then failed continuously)
        - PASS, FAIL, PASS, FAIL, FAIL = NOT Regression (passed again after failing = flaky)
        """
        if not self.results_by_job:
            return False

        statuses = list(self.results_by_job.values())

        # Must have at least one PASS
        if TestStatusEnum.PASSED not in statuses:
            return False

        sorted_jobs = sorted(self.results_by_job.keys(), key=lambda x: int(x))

        if len(sorted_jobs) < 2:
            return False

        # Count consecutive failures from the end
        consecutive_failures = 0
        for job in reversed(sorted_jobs):
            if self.results_by_job[job] == TestStatusEnum.FAILED:
                consecutive_failures += 1
            else:
                break

        # Must have at least 2 consecutive failures at the end
        if consecutive_failures < 2:
            return False

        # Check if there's any PASS after the first FAIL
        # If there is, it's flaky (not regression)
        first_fail_index = None
        for i, job in enumerate(sorted_jobs):
            if self.results_by_job[job] == TestStatusEnum.FAILED:
                first_fail_index = i
                break

        if first_fail_index is None:
            return False

        # Check if there's any PASS after the first failure
        for i in range(first_fail_index + 1, len(sorted_jobs)):
            if self.results_by_job[sorted_jobs[i]] == TestStatusEnum.PASSED:
                return False  # Has PASS after FAIL = flaky, not regression

        return True

    @property
    def is_flaky(self) -> bool:
        """
        Check if test has inconsistent results (flaky).

        A test is flaky if:
        - Has both PASSED and FAILED statuses
        - The failure(s) are NOT only in the latest job
        - Is NOT a regression (not continuously failing)

        Examples:
        - PASS, FAIL, PASS = flaky (failure not in latest)
        - PASS, PASS, FAIL = new failure (failure only in latest)
        - PASS, FAIL, PASS, FAIL, FAIL = flaky (has alternating pattern, not continuously failing)
        - PASS, FAIL, FAIL, FAIL, FAIL = regression (not flaky)
        """
        if not self.results_by_job:
            return False

        statuses = set(self.results_by_job.values())
        has_pass = TestStatusEnum.PASSED in statuses
        has_fail = TestStatusEnum.FAILED in statuses

        # Must have both passes and failures
        if not (has_pass and has_fail):
            return False

        # Check if all failures are only in the latest job
        sorted_jobs = sorted(self.results_by_job.keys(), key=lambda x: int(x))
        latest_job = sorted_jobs[-1]

        # Find all jobs with failures
        failed_jobs = [job for job, status in self.results_by_job.items()
                       if status == TestStatusEnum.FAILED]

        # If only failure is in the latest job, it's a new failure (not flaky)
        if len(failed_jobs) == 1 and failed_jobs[0] == latest_job:
            return False

        # If it's a regression, it's not flaky
        if self.is_regression:
            return False

        return True

    @property
    def is_always_failing(self) -> bool:
        """Check if test always fails across all jobs."""
        if not self.results_by_job:
            return False
        return all(
            s == TestStatusEnum.FAILED
            for s in self.results_by_job.values()
        )

    @property
    def is_always_passing(self) -> bool:
        """Check if test always passes across all jobs."""
        if not self.results_by_job:
            return False
        return all(
            s == TestStatusEnum.PASSED
            for s in self.results_by_job.values()
        )

    @property
    def latest_status(self) -> Optional[TestStatusEnum]:
        """Get the most recent status (highest job number)."""
        if not self.results_by_job:
            return None
        latest_job = max(self.results_by_job.keys(), key=lambda x: int(x))
        return self.results_by_job[latest_job]

    def is_new_failure(self, job_ids: List[str]) -> bool:
        """
        Check if this test is a new failure (strict definition).

        A new failure is a test that:
        - PASSED in the immediate previous job
        - AND FAILED in the current/latest job

        This strict definition helps identify tests that just started failing
        in the most recent run, excluding tests that have been failing for
        multiple consecutive runs.

        Args:
            job_ids: List of job IDs where this test has results, sorted chronologically

        Returns:
            True if test passed in immediate previous job and failed in latest job
        """
        if len(job_ids) < 2:
            return False

        sorted_jobs = sorted(job_ids, key=lambda x: int(x))

        # Current run = latest job where test has results
        current_job = sorted_jobs[-1]
        # Previous run = second-to-latest job where test has results
        previous_job = sorted_jobs[-2]

        current_status = self.results_by_job.get(current_job)
        previous_status = self.results_by_job.get(previous_job)

        # New failure: PASSED in previous, FAILED in current
        return (previous_status == TestStatusEnum.PASSED and
                current_status == TestStatusEnum.FAILED)


def calculate_test_trends(
    db: Session,
    release_name: str,
    module_name: str,
    use_testcase_module: bool = False,
    job_limit: Optional[int] = None
) -> List[TestTrend]:
    """
    Calculate trends for each test across jobs in a module.

    Uses eager loading to fetch jobs and test_results in a single query,
    avoiding N+1 query problem.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name (Jenkins module) or testcase_module (path-based)
        use_testcase_module: If True, filter by testcase_module (path-based) instead of Jenkins module
        job_limit: If provided, limit analysis to jobs from most recent N parent jobs.
                   This includes ALL sub-jobs from those N parent jobs, ensuring tests
                   that ran in older sub-jobs are still visible if the parent job is
                   within the limit window.

    Returns:
        List of TestTrend objects tracking each test across jobs
    """
    if use_testcase_module:
        # Path-based module filtering: Get jobs that have tests for this testcase_module
        from app.services.data_service import get_jobs_for_testcase_module
        jobs = get_jobs_for_testcase_module(db, release_name, module_name)

        if not jobs:
            return []

        # Sort jobs by job_id descending (most recent first) for consistent ordering
        jobs.sort(key=lambda j: int(j.job_id), reverse=True)

        # Apply job limit based on parent_job_id (not individual module jobs)
        # This ensures we include ALL sub-jobs from the last N parent jobs
        if job_limit is not None:
            # Get unique parent_job_ids (use job_id if parent_job_id is None)
            parent_job_ids = set()
            for job in jobs:
                parent_id = job.parent_job_id if job.parent_job_id else job.job_id
                parent_job_ids.add(parent_id)

            # Sort parent_job_ids and take the last N
            sorted_parent_ids = sorted(parent_job_ids, key=lambda x: int(x), reverse=True)
            limited_parent_ids = set(sorted_parent_ids[:job_limit])

            # Filter jobs to only those belonging to the limited parent jobs
            jobs = [
                job for job in jobs
                if (job.parent_job_id if job.parent_job_id else job.job_id) in limited_parent_ids
            ]

        # Collect all unique tests and their results per job
        # Filter to only tests matching this testcase_module
        trends_dict: Dict[str, TestTrend] = {}

        for job in jobs:
            job_id = job.job_id
            # Get Jenkins module name from job (for correct job URLs)
            jenkins_module = job.module.name
            # Get parent_job_id (use job_id if parent_job_id is None)
            parent_job_id = job.parent_job_id if job.parent_job_id else job.job_id

            # Query test results for this job that match the testcase_module
            results = db.query(TestResult).filter(
                TestResult.job_id == job.id,
                TestResult.testcase_module == module_name
            ).all()

            for result in results:
                test_key = result.test_key

                if test_key not in trends_dict:
                    trends_dict[test_key] = TestTrend(
                        test_key=test_key,
                        file_path=result.file_path,
                        class_name=result.class_name,
                        test_name=result.test_name,
                        priority=result.priority,
                        topology_metadata=result.topology_metadata
                    )

                trends_dict[test_key].results_by_job[job_id] = result.status
                trends_dict[test_key].rerun_info_by_job[job_id] = {
                    'was_rerun': result.was_rerun,
                    'rerun_still_failed': result.rerun_still_failed
                }
                trends_dict[test_key].job_modules[job_id] = jenkins_module
                trends_dict[test_key].parent_job_ids[job_id] = parent_job_id

        # Enrich trends with test_state from TestcaseMetadata
        if trends_dict:
            from app.models.db_models import TestcaseMetadata
            from app.services.testcase_metadata_service import _normalize_test_name_sql

            # Get unique NORMALIZED test names from trends (for parameterized tests)
            test_names = set()
            for trend in trends_dict.values():
                # Normalize test name for parameterized tests (e.g., test_foo[param] -> test_foo)
                normalized_name = trend.test_name.split('[')[0] if '[' in trend.test_name else trend.test_name
                test_names.add(normalized_name)

            # Query TestcaseMetadata for test_state using normalized names
            metadata_records = db.query(TestcaseMetadata).filter(
                TestcaseMetadata.testcase_name.in_(test_names)
            ).all()

            # Create lookup dict: normalized_test_name -> test_state
            test_state_lookup = {record.testcase_name: record.test_state for record in metadata_records}

            # Update trends with test_state
            for trend in trends_dict.values():
                # Normalize test name for lookup
                normalized_name = trend.test_name.split('[')[0] if '[' in trend.test_name else trend.test_name
                trend.test_state = test_state_lookup.get(normalized_name)

        return list(trends_dict.values())
    else:
        # Jenkins module filtering (original behavior)
        # Get module
        module = get_module(db, release_name, module_name)
        if not module:
            return []

        # Fetch all jobs with their test_results in a single query using eager loading
        jobs = db.query(Job)\
            .options(joinedload(Job.test_results))\
            .filter(Job.module_id == module.id)\
            .all()

        if not jobs:
            return []

        # Sort jobs by job_id descending (most recent first) for consistent ordering
        jobs.sort(key=lambda j: int(j.job_id), reverse=True)

        # Apply job limit based on parent_job_id (not individual module jobs)
        # This ensures we include ALL sub-jobs from the last N parent jobs
        if job_limit is not None:
            # Get unique parent_job_ids (use job_id if parent_job_id is None)
            parent_job_ids = set()
            for job in jobs:
                parent_id = job.parent_job_id if job.parent_job_id else job.job_id
                parent_job_ids.add(parent_id)

            # Sort parent_job_ids and take the last N
            sorted_parent_ids = sorted(parent_job_ids, key=lambda x: int(x), reverse=True)
            limited_parent_ids = set(sorted_parent_ids[:job_limit])

            # Filter jobs to only those belonging to the limited parent jobs
            jobs = [
                job for job in jobs
                if (job.parent_job_id if job.parent_job_id else job.job_id) in limited_parent_ids
            ]

        # Collect all unique tests and their results per job
        trends_dict: Dict[str, TestTrend] = {}

        for job in jobs:
            job_id = job.job_id
            # Get Jenkins module name from job (for correct job URLs)
            jenkins_module = job.module.name
            # Get parent_job_id (use job_id if parent_job_id is None)
            parent_job_id = job.parent_job_id if job.parent_job_id else job.job_id

            # Access job.test_results directly (already loaded via joinedload)
            for result in job.test_results:
                test_key = result.test_key

                if test_key not in trends_dict:
                    trends_dict[test_key] = TestTrend(
                        test_key=test_key,
                        file_path=result.file_path,
                        class_name=result.class_name,
                        test_name=result.test_name,
                        priority=result.priority,  # Include priority from test result
                        topology_metadata=result.topology_metadata  # Include design topology
                    )

                trends_dict[test_key].results_by_job[job_id] = result.status
                # Store rerun info for this job
                trends_dict[test_key].rerun_info_by_job[job_id] = {
                    'was_rerun': result.was_rerun,
                    'rerun_still_failed': result.rerun_still_failed
                }
                trends_dict[test_key].job_modules[job_id] = jenkins_module
                trends_dict[test_key].parent_job_ids[job_id] = parent_job_id

        # Enrich trends with test_state from TestcaseMetadata
        if trends_dict:
            from app.models.db_models import TestcaseMetadata

            # Get unique NORMALIZED test names from trends (for parameterized tests)
            test_names = set()
            for trend in trends_dict.values():
                # Normalize test name for parameterized tests (e.g., test_foo[param] -> test_foo)
                normalized_name = trend.test_name.split('[')[0] if '[' in trend.test_name else trend.test_name
                test_names.add(normalized_name)

            # Query TestcaseMetadata for test_state using normalized names
            metadata_records = db.query(TestcaseMetadata).filter(
                TestcaseMetadata.testcase_name.in_(test_names)
            ).all()

            # Create lookup dict: normalized_test_name -> test_state
            test_state_lookup = {record.testcase_name: record.test_state for record in metadata_records}

            # Update trends with test_state
            for trend in trends_dict.values():
                # Normalize test name for lookup
                normalized_name = trend.test_name.split('[')[0] if '[' in trend.test_name else trend.test_name
                trend.test_state = test_state_lookup.get(normalized_name)

        return list(trends_dict.values())


def get_trends_by_class(test_trends: List[TestTrend]) -> Dict[str, List[TestTrend]]:
    """
    Group test trends by class name.

    Args:
        test_trends: List of test trends

    Returns:
        Dict mapping class_name -> list of test trends
    """
    by_class: Dict[str, List[TestTrend]] = defaultdict(list)

    for trend in test_trends:
        by_class[trend.class_name].append(trend)

    # Sort trends within each class by test name
    for class_name in by_class:
        by_class[class_name].sort(key=lambda t: t.test_name)

    return dict(by_class)


def get_failure_summary(
    db: Session,
    release_name: str,
    module_name: str
) -> Dict[str, any]:
    """
    Get summary of failures for a module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name

    Returns:
        Dict with failure statistics
    """
    trends = calculate_test_trends(db, release_name, module_name)

    # Get job IDs from trends (already loaded)
    job_ids = list(set(
        job_id for trend in trends for job_id in trend.results_by_job.keys()
    ))

    # Categorize tests
    flaky_tests = [t for t in trends if t.is_flaky]
    always_failing = [t for t in trends if t.is_always_failing]
    new_failures = [t for t in trends if t.is_new_failure(job_ids)]

    return {
        'total_unique_tests': len(trends),
        'flaky_count': len(flaky_tests),
        'always_failing_count': len(always_failing),
        'new_failures_count': len(new_failures),
        'flaky_tests': flaky_tests,
        'always_failing_tests': always_failing,
        'new_failures': new_failures
    }


def get_dashboard_failure_summary(
    db: Session,
    release_name: str,
    module_name: str,
    use_testcase_module: bool = False
) -> Dict[str, any]:
    """
    Get failure summary for dashboard with priority breakdown.

    - Flaky tests: Based on last 5 parent jobs (matching trend view)
    - New failures: Based on current vs previous run

    Note: job_limit is applied to parent_job_id, so ALL sub-jobs from the
    last 5 parent jobs are included in the analysis.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name (Jenkins or testcase_module)
        use_testcase_module: If True, use testcase_module filtering

    Returns:
        Dict with failure statistics broken down by priority
    """
    # Calculate trends using last 5 parent jobs for flaky detection (matching trend view)
    trends = calculate_test_trends(
        db, release_name, module_name,
        use_testcase_module=use_testcase_module,
        job_limit=FLAKY_DETECTION_JOB_WINDOW  # Use last 5 parent jobs to match trend view
    )

    if not trends:
        return {
            'flaky_by_priority': {},
            'new_failures_by_priority': {},
            'flaky_test_keys': [],
            'total_flaky': 0,
            'total_new_failures': 0
        }

    # Get job IDs from trends (limited to last 5 jobs)
    job_ids = sorted(
        list(set(job_id for trend in trends for job_id in trend.results_by_job.keys())),
        key=lambda x: int(x)
    )

    # Categorize tests
    flaky_tests = [t for t in trends if t.is_flaky]
    new_failures = [t for t in trends if t.is_new_failure(job_ids)]

    # Filter flaky tests that PASSED in their own latest job
    # Each test may have run in different jobs, so use each test's own latest_status
    # instead of a global latest_job_id
    passed_flaky_tests = []
    for test in flaky_tests:
        if test.latest_status == TestStatusEnum.PASSED:
            passed_flaky_tests.append(test)

    # Count by priority
    def count_by_priority(test_list):
        from collections import defaultdict
        counts = defaultdict(int)
        for test in test_list:
            priority = test.priority or 'UNKNOWN'
            counts[priority] += 1
        return dict(counts)

    return {
        'flaky_by_priority': count_by_priority(flaky_tests),  # All flaky (for reference)
        'passed_flaky_by_priority': count_by_priority(passed_flaky_tests),  # Passed flaky (for table)
        'new_failures_by_priority': count_by_priority(new_failures),
        'flaky_test_keys': [t.test_key for t in flaky_tests],
        'total_flaky': len(flaky_tests),  # All flaky (for checkbox)
        'total_passed_flaky': len(passed_flaky_tests),  # Passed flaky (for exclusion)
        'total_new_failures': len(new_failures)
    }


def filter_trends(
    trends: List[TestTrend],
    flaky_only: bool = False,
    regression_only: bool = False,
    always_failing_only: bool = False,
    new_failures_only: bool = False,
    failed_only: bool = False,
    priorities: Optional[List[str]] = None,
    job_ids: Optional[List[str]] = None
) -> List[TestTrend]:
    """
    Filter test trends based on criteria.

    Filter logic:
    - failed_only: Uses AND logic (narrows down results) - filters for tests where latest status is FAILED
    - Other status filters (flaky, regression, always_failing, new_failures): Use OR logic among themselves
    - priorities: Uses AND logic with all other filters

    Example combinations:
    - failed_only=True, flaky_only=True: Tests that are flaky AND latest status is FAILED
    - flaky_only=True, regression_only=True: Tests that are flaky OR regression (no failed_only)
    - failed_only=True, priorities=['P0']: P0 tests where latest status is FAILED

    Args:
        trends: List of test trends
        flaky_only: If True, include flaky tests
        regression_only: If True, include regression tests
        always_failing_only: If True, include always-failing tests
        new_failures_only: If True, include new failures
        failed_only: If True, only include tests where latest status is FAILED (AND filter)
        priorities: Optional list of priorities to filter by (e.g., ['P0', 'P1', 'UNKNOWN'])
        job_ids: List of job IDs (required for new_failures_only)

    Returns:
        Filtered list of test trends
    """
    # Start with all trends
    filtered = trends

    # Apply failed_only as AND filter first (narrows down the result set)
    # Only include tests where the latest status is FAILED (not just any failure in history)
    if failed_only:
        from app.models.db_models import TestStatusEnum
        filtered = [
            t for t in filtered
            if t.latest_status == TestStatusEnum.FAILED
        ]

    # Collect other status filter predicates (OR logic among themselves)
    status_filters = []

    if flaky_only:
        status_filters.append(lambda t: t.is_flaky)

    if regression_only:
        status_filters.append(lambda t: t.is_regression)

    if always_failing_only:
        status_filters.append(lambda t: t.is_always_failing)

    if new_failures_only:
        # Note: We don't use the job_ids parameter anymore - each test uses its own job list
        # This ensures we only check jobs where the test actually has results
        status_filters.append(lambda t: t.is_new_failure(list(t.results_by_job.keys())))

    # Apply status filters with OR logic (on already failed-filtered results if failed_only=True)
    if status_filters:
        filtered = [t for t in filtered if any(f(t) for f in status_filters)]

    # Apply priority filter (AND logic with all previous filters)
    if priorities:
        # Filter by priority, treating None as 'UNKNOWN'
        filtered = [
            t for t in filtered
            if (t.priority in priorities) or ('UNKNOWN' in priorities and t.priority is None)
        ]

    return filtered
