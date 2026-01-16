"""
Import service for converting parsed logs into database records.
Bridges the existing parser.py with SQLAlchemy database models.
"""
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

# Add parent directory to path to import existing parser
PARENT_DIR = Path(__file__).resolve().parent.parent.parent.parent
PARSER_DIR = PARENT_DIR / "regression_tracker"
sys.path.insert(0, str(PARSER_DIR))

# Import existing parser and models
from parser import parse_job_directory, scan_logs_directory
from models import TestResult as ParsedTestResult, TestStatus as ParsedTestStatus

# Import database models
from app.models.db_models import (
    Release, Module, Job, TestResult, TestStatusEnum
)


def convert_test_status(parsed_status: ParsedTestStatus) -> TestStatusEnum:
    """Convert parsed TestStatus to database TestStatusEnum."""
    status_map = {
        ParsedTestStatus.PASSED: TestStatusEnum.PASSED,
        ParsedTestStatus.FAILED: TestStatusEnum.FAILED,
        ParsedTestStatus.SKIPPED: TestStatusEnum.SKIPPED,
        ParsedTestStatus.ERROR: TestStatusEnum.ERROR,
    }
    return status_map[parsed_status]


def calculate_job_statistics(test_results: List[ParsedTestResult]) -> Dict[str, int]:
    """
    Calculate summary statistics from test results.

    Args:
        test_results: List of parsed test results

    Returns:
        Dict with total, passed, failed, skipped, error counts and pass_rate
    """
    total = len(test_results)
    passed = sum(1 for r in test_results if r.status == ParsedTestStatus.PASSED)
    failed = sum(1 for r in test_results if r.status == ParsedTestStatus.FAILED)
    skipped = sum(1 for r in test_results if r.status == ParsedTestStatus.SKIPPED)
    error = sum(1 for r in test_results if r.status == ParsedTestStatus.ERROR)

    # Calculate pass rate (matches existing JobSummary logic)
    executed = total - skipped
    if executed == 0:
        pass_rate = 100.0 if total > 0 else 0.0
    else:
        pass_rate = round((passed / executed) * 100, 2)

    return {
        'total': total,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'error': error,
        'pass_rate': pass_rate
    }


def get_or_create_release(
    db: Session,
    release_name: str,
    jenkins_job_url: Optional[str] = None
) -> Release:
    """
    Get existing release or create new one.

    Args:
        db: Database session
        release_name: Name of the release (e.g., "7.0.0.0")
        jenkins_job_url: Optional Jenkins job URL

    Returns:
        Release object
    """
    release = db.query(Release).filter(Release.name == release_name).first()

    if not release:
        release = Release(
            name=release_name,
            is_active=True,
            jenkins_job_url=jenkins_job_url
        )
        db.add(release)
        db.flush()  # Get the ID without committing

    return release


def get_or_create_module(
    db: Session,
    release: Release,
    module_name: str
) -> Module:
    """
    Get existing module or create new one.

    Args:
        db: Database session
        release: Parent release object
        module_name: Name of the module (e.g., "business_policy")

    Returns:
        Module object
    """
    module = db.query(Module).filter(
        Module.release_id == release.id,
        Module.name == module_name
    ).first()

    if not module:
        module = Module(
            release_id=release.id,
            name=module_name
        )
        db.add(module)
        db.flush()

    return module


def get_or_create_job(
    db: Session,
    module: Module,
    job_id: str,
    jenkins_url: Optional[str] = None
) -> Job:
    """
    Get existing job or create new one.

    Args:
        db: Database session
        module: Parent module object
        job_id: Jenkins job number (e.g., "8")
        jenkins_url: Optional Jenkins build URL

    Returns:
        Job object
    """
    job = db.query(Job).filter(
        Job.module_id == module.id,
        Job.job_id == job_id
    ).first()

    if not job:
        job = Job(
            module_id=module.id,
            job_id=job_id,
            jenkins_url=jenkins_url,
            downloaded_at=datetime.utcnow()
        )
        db.add(job)
        db.flush()

    return job


def import_job(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str,
    job_path: str,
    jenkins_url: Optional[str] = None,
    skip_if_exists: bool = True
) -> Tuple[Job, int]:
    """
    Import a single job from logs directory into database.

    Args:
        db: Database session
        release_name: Release name (e.g., "7.0.0.0")
        module_name: Module name (e.g., "business_policy")
        job_id: Job ID (e.g., "8")
        job_path: Path to job directory containing .order.txt files
        jenkins_url: Optional Jenkins build URL
        skip_if_exists: If True, skip if job already exists

    Returns:
        Tuple of (Job object, number of test results imported)
    """
    # Get or create hierarchy
    release = get_or_create_release(db, release_name, jenkins_url)
    module = get_or_create_module(db, release, module_name)
    job = get_or_create_job(db, module, job_id, jenkins_url)

    # Check if job already has test results
    existing_count = db.query(TestResult).filter(TestResult.job_id == job.id).count()
    if skip_if_exists and existing_count > 0:
        print(f"Job {release_name}/{module_name}/{job_id} already has {existing_count} results, skipping")
        return job, 0

    # Parse log files using existing parser
    parsed_results = parse_job_directory(job_path)

    if not parsed_results:
        print(f"No test results found in {job_path}")
        return job, 0

    # Calculate statistics
    stats = calculate_job_statistics(parsed_results)

    # Update job statistics
    job.total = stats['total']
    job.passed = stats['passed']
    job.failed = stats['failed']
    job.skipped = stats['skipped']
    job.error = stats['error']
    job.pass_rate = stats['pass_rate']

    # Convert and insert test results
    for parsed_result in parsed_results:
        test_result = TestResult(
            job_id=job.id,
            file_path=parsed_result.file_path,
            class_name=parsed_result.class_name,
            test_name=parsed_result.test_name,
            status=convert_test_status(parsed_result.status),
            setup_ip=parsed_result.setup_ip,
            topology=parsed_result.topology,
            order_index=parsed_result.order_index,
            was_rerun=parsed_result.was_rerun,
            rerun_still_failed=parsed_result.rerun_still_failed,
            failure_message=parsed_result.failure_message or None
        )
        db.add(test_result)

    db.flush()

    return job, len(parsed_results)


def import_module(
    db: Session,
    release_name: str,
    module_name: str,
    logs_base_path: str,
    skip_existing_jobs: bool = True
) -> Tuple[int, int]:
    """
    Import all jobs for a module from logs directory.

    Args:
        db: Database session
        release_name: Release name
        module_name: Module name
        logs_base_path: Base path to logs directory
        skip_existing_jobs: Skip jobs that already exist

    Returns:
        Tuple of (jobs imported, total tests imported)
    """
    # Scan for jobs in module directory
    module_path = Path(logs_base_path) / release_name / module_name

    if not module_path.exists():
        print(f"Module path not found: {module_path}")
        return 0, 0

    jobs_imported = 0
    tests_imported = 0

    # Iterate through job directories
    for job_dir in module_path.iterdir():
        if not job_dir.is_dir() or job_dir.name.startswith('.'):
            continue

        # Verify it's a valid job directory (numeric name)
        if not job_dir.name.isdigit():
            continue

        job_id = job_dir.name

        try:
            job, test_count = import_job(
                db=db,
                release_name=release_name,
                module_name=module_name,
                job_id=job_id,
                job_path=str(job_dir),
                skip_if_exists=skip_existing_jobs
            )

            if test_count > 0:
                jobs_imported += 1
                tests_imported += test_count
                print(f"Imported job {release_name}/{module_name}/{job_id}: {test_count} tests")

        except Exception as e:
            print(f"Error importing job {release_name}/{module_name}/{job_id}: {e}")
            db.rollback()
            continue

    return jobs_imported, tests_imported


def import_release(
    db: Session,
    release_name: str,
    logs_base_path: str,
    skip_existing_jobs: bool = True
) -> Tuple[int, int, int]:
    """
    Import all modules and jobs for a release.

    Args:
        db: Database session
        release_name: Release name
        logs_base_path: Base path to logs directory
        skip_existing_jobs: Skip jobs that already exist

    Returns:
        Tuple of (modules imported, jobs imported, tests imported)
    """
    release_path = Path(logs_base_path) / release_name

    if not release_path.exists():
        print(f"Release path not found: {release_path}")
        return 0, 0, 0

    modules_imported = 0
    total_jobs = 0
    total_tests = 0

    # Iterate through module directories
    for module_dir in release_path.iterdir():
        if not module_dir.is_dir() or module_dir.name.startswith('.'):
            continue

        module_name = module_dir.name

        try:
            jobs, tests = import_module(
                db=db,
                release_name=release_name,
                module_name=module_name,
                logs_base_path=logs_base_path,
                skip_existing_jobs=skip_existing_jobs
            )

            if jobs > 0:
                modules_imported += 1
                total_jobs += jobs
                total_tests += tests

        except Exception as e:
            print(f"Error importing module {release_name}/{module_name}: {e}")
            db.rollback()
            continue

    return modules_imported, total_jobs, total_tests


def import_all_logs(
    db: Session,
    logs_base_path: str,
    skip_existing_jobs: bool = True
) -> Dict[str, Tuple[int, int, int]]:
    """
    Import all releases, modules, and jobs from logs directory.

    Args:
        db: Database session
        logs_base_path: Base path to logs directory
        skip_existing_jobs: Skip jobs that already exist

    Returns:
        Dict mapping release_name -> (modules, jobs, tests) imported
    """
    # Scan logs directory to discover all releases
    logs_structure = scan_logs_directory(logs_base_path)

    results = {}

    for release_name in logs_structure.keys():
        print(f"\n=== Importing release: {release_name} ===")

        try:
            modules, jobs, tests = import_release(
                db=db,
                release_name=release_name,
                logs_base_path=logs_base_path,
                skip_existing_jobs=skip_existing_jobs
            )

            results[release_name] = (modules, jobs, tests)
            print(f"Release {release_name}: {modules} modules, {jobs} jobs, {tests} tests")

            # Commit after each release
            db.commit()

        except Exception as e:
            print(f"Error importing release {release_name}: {e}")
            db.rollback()
            continue

    return results
