"""
Data models for Regression Tracker.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class TestStatus(Enum):
    """Test execution status.

    Note: ERROR is kept for parser compatibility (can read from Jenkins XML),
    but is automatically converted to FAILED.
    """
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"  # Kept for parser compatibility, converted to FAILED

    @classmethod
    def from_string(cls, status_str: str) -> "TestStatus":
        """Convert string to TestStatus enum.

        ERROR status is automatically converted to FAILED for consistency.
        """
        status_upper = status_str.upper().strip()
        try:
            status = cls(status_upper)
            # Convert ERROR to FAILED (hybrid approach)
            if status == cls.ERROR:
                return cls.FAILED
            return status
        except ValueError:
            # Default to FAILED for unknown statuses
            return cls.FAILED

    @property
    def priority(self) -> int:
        """
        Priority for status (lower is better).
        Used for determining worst status in a group.

        Note: ERROR is kept in mapping for backward compatibility,
        but since from_string() converts ERROR→FAILED, only FAILED
        priority will be used in practice.
        """
        priorities = {
            TestStatus.PASSED: 0,
            TestStatus.SKIPPED: 1,
            TestStatus.ERROR: 2,  # Kept for compatibility, not used (converted to FAILED)
            TestStatus.FAILED: 3,
        }
        return priorities.get(self, 99)


@dataclass
class TestResult:
    """Represents a single test execution result."""
    setup_ip: str
    status: TestStatus
    file_path: str
    class_name: str
    test_name: str
    topology: str
    order_index: int = 0  # Original order in the log file
    was_rerun: bool = False  # Whether this test was rerun
    rerun_still_failed: bool = False  # Rerun but still failed/error
    failure_message: str = ""  # Failure/error message from junit XML

    @property
    def test_key(self) -> str:
        """Unique identifier for this test (ignoring run-specific data)."""
        return f"{self.file_path}::{self.class_name}::{self.test_name}"

    @property
    def short_file_path(self) -> str:
        """Get just the filename without the full path."""
        return self.file_path.split("/")[-1] if "/" in self.file_path else self.file_path


@dataclass
class JobSummary:
    """Summary statistics for a single job run."""
    job_id: str
    release: str
    module: str
    total: int = 0
    passed: int = 0
    failed: int = 0  # Includes both FAILED and ERROR statuses
    skipped: int = 0

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage of all tests (including skipped)."""
        if self.total == 0:
            return 0.0
        return round((self.passed / self.total) * 100, 2)

    @property
    def fail_rate(self) -> float:
        """Calculate failure rate as percentage of all tests (including skipped)."""
        if self.total == 0:
            return 0.0
        return round((self.failed / self.total) * 100, 2)


@dataclass
class TestTrend:
    """Tracks a single test's status across multiple jobs."""
    test_key: str
    file_path: str
    class_name: str
    test_name: str
    results_by_job: Dict[str, TestStatus] = field(default_factory=dict)
    rerun_info_by_job: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    # rerun_info_by_job: {job_id: {'was_rerun': bool, 'rerun_still_failed': bool}}

    @property
    def is_flaky(self) -> bool:
        """Check if test has inconsistent results (both pass and fail)."""
        statuses = set(self.results_by_job.values())
        has_pass = TestStatus.PASSED in statuses
        has_fail = TestStatus.FAILED in statuses
        return has_pass and has_fail

    @property
    def is_always_failing(self) -> bool:
        """Check if test always fails across all jobs."""
        if not self.results_by_job:
            return False
        return all(
            s == TestStatus.FAILED
            for s in self.results_by_job.values()
        )

    @property
    def is_always_passing(self) -> bool:
        """Check if test always passes across all jobs."""
        if not self.results_by_job:
            return False
        return all(
            s == TestStatus.PASSED
            for s in self.results_by_job.values()
        )

    @property
    def latest_status(self) -> Optional[TestStatus]:
        """Get the most recent status (highest job number)."""
        if not self.results_by_job:
            return None
        latest_job = max(self.results_by_job.keys(), key=lambda x: int(x))
        return self.results_by_job[latest_job]

    def is_new_failure(self, job_ids: List[str]) -> bool:
        """
        Check if this test started failing recently.
        A new failure is a test that passed in earlier jobs but fails in the latest.
        """
        if len(job_ids) < 2:
            return False

        sorted_jobs = sorted(job_ids, key=lambda x: int(x))
        latest_job = sorted_jobs[-1]

        latest_status = self.results_by_job.get(latest_job)
        if latest_status != TestStatus.FAILED:
            return False

        # Check if it passed in any earlier job
        for job_id in sorted_jobs[:-1]:
            if self.results_by_job.get(job_id) == TestStatus.PASSED:
                return True

        return False


@dataclass
class ModuleData:
    """All data for a single module within a release."""
    release: str
    module: str
    job_summaries: List[JobSummary] = field(default_factory=list)
    test_trends: List[TestTrend] = field(default_factory=list)
    job_results: Dict[str, List[TestResult]] = field(default_factory=dict)

    @property
    def job_ids(self) -> List[str]:
        """Get sorted list of job IDs."""
        return sorted(self.job_results.keys(), key=lambda x: int(x))

    @property
    def total_tests(self) -> int:
        """Total unique tests across all jobs."""
        return len(self.test_trends)

    @property
    def flaky_tests(self) -> List[TestTrend]:
        """Get all flaky tests."""
        return [t for t in self.test_trends if t.is_flaky]

    @property
    def always_failing_tests(self) -> List[TestTrend]:
        """Get tests that always fail."""
        return [t for t in self.test_trends if t.is_always_failing]

    def new_failures(self) -> List[TestTrend]:
        """Get tests that are new failures."""
        return [t for t in self.test_trends if t.is_new_failure(self.job_ids)]


@dataclass
class ReportData:
    """Complete data structure for report generation."""
    modules: Dict[str, Dict[str, ModuleData]] = field(default_factory=dict)
    # Structure: {release: {module: ModuleData}}

    @property
    def releases(self) -> List[str]:
        """Get list of available releases."""
        return sorted(self.modules.keys())

    def get_modules_for_release(self, release: str) -> List[str]:
        """Get list of modules for a specific release."""
        if release not in self.modules:
            return []
        return sorted(self.modules[release].keys())

    def get_module_data(self, release: str, module: str) -> Optional[ModuleData]:
        """Get data for a specific release/module combination."""
        if release not in self.modules:
            return None
        return self.modules[release].get(module)
