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
        priority: Optional[str] = None
    ):
        self.test_key = test_key
        self.file_path = file_path
        self.class_name = class_name
        self.test_name = test_name
        self.priority = priority  # P0, P1, P2, P3, or None for UNKNOWN
        self.results_by_job: Dict[str, TestStatusEnum] = {}
        self.rerun_info_by_job: Dict[str, Dict[str, bool]] = {}
        self.job_modules: Dict[str, str] = {}  # job_id -> Jenkins module name

    @property
    def is_flaky(self) -> bool:
        """Check if test has inconsistent results (both pass and fail)."""
        statuses = set(self.results_by_job.values())
        has_pass = TestStatusEnum.PASSED in statuses
        has_fail = TestStatusEnum.FAILED in statuses
        return has_pass and has_fail

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
        Check if this test is a new failure.
        A new failure is a test that PASSED in the previous run but FAILED in the current run.

        Args:
            job_ids: List of job IDs, should be sorted chronologically

        Returns:
            True if test passed in previous run and failed in current run
        """
        if len(job_ids) < 2:
            return False

        sorted_jobs = sorted(job_ids, key=lambda x: int(x))

        # Current run = latest job
        current_job = sorted_jobs[-1]
        # Previous run = second-to-latest job
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
        job_limit: If provided, limit analysis to most recent N jobs (for flaky detection window)

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

        # Apply job limit if specified (for flaky detection window)
        if job_limit is not None:
            jobs = jobs[:job_limit]

        # Collect all unique tests and their results per job
        # Filter to only tests matching this testcase_module
        trends_dict: Dict[str, TestTrend] = {}

        for job in jobs:
            job_id = job.job_id
            # Get Jenkins module name from job (for correct job URLs)
            jenkins_module = job.module.name

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
                        priority=result.priority
                    )

                trends_dict[test_key].results_by_job[job_id] = result.status
                trends_dict[test_key].rerun_info_by_job[job_id] = {
                    'was_rerun': result.was_rerun,
                    'rerun_still_failed': result.rerun_still_failed
                }
                trends_dict[test_key].job_modules[job_id] = jenkins_module

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

        # Apply job limit if specified (for flaky detection window)
        if job_limit is not None:
            jobs = jobs[:job_limit]

        # Collect all unique tests and their results per job
        trends_dict: Dict[str, TestTrend] = {}

        for job in jobs:
            job_id = job.job_id
            # Get Jenkins module name from job (for correct job URLs)
            jenkins_module = job.module.name

            # Access job.test_results directly (already loaded via joinedload)
            for result in job.test_results:
                test_key = result.test_key

                if test_key not in trends_dict:
                    trends_dict[test_key] = TestTrend(
                        test_key=test_key,
                        file_path=result.file_path,
                        class_name=result.class_name,
                        test_name=result.test_name,
                        priority=result.priority  # Include priority from test result
                    )

                trends_dict[test_key].results_by_job[job_id] = result.status
                # Store rerun info for this job
                trends_dict[test_key].rerun_info_by_job[job_id] = {
                    'was_rerun': result.was_rerun,
                    'rerun_still_failed': result.rerun_still_failed
                }
                trends_dict[test_key].job_modules[job_id] = jenkins_module

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

    - Flaky tests: Based on last 5 jobs only
    - New failures: Based on current vs previous run

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name (Jenkins or testcase_module)
        use_testcase_module: If True, use testcase_module filtering

    Returns:
        Dict with failure statistics broken down by priority
    """
    # Calculate trends limited to last 5 jobs for flaky detection
    trends = calculate_test_trends(
        db, release_name, module_name,
        use_testcase_module=use_testcase_module,
        job_limit=5
    )

    if not trends:
        return {
            'flaky_by_priority': {},
            'new_failures_by_priority': {},
            'flaky_test_keys': [],
            'total_flaky': 0,
            'total_new_failures': 0
        }

    # Get job IDs from trends (already limited to last 5)
    job_ids = sorted(
        list(set(job_id for trend in trends for job_id in trend.results_by_job.keys())),
        key=lambda x: int(x)
    )

    # Categorize tests
    flaky_tests = [t for t in trends if t.is_flaky]
    new_failures = [t for t in trends if t.is_new_failure(job_ids)]

    # Get latest job ID to filter for passed flaky tests
    latest_job_id = job_ids[-1] if job_ids else None

    # Filter flaky tests that PASSED in the latest job
    passed_flaky_tests = []
    if latest_job_id:
        for test in flaky_tests:
            latest_status = test.results_by_job.get(latest_job_id)
            if latest_status == TestStatusEnum.PASSED:
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
    always_failing_only: bool = False,
    new_failures_only: bool = False,
    priorities: Optional[List[str]] = None,
    job_ids: Optional[List[str]] = None
) -> List[TestTrend]:
    """
    Filter test trends based on criteria.

    Status filters (flaky, always_failing, new_failures) use OR logic.
    Priority filter uses AND logic with status filters.

    Args:
        trends: List of test trends
        flaky_only: If True, include flaky tests
        always_failing_only: If True, include always-failing tests
        new_failures_only: If True, include new failures
        priorities: Optional list of priorities to filter by (e.g., ['P0', 'P1', 'UNKNOWN'])
        job_ids: List of job IDs (required for new_failures_only)

    Returns:
        Filtered list of test trends
    """
    # Collect status filter predicates (OR logic)
    status_filters = []

    if flaky_only:
        status_filters.append(lambda t: t.is_flaky)

    if always_failing_only:
        status_filters.append(lambda t: t.is_always_failing)

    if new_failures_only:
        if not job_ids:
            logger.warning("new_failures_only requires job_ids parameter")
            return []
        status_filters.append(lambda t: t.is_new_failure(job_ids))

    # Apply status filters with OR logic
    if status_filters:
        filtered = [t for t in trends if any(f(t) for f in status_filters)]
    else:
        filtered = trends

    # Apply priority filter (AND logic with status filters)
    if priorities:
        # Filter by priority, treating None as 'UNKNOWN'
        filtered = [
            t for t in filtered
            if (t.priority in priorities) or ('UNKNOWN' in priorities and t.priority is None)
        ]

    return filtered
