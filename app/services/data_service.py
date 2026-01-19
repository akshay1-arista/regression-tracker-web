"""
Data service layer for database queries.
Provides high-level query functions for API routers.
"""
import logging
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case

from app.models.db_models import (
    Release, Module, Job, TestResult, TestStatusEnum
)
from app.utils.helpers import escape_like_pattern, validation_error
from app.constants import PRIORITY_ORDER

logger = logging.getLogger(__name__)

# Valid priority values
VALID_PRIORITIES = {'P0', 'P1', 'P2', 'P3', 'UNKNOWN'}


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
            'failed': latest_job.failed,
            'skipped': latest_job.skipped,
            'error': latest_job.error,
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
        query = query.filter(TestResult.topology == topology_filter)

    if priority_filter:
        # Validate priority values
        invalid = [p for p in priority_filter if p not in VALID_PRIORITIES]
        if invalid:
            raise validation_error(
                f"Invalid priorities: {', '.join(invalid)}. "
                f"Valid values: {', '.join(sorted(VALID_PRIORITIES))}"
            )

        # Support filtering by multiple priorities including NULL
        if 'UNKNOWN' in priority_filter:
            # Include NULL values when UNKNOWN is selected
            other_priorities = [p for p in priority_filter if p != 'UNKNOWN']
            if other_priorities:
                query = query.filter(
                    (TestResult.priority.in_(other_priorities)) |
                    (TestResult.priority.is_(None))
                )
            else:
                query = query.filter(TestResult.priority.is_(None))
        else:
            query = query.filter(TestResult.priority.in_(priority_filter))

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


def get_test_results_grouped_by_topology(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str
) -> Dict[str, Dict[str, List[TestResult]]]:
    """
    Get test results grouped by topology and setup_ip.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        Nested dict: {topology: {setup_ip: [TestResult]}}
    """
    results = get_test_results_for_job(db, release_name, module_name, job_id)

    grouped = {}
    for result in results:
        topology = result.topology or 'unknown'
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
    Get list of unique topologies for a job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        List of topology names
    """
    job = get_job(db, release_name, module_name, job_id)
    if not job:
        return []

    topologies = db.query(TestResult.topology)\
        .filter(TestResult.job_id == job.id)\
        .distinct()\
        .all()

    return sorted([t[0] for t in topologies if t[0]])


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
        Dict mapping topology -> {passed, failed, skipped, error, total}
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
        topology = result.topology or 'Unknown'
        if topology not in topology_stats:
            topology_stats[topology] = {
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'error': 0,
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
    job_id: str
) -> List[Dict[str, Any]]:
    """
    Get statistics broken down by priority for a specific job.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        job_id: Job ID

    Returns:
        List of dicts with priority statistics:
        [{priority, total, passed, failed, skipped, error, pass_rate}]
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
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped'),
        func.sum(case((TestResult.status == TestStatusEnum.ERROR, 1), else_=0)).label('error')
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
        error = row.error

        # Calculate pass rate (excluding skipped)
        total_non_skipped = total - skipped
        pass_rate = (passed / total_non_skipped * 100) if total_non_skipped > 0 else 0.0

        stats.append({
            'priority': priority,
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'error': error,
            'pass_rate': round(pass_rate, 2)
        })

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
        List of parent_job_id strings ordered by creation time (most recent first)
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Query distinct parent_job_ids with their earliest creation time
    query = db.query(
        Job.parent_job_id,
        func.min(Job.created_at).label('earliest_created')
    ).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id.isnot(None)  # Exclude jobs without parent_job_id
    )

    if version:
        query = query.filter(Job.version == version)

    # Group by parent_job_id and order by earliest creation time
    parent_jobs = query.group_by(Job.parent_job_id)\
        .order_by(desc('earliest_created'))\
        .limit(limit)\
        .all()

    return [pj.parent_job_id for pj in parent_jobs]


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
    error = sum(job.error for job in jobs)

    # Validate aggregated counts
    assert total >= skipped, f"Total tests ({total}) should be >= skipped ({skipped})"
    assert total >= 0, f"Total tests should be non-negative, got {total}"

    # Calculate weighted pass rate
    total_non_skipped = total - skipped
    pass_rate = (passed / total_non_skipped * 100) if total_non_skipped > 0 else 0.0

    # Find most common version
    versions = [job.version for job in jobs if job.version]
    most_common_version = max(set(versions), key=versions.count) if versions else None

    # Get earliest creation time
    earliest_created = min(job.created_at for job in jobs)

    return {
        'parent_job_id': parent_job_id,
        'version': most_common_version,
        'total': total,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'error': error,
        'pass_rate': round(pass_rate, 2),
        'created_at': earliest_created,
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
            'failed': int,
            'skipped': int,
            'error': int,
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
    parent_job_id: str
) -> List[Dict[str, Any]]:
    """
    Get per-module statistics for a parent_job_id.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID

    Returns:
        List of dicts with module-level stats:
        [{
            'module_name': str,
            'job_id': str,
            'total': int,
            'passed': int,
            'failed': int,
            'skipped': int,
            'error': int,
            'pass_rate': float
        }]
        Sorted alphabetically by module_name
    """
    release = get_release_by_name(db, release_name)
    if not release:
        return []

    # Query jobs with module names
    jobs = db.query(Job, Module.name).join(Module).filter(
        Module.release_id == release.id,
        Job.parent_job_id == parent_job_id
    ).all()

    breakdown = []
    for job, module_name in jobs:
        breakdown.append({
            'module_name': module_name,
            'job_id': job.job_id,
            'total': job.total,
            'passed': job.passed,
            'failed': job.failed,
            'skipped': job.skipped,
            'error': job.error,
            'pass_rate': job.pass_rate
        })

    # Sort alphabetically by module name
    breakdown.sort(key=lambda x: x['module_name'])

    return breakdown


def get_all_modules_summary_stats(
    db: Session,
    release_name: str,
    version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get summary statistics for 'All Modules' view.

    Optimized to fetch all jobs in a single query and aggregate in memory.

    Args:
        db: Database session
        release_name: Release name
        version: Optional version filter

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
            'created_at': datetime
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
            'created_at': stats['created_at']
        })

    # Reverse to get chronological order (oldest first)
    history.reverse()

    return history


def get_aggregated_priority_statistics(
    db: Session,
    release_name: str,
    parent_job_id: str
) -> List[Dict[str, Any]]:
    """
    Get priority statistics aggregated across all modules for a parent_job_id.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID

    Returns:
        List of dicts with priority statistics:
        [{priority, total, passed, failed, skipped, error, pass_rate}]
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
        func.sum(case((TestResult.status == TestStatusEnum.SKIPPED, 1), else_=0)).label('skipped'),
        func.sum(case((TestResult.status == TestStatusEnum.ERROR, 1), else_=0)).label('error')
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
        error = row.error

        # Calculate pass rate (excluding skipped)
        total_non_skipped = total - skipped
        pass_rate = (passed / total_non_skipped * 100) if total_non_skipped > 0 else 0.0

        stats.append({
            'priority': priority,
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'error': error,
            'pass_rate': round(pass_rate, 2)
        })

    # Sort by priority (P0, P1, P2, P3, UNKNOWN)
    stats.sort(key=lambda x: PRIORITY_ORDER.get(x['priority'], 999))

    return stats
