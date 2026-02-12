"""
Data service layer for database queries.
Provides high-level query functions for API routers.
"""
import logging
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case, Integer

from app.models.db_models import (
    Release, Module, Job, TestResult, TestStatusEnum,
    BugMetadata, BugTestcaseMapping, TestcaseMetadata
)
from app.models.schemas import BugSchema
from app.utils.helpers import escape_like_pattern, validation_error
from app.constants import PRIORITY_ORDER

logger = logging.getLogger(__name__)

# Valid priority values
VALID_PRIORITIES = {'P0', 'P1', 'P2', 'P3', 'UNKNOWN'}

# Lookback limit for finding previous parent job IDs
# Limits memory usage and query complexity when searching for previous runs
PREVIOUS_PARENT_JOB_LOOKUP_LIMIT = 50


# ============================================================================
# Helper Functions
# ============================================================================

def parse_and_validate_priorities(priorities_str: Optional[str]) -> Optional[List[str]]:
    """
    Parse and validate comma-separated priority string.

    Centralizes priority parsing and validation logic for API endpoints.
    Raises validation_error if any invalid priorities are found.

    Args:
        priorities_str: Comma-separated priority string (e.g., "P0,P1,UNKNOWN")
                       or None

    Returns:
        List of uppercase priority strings, or None if input is None

    Raises:
        ValidationError: If any priorities are invalid

    Example:
        >>> parse_and_validate_priorities("p0, P1,unknown")
        ['P0', 'P1', 'UNKNOWN']
    """
    if not priorities_str:
        return None

    # Parse comma-separated values and normalize
    priority_list = [p.strip().upper() for p in priorities_str.split(',') if p.strip()]

    # Validate against known priorities
    invalid = [p for p in priority_list if p not in VALID_PRIORITIES]
    if invalid:
        raise validation_error(
            f"Invalid priorities: {', '.join(invalid)}. "
            f"Valid values: {', '.join(sorted(VALID_PRIORITIES))}"
        )

    return priority_list

def _add_comparison_data(
    current_stats: List[Dict[str, Any]],
    previous_stats: List[Dict[str, Any]]
) -> None:
    """
    Add comparison data to current priority statistics by comparing with previous stats.
    Modifies current_stats in place.

    Args:
        current_stats: List of current priority statistics dicts
        previous_stats: List of previous priority statistics dicts

    Side Effects:
        Adds 'comparison' key to each dict in current_stats with delta values
    """
    # Create lookup dict for previous stats by priority
    prev_lookup = {stat['priority']: stat for stat in previous_stats}

    # Add comparison data to each current stat
    for stat in current_stats:
        priority = stat['priority']
        if priority in prev_lookup:
            prev = prev_lookup[priority]

            # Calculate deltas for all metrics
            stat['comparison'] = {
                'total_delta': stat['total'] - prev['total'],
                'passed_delta': stat['passed'] - prev['passed'],
                'failed_delta': stat['failed'] - prev['failed'],
                'skipped_delta': stat['skipped'] - prev['skipped'],
                'pass_rate_delta': round(stat['pass_rate'] - prev['pass_rate'], 2),
                'previous': {
                    'total': prev['total'],
                    'passed': prev['passed'],
                    'failed': prev['failed'],
                    'skipped': prev['skipped'],
                    'pass_rate': prev['pass_rate']
                }
            }
        else:
            # Priority didn't exist in previous run (new tests added)
            stat['comparison'] = None


def _calculate_stats_for_jobs(
    db: Session,
    job_ids: List[int],
    testcase_module: Optional[str] = None
) -> Dict[int, Dict[str, Any]]:
    """
    Efficiently calculate statistics for multiple jobs in a single query.

    Uses database aggregation to avoid N+1 query problem when calculating
    stats for multiple jobs. Returns per-job statistics grouped by job_id.

    Args:
        db: Database session
        job_ids: List of Job.id values to calculate stats for
        testcase_module: Optional module filter (for path-based filtering)

    Returns:
        Dict mapping job_id (int) -> stats dict with:
        {
            'total': int,
            'passed': int,
            'failed': int,  # Includes both FAILED and ERROR statuses
            'skipped': int
        }
    """
    if not job_ids:
        return {}

    # Build aggregation query
    query = db.query(
        TestResult.job_id,
        func.count(TestResult.id).label('total'),
        func.sum(case((TestResult.status == TestStatusEnum.PASSED, 1), else_=0)).label('passed'),
        func.sum(case((TestResult.status == TestStatusEnum.FAILED, 1), else_=0)).label('failed'),
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped')
    ).filter(
        TestResult.job_id.in_(job_ids)
    )

    # Apply testcase_module filter if provided
    if testcase_module:
        query = query.filter(TestResult.testcase_module == testcase_module)

    # Group by job_id
    results = query.group_by(TestResult.job_id).all()

    # Build lookup dict
    stats_by_job = {}
    for row in results:
        stats_by_job[row.job_id] = {
            'total': row.total,
            'passed': row.passed,
            'failed': row.failed,  # Includes both FAILED and ERROR statuses
            'skipped': row.skipped
        }

    return stats_by_job


def _apply_priority_filter(query, priority_list: List[str]):
    """
    Apply priority filter to a SQLAlchemy query, handling UNKNOWN (NULL) priorities.

    This centralizes the priority filtering logic to avoid code duplication.
    Handles the special case where 'UNKNOWN' maps to NULL priority values.

    Args:
        query: SQLAlchemy query object
        priority_list: List of priority values (P0, P1, P2, P3, UNKNOWN)

    Returns:
        Modified query with priority filter applied

    Example:
        query = db.query(TestResult)
        query = _apply_priority_filter(query, ['P0', 'P1', 'UNKNOWN'])
    """
    if 'UNKNOWN' in priority_list:
        # Handle UNKNOWN (NULL) priority
        other_priorities = [p for p in priority_list if p != 'UNKNOWN']
        if other_priorities:
            # Both specific priorities AND NULL
            return query.filter(
                (TestResult.priority.in_(other_priorities)) |
                (TestResult.priority.is_(None))
            )
        else:
            # Only NULL priorities
            return query.filter(TestResult.priority.is_(None))
    else:
        # Only specific priorities (no NULL)
        return query.filter(TestResult.priority.in_(priority_list))


# ============================================================================
# Release Queries
# ============================================================================

def get_all_releases(db: Session, active_only: bool = False) -> List[Release]:
    """
    Get all releases.

    Args:
        db: Database session
        active_only: If True, only return active releases

    Returns:
        List of Release objects
    """
    query = db.query(Release)
    if active_only:
        query = query.filter(Release.is_active == True)
    return query.order_by(Release.name).all()


def get_release_by_name(db: Session, release_name: str) -> Optional[Release]:
    """
    Get a release by name.

    Args:
        db: Database session
        release_name: Release name (e.g., "7.0.0.0")

    Returns:
        Release object or None
    """
    return db.query(Release).filter(Release.name == release_name).first()


# ============================================================================
# Module Queries
# ============================================================================

def get_modules_for_release(db: Session, release_name: str) -> List[Module]:
    """
    Get all modules for a specific release.

    Args:
        db: Database session
        release_name: Release name

    Returns:
        List of Module objects
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    return db.query(Module)\
        .filter(Module.release_id == release.id)\
        .order_by(Module.name)\
        .all()


def get_module(
    db: Session,
    release_name: str,
    module_name: str
) -> Optional[Module]:
    """
    Get a specific module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name

    Returns:
        Module object or None
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return None

    return db.query(Module)\
        .filter(Module.release_id == release.id, Module.name == module_name)\
        .first()


def get_modules_for_release_by_testcases(
    db: Session,
    release_name: str,
    version: Optional[str] = None
) -> List[str]:
    """
    Get unique testcase_module values for a release.

    This returns modules based on test file paths, not Jenkins job modules.
    Used for dashboard grouping by path-derived modules.

    Args:
        db: Database session
        release_name: Release name
        version: Optional version filter (e.g., "7.0.0.0")

    Returns:
        List of module names sorted alphabetically
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Query distinct testcase_module values
    query = db.query(TestResult.testcase_module).distinct()\
        .join(Job, TestResult.job_id == Job.id)\
        .join(Module, Job.module_id == Module.id)\
        .filter(
            Module.release_id == release.id,
            TestResult.testcase_module.isnot(None)
        )

    if version:
        query = query.filter(Job.version == version)

    modules = [row[0] for row in query.all()]
    return sorted(modules)


# ============================================================================
# Job Queries
# ============================================================================

def get_jobs_for_module(
    db: Session,
    release_name: str,
    module_name: str,
    version: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Job]:
    """
    Get all jobs for a specific module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        version: Optional version filter (e.g., "7.0.0.0")
        limit: Optional limit on number of jobs (most recent)

    Returns:
        List of Job objects sorted by job_id descending
    """
    module = get_module(db, release_name, module_name)
    if not module:
        return []

    # Build query with optional version filter
    query = db.query(Job).filter(Job.module_id == module.id)

    if version:
        query = query.filter(Job.version == version)

    jobs = query.all()

    # Sort by job_id as integer in Python (more reliable than SQL CAST)
    jobs.sort(key=lambda j: int(j.job_id), reverse=True)

    if limit:
        jobs = jobs[:limit]

    return jobs


def get_jobs_for_testcase_module(
    db: Session,
    release_name: str,
    testcase_module: str,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    limit: int = 50
) -> List[Job]:
    """
    Get jobs that contain tests for a specific testcase_module.

    Returns jobs where at least one test result has the given testcase_module,
    sorted by job_id descending.

    Note: A single job may contain tests from multiple testcase_modules
    (this is the cross-contamination issue being addressed in the UI).

    Args:
        db: Database session
        release_name: Release name
        testcase_module: Testcase module derived from file path (e.g., "business_policy")
        version: Optional version filter (e.g., "7.0.0.0")
        parent_job_id: Optional parent job ID filter
        limit: Maximum number of jobs to return (default: 50)

    Returns:
        List of Job objects sorted by job_id descending
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Subquery: Get distinct job IDs that have this testcase_module
    job_ids_subquery = db.query(TestResult.job_id).distinct()\
        .filter(TestResult.testcase_module == testcase_module)\
        .subquery()

    # Main query: Get full Job objects for those job IDs
    query = db.query(Job)\
        .join(Module, Job.module_id == Module.id)\
        .filter(
            Module.release_id == release.id,
            Job.id.in_(job_ids_subquery)
        )

    if version:
        query = query.filter(Job.version == version)

    if parent_job_id:
        query = query.filter(Job.parent_job_id == parent_job_id)

    jobs = query.all()

    # Sort by numeric job_id (descending)
    jobs.sort(key=lambda j: int(j.job_id), reverse=True)

    return jobs[:limit]


def get_previous_job(
    db: Session,
    release_name: str,
    module_name: str,
    current_job_id: str
) -> Optional[Job]:
    """
    Get the job that immediately precedes the current job.
    Jobs are ordered by job_id as integer (descending).

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        current_job_id: Current job ID

    Returns:
        Previous Job object or None if current job is first
    """
    module = get_module(db, release_name, module_name)
    if not module:
        return None

    # Direct database query to find the previous job
    # Use CAST to convert job_id to integer for proper numeric comparison
    try:
        current_job_id_int = int(current_job_id)

        # Numeric comparison using CAST(job_id AS INTEGER)
        # This works across SQLite, PostgreSQL, and MySQL
        return db.query(Job)\
            .filter(
                Job.module_id == module.id,
                func.cast(Job.job_id, Integer) < current_job_id_int
            )\
            .order_by(desc(func.cast(Job.job_id, Integer)))\
            .first()
    except (ValueError, TypeError):
        # If job_id is not numeric, fall back to string comparison
        # This gets the job with job_id < current_job_id, ordered descending
        return db.query(Job)\
            .filter(
                Job.module_id == module.id,
                Job.job_id < current_job_id
            )\
            .order_by(desc(Job.job_id))\
            .first()


def get_job(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> Optional[Job]:
    """
    Get a specific job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        Job object or None
    """
    module = get_module(db, release_name, module_name)
    if not module:
        return None

    return db.query(Job)\
        .filter(Job.module_id == module.id, Job.job_id == job_id)\
        .first()


def get_job_summary_stats(
    db: Session,
    release_name: str,
    module_name: str,
    version: Optional[str] = None
) -> Dict[str, any]:
    """
    Get summary statistics for all jobs in a module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        version: Optional version filter (e.g., "7.0.0.0")

    Returns:
        Dict with summary statistics
    """
    jobs = get_jobs_for_module(db, release_name, module_name, version=version)

    if not jobs:
        return {
            'total_jobs': 0,
            'latest_job': None,
            'average_pass_rate': 0.0,
            'total_tests': 0
        }

    # Latest job is first (ordered by job_id desc)
    latest_job = jobs[0]

    # Calculate averages
    avg_pass_rate = sum(job.pass_rate for job in jobs) / len(jobs)

    return {
        'total_jobs': len(jobs),
        'latest_job': {
            'job_id': latest_job.job_id,
            'total': latest_job.total,
            'passed': latest_job.passed,
            'failed': latest_job.failed,  # Includes both FAILED and ERROR statuses
            'skipped': latest_job.skipped,
            'pass_rate': latest_job.pass_rate
        },
        'average_pass_rate': round(avg_pass_rate, 2),
        'total_tests': latest_job.total if latest_job else 0
    }


def get_pass_rate_history(
    db: Session,
    release_name: str,
    module_name: str,
    version: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, any]]:
    """
    Get pass rate history for a module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        version: Optional version filter (e.g., "7.0.0.0")
        limit: Number of recent jobs to include

    Returns:
        List of dicts with job_id and pass_rate
    """
    jobs = get_jobs_for_module(db, release_name, module_name, version=version, limit=limit)

    # Reverse to get chronological order
    jobs.reverse()

    return [
        {
            'job_id': job.job_id,
            'pass_rate': job.pass_rate,
            'total': job.total,
            'passed': job.passed,
            'failed': job.failed
        }
        for job in jobs
    ]


# ============================================================================
# Test Result Queries
# ============================================================================

def get_test_results_for_job(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str,
    status_filter: Optional[List[TestStatusEnum]] = None,
    topology_filter: Optional[str] = None,
    priority_filter: Optional[List[str]] = None,
    testcase_module_filter: Optional[str] = None,
    search: Optional[str] = None
) -> List[TestResult]:
    """
    Get test results for a specific job with optional filters.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID
        status_filter: Optional list of status filters (e.g., [TestStatusEnum.PASSED, TestStatusEnum.FAILED])
        topology_filter: Optional topology filter
        priority_filter: Optional list of priorities (e.g., ['P0', 'P1'])
        testcase_module_filter: Optional testcase module filter (e.g., 'business_policy', 'routing')
        search: Optional search string (matches test_name, class_name, file_path)

    Returns:
        List of TestResult objects
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return []

    query = db.query(TestResult).filter(TestResult.job_id == job.id)

    if status_filter:
        query = query.filter(TestResult.status.in_(status_filter))

    if topology_filter:
        query = query.filter(TestResult.topology_metadata == topology_filter)

    if testcase_module_filter:
        query = query.filter(TestResult.testcase_module == testcase_module_filter)

    if priority_filter:
        # Validate priority values
        invalid = [p for p in priority_filter if p not in VALID_PRIORITIES]
        if invalid:
            raise validation_error(
                f"Invalid priorities: {', '.join(invalid)}. "
                f"Valid values: {', '.join(sorted(VALID_PRIORITIES))}"
            )

        # Apply priority filter using centralized helper
        query = _apply_priority_filter(query, priority_filter)

    if search:
        # Escape special LIKE characters to prevent injection
        escaped_search = escape_like_pattern(search)
        search_pattern = f"%{escaped_search}%"
        query = query.filter(
            (TestResult.test_name.like(search_pattern, escape='\\')) |
            (TestResult.class_name.like(search_pattern, escape='\\')) |
            (TestResult.file_path.like(search_pattern, escape='\\'))
        )

    return query.order_by(TestResult.order_index).all()


def get_test_results_for_testcase_module(
    db: Session,
    release_name: str,
    testcase_module: str,
    job_id: str,
    status_filter: Optional[List[TestStatusEnum]] = None,
    topology_filter: Optional[str] = None,
    priority_filter: Optional[List[str]] = None,
    search: Optional[str] = None
) -> List[TestResult]:
    """
    Get test results filtered by testcase_module within a specific job.

    This filters test results to only those belonging to the testcase_module,
    even if the job ran tests from multiple modules.

    Args:
        db: Database session
        release_name: Release name
        testcase_module: Testcase module derived from file path (e.g., "business_policy")
        job_id: Job ID
        status_filter: Optional list of status filters
        topology_filter: Optional topology filter
        priority_filter: Optional list of priorities
        search: Optional search string

    Returns:
        List of TestResult objects filtered by testcase_module
    """
    # First, we need to find any job that has this job_id in the release
    # Since we're filtering by testcase_module, we don't need to know the Jenkins module
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Find the job by job_id within this release
    job = db.query(Job)\
        .join(Module, Job.module_id == Module.id)\
        .filter(
            Module.release_id == release.id,
            Job.job_id == job_id
        ).first()

    if not job:
        return []

    # Base query: Filter by job AND testcase_module
    query = db.query(TestResult).filter(
        TestResult.job_id == job.id,
        TestResult.testcase_module == testcase_module
    )

    # Apply same filters as get_test_results_for_job()
    if status_filter:
        query = query.filter(TestResult.status.in_(status_filter))

    if topology_filter:
        query = query.filter(TestResult.topology_metadata == topology_filter)

    if priority_filter:
        # Validate priority values
        invalid = [p for p in priority_filter if p not in VALID_PRIORITIES]
        if invalid:
            raise validation_error(
                f"Invalid priorities: {', '.join(invalid)}. "
                f"Valid values: {', '.join(sorted(VALID_PRIORITIES))}"
            )

        # Apply priority filter using centralized helper
        query = _apply_priority_filter(query, priority_filter)

    if search:
        escaped_search = escape_like_pattern(search)
        search_pattern = f"%{escaped_search}%"
        query = query.filter(
            (TestResult.test_name.like(search_pattern, escape='\\')) |
            (TestResult.class_name.like(search_pattern, escape='\\')) |
            (TestResult.file_path.like(search_pattern, escape='\\'))
        )

    return query.order_by(TestResult.order_index).all()


def get_test_results_grouped_by_jenkins_topology(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> Dict[str, Dict[str, List[TestResult]]]:
    """
    Get test results grouped by jenkins_topology (execution topology) and setup_ip.

    NOTE: This groups by EXECUTION topology (jenkins_topology), not design topology.
    Design topology filtering uses topology_metadata field.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        Nested dict: {jenkins_topology: {setup_ip: [TestResult]}}
    """
    results = get_test_results_for_job(db, release_name, module_name, job_id)

    grouped = {}
    for result in results:
        topology = result.jenkins_topology or 'unknown'
        setup_ip = result.setup_ip or 'unknown'

        if topology not in grouped:
            grouped[topology] = {}

        if setup_ip not in grouped[topology]:
            grouped[topology][setup_ip] = []

        grouped[topology][setup_ip].append(result)

    return grouped


def get_test_results_by_class(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> Dict[str, List[TestResult]]:
    """
    Get test results grouped by class name.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        Dict mapping class_name -> [TestResult]
    """
    results = get_test_results_for_job(db, release_name, module_name, job_id)

    by_class = {}
    for result in results:
        class_name = result.class_name

        if class_name not in by_class:
            by_class[class_name] = []

        by_class[class_name].append(result)

    # Sort tests within each class by test name
    for class_name in by_class:
        by_class[class_name].sort(key=lambda r: r.test_name)

    return by_class


def get_unique_topologies(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> List[str]:
    """
    Get list of unique design topologies for a job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        List of design topology names (from topology_metadata)
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return []

    topologies = db.query(TestResult.topology_metadata)\
        .filter(TestResult.job_id == job.id)\
        .distinct()\
        .all()

    return sorted([t[0] for t in topologies if t[0]])


def get_unique_modules(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> List[str]:
    """
    Get list of unique testcase modules for a job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        List of testcase module names (e.g., "business_policy", "routing")
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return []

    modules = db.query(TestResult.testcase_module)\
        .filter(TestResult.job_id == job.id)\
        .distinct()\
        .all()

    return sorted([m[0] for m in modules if m[0]])


def get_topology_statistics(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> Dict[str, Dict[str, int]]:
    """
    Get statistics broken down by topology.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        Dict mapping topology -> {passed, failed, skipped, total}
        Note: failed includes both FAILED and ERROR statuses
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return {}

    # Get all test results for this job
    results = db.query(TestResult)\
        .filter(TestResult.job_id == job.id)\
        .all()

    # Group by topology and count statuses
    topology_stats = {}
    for result in results:
        topology = result.jenkins_topology or 'Unknown'
        if topology not in topology_stats:
            topology_stats[topology] = {
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'total': 0
            }

        status_key = result.status.value.lower()
        topology_stats[topology][status_key] = topology_stats[topology].get(status_key, 0) + 1
        topology_stats[topology]['total'] += 1

    return topology_stats


# ============================================================================
# Statistics Queries
# ============================================================================

def get_database_statistics(db: Session) -> Dict[str, int]:
    """
    Get overall database statistics.

    Args:
        db: Database session

    Returns:
        Dict with counts for releases, modules, jobs, tests
    """
    return {
        'releases': db.query(Release).count(),
        'modules': db.query(Module).count(),
        'jobs': db.query(Job).count(),
        'test_results': db.query(TestResult).count()
    }


def get_priority_statistics(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str,
    include_comparison: bool = False
) -> List[Dict[str, Any]]:
    """
    Get statistics broken down by priority for a specific job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID
        include_comparison: If True, include comparison with previous job

    Returns:
        List of dicts with priority statistics:
        [{priority, total, passed, failed, skipped, pass_rate, comparison?}]
        Note: failed includes both FAILED and ERROR statuses
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return []

    # Query grouped by priority with counts
    results = db.query(
        TestResult.priority,
        func.count(TestResult.id).label('total'),
        func.sum(case((TestResult.status == TestStatusEnum.PASSED, 1), else_=0)).label('passed'),
        func.sum(case((TestResult.status == TestStatusEnum.FAILED, 1), else_=0)).label('failed'),
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped')
    ).filter(
        TestResult.job_id == job.id
    ).group_by(
        TestResult.priority
    ).all()

    # Convert to list of dicts
    stats = []
    for row in results:
        priority = row.priority or 'UNKNOWN'
        total = row.total
        passed = row.passed
        failed = row.failed
        skipped = row.skipped

        # Calculate pass rate (including skipped in denominator)
        pass_rate = (passed / total * 100) if total > 0 else 0.0

        stats.append({
            'priority': priority,
            'total': total,
            'passed': passed,
            'failed': failed,  # Includes both FAILED and ERROR statuses
            'skipped': skipped,
            'pass_rate': round(pass_rate, 2)
        })

    # Get comparison data if requested
    if include_comparison:
        try:
            previous_job = get_previous_job(db, release_name, module_name, job_id)

            if previous_job:
                previous_stats = get_priority_statistics(
                    db, release_name, module_name, previous_job.job_id, include_comparison=False
                )
                # Use helper function to add comparison data
                _add_comparison_data(stats, previous_stats)
        except Exception as e:
            # Log error but don't fail the entire request
            logger.error(f"Failed to fetch comparison data for job {job_id}: {e}")
            # Stats remain without comparison data (no 'comparison' key)

    # Sort by priority (P0, P1, P2, P3, UNKNOWN)
    stats.sort(key=lambda x: PRIORITY_ORDER.get(x['priority'], 999))

    return stats


def get_priority_statistics_for_parent_job(
    db: Session,
    release_name: str,
    module_name: str,
    parent_job_id: str,
    parent_jobs: List[Job],
    include_comparison: bool = False,
    exclude_flaky: bool = False
) -> List[Dict[str, Any]]:
    """
    Get statistics broken down by priority for a parent job (all its sub-jobs).

    Calculates priority statistics across ALL sub-jobs for a parent job,
    filtered by testcase_module to show only tests from the specified module.

    Args:
        db: Database session
        release_name: Release name
        module_name: Testcase module name (path-derived)
        parent_job_id: Parent job ID
        parent_jobs: List of Job objects (all sub-jobs for this parent)
        include_comparison: If True, include comparison with previous parent job
        exclude_flaky: If True, exclude passed flaky tests from pass rate calculation

    Returns:
        List of dicts with priority statistics:
        [{priority, total, passed, failed, skipped, pass_rate, comparison?}]
        Note: failed includes both FAILED and ERROR statuses
    """
    if not parent_jobs:
        return []

    # Get all job IDs for this parent job
    job_ids = [job.id for job in parent_jobs]

    # Query grouped by priority with counts
    # Filter by testcase_module to only count tests from this module
    results = db.query(
        TestResult.priority,
        func.count(TestResult.id).label('total'),
        func.sum(case((TestResult.status == TestStatusEnum.PASSED, 1), else_=0)).label('passed'),
        func.sum(case((TestResult.status == TestStatusEnum.FAILED, 1), else_=0)).label('failed'),
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped')
    ).filter(
        TestResult.job_id.in_(job_ids),
        TestResult.testcase_module == module_name  # Filter by path-based module
    ).group_by(
        TestResult.priority
    ).all()

    # Convert to list of dicts
    stats = []
    for row in results:
        priority = row.priority or 'UNKNOWN'
        total = row.total
        passed = row.passed
        failed = row.failed
        skipped = row.skipped

        # Calculate pass rate (including skipped in denominator)
        pass_rate = (passed / total * 100) if total > 0 else 0.0

        stats.append({
            'priority': priority,
            'total': total,
            'passed': passed,
            'failed': failed,  # Includes both FAILED and ERROR statuses
            'skipped': skipped,
            'pass_rate': round(pass_rate, 2)
        })

    # Apply exclude_flaky logic if requested
    if exclude_flaky:
        from app.services import trend_analyzer
        from sqlalchemy import tuple_

        # Get flaky test keys for this module
        failure_summary = trend_analyzer.get_dashboard_failure_summary(
            db, release_name, module_name, use_testcase_module=True
        )
        flaky_test_keys = failure_summary.get('flaky_test_keys', [])

        if flaky_test_keys:
            # Parse test keys into tuples for querying
            test_key_tuples = []
            for test_key in flaky_test_keys:
                parts = test_key.split('::')
                if len(parts) == 3:
                    test_key_tuples.append(tuple(parts))

            if test_key_tuples:
                # Query to count passed flaky tests per priority
                flaky_passed_by_priority = db.query(
                    TestResult.priority,
                    func.count(TestResult.id).label('flaky_passed_count')
                ).filter(
                    TestResult.job_id.in_(job_ids),
                    TestResult.testcase_module == module_name,
                    tuple_(TestResult.file_path, TestResult.class_name, TestResult.test_name).in_(test_key_tuples),
                    TestResult.status == TestStatusEnum.PASSED
                ).group_by(
                    TestResult.priority
                ).all()

                # Create lookup dict for flaky counts by priority
                flaky_counts = {(row.priority or 'UNKNOWN'): row.flaky_passed_count for row in flaky_passed_by_priority}

                # Adjust stats by subtracting passed flaky tests
                for stat in stats:
                    priority = stat['priority']
                    flaky_count = flaky_counts.get(priority, 0)

                    if flaky_count > 0:
                        # Subtract flaky passed from passed count
                        adjusted_passed = stat['passed'] - flaky_count
                        # Recalculate pass rate
                        adjusted_pass_rate = (adjusted_passed / stat['total'] * 100) if stat['total'] > 0 else 0.0

                        stat['passed'] = adjusted_passed
                        stat['pass_rate'] = round(adjusted_pass_rate, 2)

    # Get comparison data if requested
    if include_comparison:
        try:
            # Get all jobs for this module
            all_jobs = get_jobs_for_testcase_module(db, release_name, module_name, version=None, limit=100)

            # Group by parent_job_id
            from collections import defaultdict
            jobs_by_parent = defaultdict(list)
            for job in all_jobs:
                parent_id = job.parent_job_id or job.job_id
                jobs_by_parent[parent_id].append(job)

            # Get parent job IDs sorted descending
            parent_ids = sorted(jobs_by_parent.keys(), key=lambda x: int(x), reverse=True)

            # Find current parent job index
            try:
                current_index = parent_ids.index(parent_job_id)
                # Get previous parent job (next in sorted list)
                if current_index + 1 < len(parent_ids):
                    prev_parent_id = parent_ids[current_index + 1]
                    prev_parent_jobs = jobs_by_parent[prev_parent_id]

                    # Get stats for previous parent job (with same exclude_flaky setting for fair comparison)
                    previous_stats = get_priority_statistics_for_parent_job(
                        db, release_name, module_name, prev_parent_id, prev_parent_jobs,
                        include_comparison=False, exclude_flaky=exclude_flaky
                    )
                    # Use helper function to add comparison data
                    _add_comparison_data(stats, previous_stats)
            except ValueError:
                # Current parent_job_id not found in list
                pass

        except Exception as e:
            # Log error but don't fail the entire request
            logger.error(f"Failed to fetch comparison data for parent job {parent_job_id}: {e}")
            # Stats remain without comparison data (no 'comparison' key)

    # Sort by priority (P0, P1, P2, P3, UNKNOWN)
    stats.sort(key=lambda x: PRIORITY_ORDER.get(x['priority'], 999))

    return stats


# ============================================================================
# All Modules Aggregation Queries (Parent Job ID)
# ============================================================================

def get_latest_parent_job_ids(
    db: Session,
    release_name: str,
    version: Optional[str] = None,
    limit: int = 10
) -> List[str]:
    """
    Get list of recent parent_job_ids for a release.

    Args:
        db: Database session
        release_name: Release name
        version: Optional version filter
        limit: Number of recent parent_job_ids to return

    Returns:
        List of parent_job_id strings ordered numerically (most recent first)
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Query distinct parent_job_ids
    query = db.query(
        Job.parent_job_id
    ).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id.isnot(None)  # Exclude jobs without parent_job_id
    )

    if version:
        query = query.filter(Job.version == version)

    # Get distinct parent_job_ids
    parent_jobs = query.distinct().all()

    # Sort numerically (descending) and limit
    parent_job_ids = [pj.parent_job_id for pj in parent_jobs]
    parent_job_ids.sort(key=lambda x: int(x), reverse=True)

    return parent_job_ids[:limit]


def get_parent_jobs_with_dates(
    db: Session,
    release_name: str,
    module: str,
    version: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get available parent job IDs with execution dates for dropdown.

    For All Modules: Returns parent job IDs with multi-module jobs
    For specific module: Returns parent job IDs filtered by testcase_module

    Uses executed_at (Jenkins execution time) if available, falls back to created_at (DB import time).

    Args:
        db: Database session
        release_name: Release name
        module: Module name or '__all__' for all modules
        version: Optional version filter
        limit: Number of recent parent_job_ids to return (default: 10)

    Returns:
        List of dicts with {parent_job_id: str, executed_at: datetime}
        Sorted numerically descending (newest first)
    """
    from app.constants import ALL_MODULES_IDENTIFIER
    from sqlalchemy import case

    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Use COALESCE to prefer executed_at, fall back to created_at
    # Take MIN across all sub-jobs for the same parent_job_id
    timestamp_expr = func.min(
        case(
            (Job.executed_at.isnot(None), Job.executed_at),
            else_=Job.created_at
        )
    ).label('executed_at')

    if module == ALL_MODULES_IDENTIFIER:
        # For All Modules: Get parent job IDs with multi-module jobs
        query = db.query(
            Job.parent_job_id,
            timestamp_expr,
            func.count(func.distinct(Job.module_id)).label('module_count')
        ).join(Module).filter(
            Module.release_id == release.id,
            Job.parent_job_id.isnot(None)
        )

        if version:
            query = query.filter(Job.version == version)

        # Group by parent_job_id and filter for multi-module jobs
        query = query.group_by(Job.parent_job_id)\
                     .having(func.count(func.distinct(Job.module_id)) > 1)
    else:
        # For specific module: Filter by testcase_module
        # Subquery: Get distinct job IDs that have this testcase_module
        job_ids_subquery = db.query(TestResult.job_id).distinct()\
            .filter(TestResult.testcase_module == module)\
            .subquery()

        # Main query: Get parent_job_ids and dates for those jobs
        query = db.query(
            Job.parent_job_id,
            timestamp_expr
        ).join(Module).filter(
            Module.release_id == release.id,
            Job.parent_job_id.isnot(None),
            Job.id.in_(job_ids_subquery)
        )

        if version:
            query = query.filter(Job.version == version)

        # Group by parent_job_id
        query = query.group_by(Job.parent_job_id)

    # Execute query
    results = query.all()

    # Convert to list of dicts
    parent_jobs = [
        {
            'parent_job_id': result.parent_job_id,
            'executed_at': result.executed_at  # Now using executed_at (with fallback)
        }
        for result in results
    ]

    # Sort numerically descending (newest first)
    parent_jobs.sort(key=lambda x: int(x['parent_job_id']), reverse=True)

    return parent_jobs[:limit]


def get_previous_parent_job_id(
    db: Session,
    release_name: str,
    current_parent_job_id: str,
    version: Optional[str] = None
) -> Optional[str]:
    """
    Get the parent_job_id that immediately precedes the current one.
    Parent jobs are ordered by creation time (descending).

    Args:
        db: Database session
        release_name: Release name
        current_parent_job_id: Current parent job ID
        version: Optional version filter

    Returns:
        Previous parent_job_id or None if current is first
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return None

    # First, get the creation time of the current parent job
    current_job_query = db.query(
        func.min(Job.created_at).label('created_at')
    ).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id == current_parent_job_id
    )

    if version:
        current_job_query = current_job_query.filter(Job.version == version)

    current_job = current_job_query.first()

    if not current_job or not current_job.created_at:
        return None

    # Find the parent_job_id with the next oldest creation time
    previous_query = db.query(
        Job.parent_job_id,
        func.min(Job.created_at).label('earliest_created')
    ).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id.isnot(None),
        Job.parent_job_id != current_parent_job_id
    )

    if version:
        previous_query = previous_query.filter(Job.version == version)

    previous_job = previous_query.group_by(Job.parent_job_id)\
        .having(func.min(Job.created_at) < current_job.created_at)\
        .order_by(desc('earliest_created'))\
        .first()

    return previous_job.parent_job_id if previous_job else None


def get_jobs_by_parent_job_id(
    db: Session,
    release_name: str,
    parent_job_id: str
) -> List[Job]:
    """
    Get all module jobs that share the same parent_job_id.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID

    Returns:
        List of Job objects from all modules with this parent_job_id
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    return db.query(Job).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id == parent_job_id
    ).all()


def _aggregate_jobs_for_parent(jobs: List[Job], parent_job_id: str) -> Dict[str, Any]:
    """
    Helper function to aggregate job statistics for a parent_job_id.

    Args:
        jobs: List of Job objects to aggregate
        parent_job_id: Parent job ID

    Returns:
        Dict with aggregated statistics
    """
    if not jobs:
        return {
            'parent_job_id': parent_job_id,
            'version': None,
            'total': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'error': 0,
            'pass_rate': 0.0,
            'created_at': None,
            'module_count': 0
        }

    # Aggregate stats across all jobs
    total = sum(job.total for job in jobs)
    passed = sum(job.passed for job in jobs)
    failed = sum(job.failed for job in jobs)
    skipped = sum(job.skipped for job in jobs)

    # Validate aggregated counts
    assert total >= skipped, f"Total tests ({total}) should be >= skipped ({skipped})"
    assert total >= 0, f"Total tests should be non-negative, got {total}"

    # Calculate weighted pass rate (including skipped in denominator)
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    # Find most common version
    versions = [job.version for job in jobs if job.version]
    most_common_version = max(set(versions), key=versions.count) if versions else None

    # Get earliest creation time
    earliest_created = min(job.created_at for job in jobs)

    # Get earliest execution time (if available, use executed_at; otherwise fallback to created_at)
    jobs_with_executed_at = [job for job in jobs if job.executed_at]
    if jobs_with_executed_at:
        earliest_executed = min(job.executed_at for job in jobs_with_executed_at)
    else:
        earliest_executed = earliest_created

    return {
        'parent_job_id': parent_job_id,
        'version': most_common_version,
        'total': total,
        'passed': passed,
        'failed': failed,  # Includes both FAILED and ERROR statuses
        'skipped': skipped,
        'pass_rate': round(pass_rate, 2),
        'created_at': earliest_created,
        'executed_at': earliest_executed,
        'module_count': len(jobs)
    }


def get_aggregated_stats_for_parent_job(
    db: Session,
    release_name: str,
    parent_job_id: str
) -> Dict[str, Any]:
    """
    Aggregate statistics across all modules for a parent_job_id.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID (must not be None)

    Returns:
        Dict with aggregated statistics:
        {
            'parent_job_id': str,
            'version': str,  # Most common version
            'total': int,
            'passed': int,
            'failed': int,  # Includes both FAILED and ERROR statuses
            'skipped': int,
            'pass_rate': float,
            'created_at': datetime,
            'module_count': int
        }
    """
    # Validate parent_job_id is not None
    if not parent_job_id:
        raise ValueError("parent_job_id cannot be None or empty")

    jobs = get_jobs_by_parent_job_id(db, release_name, parent_job_id)
    return _aggregate_jobs_for_parent(jobs, parent_job_id)


def get_module_breakdown_for_parent_job(
    db: Session,
    release_name: str,
    parent_job_id: str,
    priorities: Optional[List[str]] = None,
    exclude_flaky: bool = False
) -> List[Dict[str, Any]]:
    """
    Get per-module statistics for a parent_job_id (based on path-derived modules).

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID
        priorities: Optional list of priorities to filter by (e.g., ['P0', 'P1'])
        exclude_flaky: If True, exclude passed flaky tests from pass rate calculation

    Returns:
        List of dicts with module-level stats:
        [{
            'module_name': str,  # testcase_module (path-derived)
            'total': int,
            'passed': int,
            'failed': int,  # Includes both FAILED and ERROR statuses
            'skipped': int,
            'pass_rate': float
        }]
        Sorted alphabetically by module_name
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Get all jobs for this parent_job_id
    jobs = get_jobs_by_parent_job_id(db, release_name, parent_job_id)

    if not jobs:
        return []

    job_ids = [job.id for job in jobs]

    # Query test results grouped by testcase_module (path-derived module)
    query = db.query(
        TestResult.testcase_module,
        func.count(TestResult.id).label('total'),
        func.sum(case((TestResult.status == TestStatusEnum.PASSED, 1), else_=0)).label('passed'),
        func.sum(case((TestResult.status == TestStatusEnum.FAILED, 1), else_=0)).label('failed'),
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped')
    ).filter(
        TestResult.job_id.in_(job_ids),
        TestResult.testcase_module.isnot(None)  # Exclude test results without module
    )

    # Apply priority filter if provided
    if priorities:
        query = _apply_priority_filter(query, priorities)

    results = query.group_by(TestResult.testcase_module).all()

    breakdown = []
    for row in results:
        testcase_module = row.testcase_module
        total = row.total
        passed = row.passed
        failed = row.failed
        skipped = row.skipped

        # Calculate pass rate (including skipped in denominator)
        pass_rate = (passed / total * 100) if total > 0 else 0.0

        breakdown.append({
            'module_name': testcase_module,
            'total': total,
            'passed': passed,
            'failed': failed,  # Includes both FAILED and ERROR statuses
            'skipped': skipped,
            'pass_rate': round(pass_rate, 2)
        })

    # Apply exclude_flaky logic if requested
    if exclude_flaky and breakdown:
        from app.services import trend_analyzer
        from sqlalchemy import tuple_

        # For each module, get flaky test keys and adjust stats
        for module_stat in breakdown:
            module_name = module_stat['module_name']

            # Get flaky test keys for this module
            failure_summary = trend_analyzer.get_dashboard_failure_summary(
                db, release_name, module_name, use_testcase_module=True
            )
            flaky_test_keys = failure_summary.get('flaky_test_keys', [])

            if flaky_test_keys:
                # Parse test keys into tuples for querying
                test_key_tuples = []
                for test_key in flaky_test_keys:
                    parts = test_key.split('::')
                    if len(parts) == 3:
                        test_key_tuples.append(tuple(parts))

                if test_key_tuples:
                    # Build filter with module and priority constraints
                    filters = [
                        TestResult.job_id.in_(job_ids),
                        TestResult.testcase_module == module_name,
                        tuple_(TestResult.file_path, TestResult.class_name, TestResult.test_name).in_(test_key_tuples),
                        TestResult.status == TestStatusEnum.PASSED
                    ]

                    # Apply priority filter if provided
                    if priorities:
                        filters.append(TestResult.priority.in_(priorities))

                    # Count passed flaky tests for this module
                    passed_flaky_count = db.query(func.count(TestResult.id)).filter(*filters).scalar()

                    if passed_flaky_count and passed_flaky_count > 0:
                        # Subtract flaky passed from passed count
                        adjusted_passed = module_stat['passed'] - passed_flaky_count
                        # Recalculate pass rate
                        adjusted_pass_rate = (adjusted_passed / module_stat['total'] * 100) if module_stat['total'] > 0 else 0.0

                        module_stat['passed'] = adjusted_passed
                        module_stat['pass_rate'] = round(adjusted_pass_rate, 2)

    # Sort alphabetically by module name
    breakdown.sort(key=lambda x: x['module_name'])

    return breakdown


def get_all_modules_summary_stats(
    db: Session,
    release_name: str,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get summary statistics for 'All Modules' view.

    Optimized to fetch all jobs in a single query and aggregate in memory.

    Args:
        db: Database session
        release_name: Release name
        version: Optional version filter
        parent_job_id: Optional specific parent job ID to display (if None, shows latest)

    Returns:
        Dict with summary statistics:
        {
            'total_runs': int,
            'latest_run': {...},
            'average_pass_rate': float,
            'total_tests': int
        }
    """
    # Get recent parent_job_ids
    if parent_job_id:
        # If specific parent_job_id provided, use only that one
        parent_job_ids = [parent_job_id]
    else:
        # Otherwise, get latest 10
        parent_job_ids = get_latest_parent_job_ids(db, release_name, version, limit=10)

    if not parent_job_ids:
        return {
            'total_runs': 0,
            'latest_run': None,
            'average_pass_rate': 0.0,
            'total_tests': 0
        }

    # OPTIMIZATION: Fetch all jobs in a single query instead of N queries
    release = get_release_by_name(db, release_name)
    if not release:
        return {
            'total_runs': 0,
            'latest_run': None,
            'average_pass_rate': 0.0,
            'total_tests': 0
        }

    all_jobs = db.query(Job).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id.in_(parent_job_ids)
    ).all()

    # Group jobs by parent_job_id in memory
    jobs_by_parent = defaultdict(list)
    for job in all_jobs:
        jobs_by_parent[job.parent_job_id].append(job)

    # Aggregate stats for each parent_job_id
    all_stats = [
        _aggregate_jobs_for_parent(jobs_by_parent[pj_id], pj_id)
        for pj_id in parent_job_ids
    ]

    # Latest run is the first one
    latest_run = all_stats[0] if all_stats else None

    # Calculate average pass rate across all runs
    avg_pass_rate = sum(stat['pass_rate'] for stat in all_stats) / len(all_stats) if all_stats else 0.0

    return {
        'total_runs': len(parent_job_ids),
        'latest_run': latest_run,
        'average_pass_rate': round(avg_pass_rate, 2),
        'total_tests': latest_run['total'] if latest_run else 0
    }


def get_all_modules_pass_rate_history(
    db: Session,
    release_name: str,
    version: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get pass rate history aggregated across all modules.

    Optimized to fetch all jobs in a single query and aggregate in memory.

    Args:
        db: Database session
        release_name: Release name
        version: Optional version filter
        limit: Number of recent runs to include

    Returns:
        List of aggregated stats per parent_job_id:
        [{
            'parent_job_id': str,
            'pass_rate': float,
            'total': int,
            'passed': int,
            'failed': int,
            'created_at': datetime,
            'executed_at': datetime
        }]
        Sorted chronologically (oldest first for chart display)
    """
    # Get recent parent_job_ids
    parent_job_ids = get_latest_parent_job_ids(db, release_name, version, limit)

    if not parent_job_ids:
        return []

    # OPTIMIZATION: Fetch all jobs in a single query instead of N queries
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    all_jobs = db.query(Job).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id.in_(parent_job_ids)
    ).all()

    # Group jobs by parent_job_id in memory
    jobs_by_parent = defaultdict(list)
    for job in all_jobs:
        jobs_by_parent[job.parent_job_id].append(job)

    # Aggregate stats for each parent_job_id
    history = []
    for pj_id in parent_job_ids:
        stats = _aggregate_jobs_for_parent(jobs_by_parent[pj_id], pj_id)
        history.append({
            'parent_job_id': stats['parent_job_id'],
            'pass_rate': stats['pass_rate'],
            'total': stats['total'],
            'passed': stats['passed'],
            'failed': stats['failed'],
            'created_at': stats['created_at'],
            'executed_at': stats['executed_at']
        })

    # Reverse to get chronological order (oldest first)
    history.reverse()

    return history


def get_aggregated_priority_statistics(
    db: Session,
    release_name: str,
    parent_job_id: str,
    include_comparison: bool = False,
    exclude_flaky: bool = False
) -> List[Dict[str, Any]]:
    """
    Get priority statistics aggregated across all modules for a parent_job_id.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID
        include_comparison: If True, include comparison with previous parent job
        exclude_flaky: If True, exclude passed flaky tests from pass rate calculation

    Returns:
        List of dicts with priority statistics:
        [{priority, total, passed, failed, skipped, pass_rate, comparison?}]
        Note: failed includes both FAILED and ERROR statuses
    """
    # Get all jobs for this parent_job_id
    jobs = get_jobs_by_parent_job_id(db, release_name, parent_job_id)

    if not jobs:
        return []

    # Get job IDs for filtering test results
    job_ids = [job.id for job in jobs]

    # Query grouped by priority with counts across all jobs
    results = db.query(
        TestResult.priority,
        func.count(TestResult.id).label('total'),
        func.sum(case((TestResult.status == TestStatusEnum.PASSED, 1), else_=0)).label('passed'),
        func.sum(case((TestResult.status == TestStatusEnum.FAILED, 1), else_=0)).label('failed'),
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped')
    ).filter(
        TestResult.job_id.in_(job_ids)
    ).group_by(
        TestResult.priority
    ).all()

    # Convert to list of dicts
    stats = []
    for row in results:
        priority = row.priority or 'UNKNOWN'
        total = row.total
        passed = row.passed
        failed = row.failed
        skipped = row.skipped

        # Calculate pass rate (including skipped in denominator)
        pass_rate = (passed / total * 100) if total > 0 else 0.0

        stats.append({
            'priority': priority,
            'total': total,
            'passed': passed,
            'failed': failed,  # Includes both FAILED and ERROR statuses
            'skipped': skipped,
            'pass_rate': round(pass_rate, 2)
        })

    # Apply exclude_flaky logic if requested
    if exclude_flaky:
        from app.services import trend_analyzer
        from sqlalchemy import tuple_

        # Get all flaky test keys across all modules for this release
        all_module_names = get_modules_for_release_by_testcases(db, release_name, version=None)
        all_flaky_test_keys = set()

        for mod_name in all_module_names:
            mod_summary = trend_analyzer.get_dashboard_failure_summary(
                db, release_name, mod_name, use_testcase_module=True
            )
            all_flaky_test_keys.update(mod_summary.get('flaky_test_keys', []))

        if all_flaky_test_keys:
            # Parse test keys into tuples for querying
            test_key_tuples = []
            for test_key in all_flaky_test_keys:
                parts = test_key.split('::')
                if len(parts) == 3:
                    test_key_tuples.append(tuple(parts))

            if test_key_tuples:
                # Query to count passed flaky tests per priority (across all modules)
                flaky_passed_by_priority = db.query(
                    TestResult.priority,
                    func.count(TestResult.id).label('flaky_passed_count')
                ).filter(
                    TestResult.job_id.in_(job_ids),
                    tuple_(TestResult.file_path, TestResult.class_name, TestResult.test_name).in_(test_key_tuples),
                    TestResult.status == TestStatusEnum.PASSED
                ).group_by(
                    TestResult.priority
                ).all()

                # Create lookup dict for flaky counts by priority
                flaky_counts = {(row.priority or 'UNKNOWN'): row.flaky_passed_count for row in flaky_passed_by_priority}

                # Adjust stats by subtracting passed flaky tests
                for stat in stats:
                    priority = stat['priority']
                    flaky_count = flaky_counts.get(priority, 0)

                    if flaky_count > 0:
                        # Subtract flaky passed from passed count
                        adjusted_passed = stat['passed'] - flaky_count
                        # Recalculate pass rate
                        adjusted_pass_rate = (adjusted_passed / stat['total'] * 100) if stat['total'] > 0 else 0.0

                        stat['passed'] = adjusted_passed
                        stat['pass_rate'] = round(adjusted_pass_rate, 2)

    # Get comparison data if requested
    if include_comparison:
        try:
            previous_parent_job_id = get_previous_parent_job_id(db, release_name, parent_job_id)

            if previous_parent_job_id:
                # Use same exclude_flaky setting for fair comparison
                previous_stats = get_aggregated_priority_statistics(
                    db, release_name, previous_parent_job_id,
                    include_comparison=False, exclude_flaky=exclude_flaky
                )
                # Use helper function to add comparison data
                _add_comparison_data(stats, previous_stats)
        except Exception as e:
            # Log error but don't fail the entire request
            logger.error(f"Failed to fetch comparison data for parent job {parent_job_id}: {e}")
            # Stats remain without comparison data (no 'comparison' key)

    # Sort by priority (P0, P1, P2, P3, UNKNOWN)
    stats.sort(key=lambda x: PRIORITY_ORDER.get(x['priority'], 999))

    return stats


# ============================================================================
# Bug Tracking Functions
# ============================================================================

def get_bugs_for_tests(
    db: Session,
    test_results: List[TestResult]
) -> Dict[str, List[BugSchema]]:
    """
    Fetch bugs associated with test results.

    Matches on test_case_id OR testrail_id from TestcaseMetadata.

    Args:
        db: Database session
        test_results: List of TestResult objects

    Returns:
        Dict mapping test_key to list of BugSchema objects
    """
    if not test_results:
        return {}

    # 1. Extract unique test_names from test results (just method names, no class)
    test_names = list(set(test.test_name for test in test_results))

    # 2. Query: TestcaseMetadata -> BugTestcaseMapping -> BugMetadata
    from sqlalchemy import or_
    bugs_query = (
        db.query(
            TestcaseMetadata.testcase_name,
            BugMetadata
        )
        .join(
            BugTestcaseMapping,
            or_(
                BugTestcaseMapping.case_id == TestcaseMetadata.test_case_id,
                BugTestcaseMapping.case_id == TestcaseMetadata.testrail_id
            )
        )
        .join(
            BugMetadata,
            BugMetadata.id == BugTestcaseMapping.bug_id
        )
        .filter(TestcaseMetadata.testcase_name.in_(test_names))
        .all()
    )

    # 3. Group bugs by testcase_name (test method name)
    bugs_by_testcase = {}
    for testcase_name, bug in bugs_query:
        if bug is None:
            continue
        if testcase_name not in bugs_by_testcase:
            bugs_by_testcase[testcase_name] = []
        bugs_by_testcase[testcase_name].append(BugSchema.model_validate(bug))

    # 4. Map to test_key (match on test_name only)
    bugs_by_test_key = {}
    for test in test_results:
        if test.test_name in bugs_by_testcase:
            bugs_by_test_key[test.test_key] = bugs_by_testcase[test.test_name]

    return bugs_by_test_key
