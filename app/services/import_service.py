"""
Import service for converting parsed logs into database records.
Bridges the bundled parser with SQLAlchemy database models.
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# Configure logger
logger = logging.getLogger(__name__)

# Import bundled parser and models
from app.parser import parse_job_directory, scan_logs_directory
from app.parser.models import TestResult as ParsedTestResult, TestStatus as ParsedTestStatus

# Import database models
from app.models.db_models import (
    Release, Module, Job, TestResult, TestStatusEnum, TestcaseMetadata
)

# Import utilities
from app.utils.testcase_helpers import extract_module_from_path


def convert_test_status(parsed_status: ParsedTestStatus) -> TestStatusEnum:
    """Convert parsed TestStatus to database TestStatusEnum.

    Note: ERROR status is mapped to FAILED for consistency (hybrid approach).
    """
    status_map = {
        ParsedTestStatus.PASSED: TestStatusEnum.PASSED,
        ParsedTestStatus.FAILED: TestStatusEnum.FAILED,
        ParsedTestStatus.SKIPPED: TestStatusEnum.SKIPPED,
        ParsedTestStatus.ERROR: TestStatusEnum.FAILED,  # Map ERROR → FAILED
    }
    return status_map[parsed_status]


def calculate_job_statistics(test_results: List[ParsedTestResult]) -> Dict[str, int]:
    """
    Calculate summary statistics from test results.

    Args:
        test_results: List of parsed test results

    Returns:
        Dict with total, passed, failed (includes ERROR), skipped counts and pass_rate

    Notes:
        Pass rate calculation follows this business logic:
        - Pass rate = (passed / executed) * 100, where executed = total - skipped
        - If no tests were executed (all skipped), pass_rate = 100.0 if total > 0
        - If no tests exist at all (total = 0), pass_rate = 0.0
        - This matches the existing CLI tool's JobSummary calculation
        - Skipped tests are excluded from the denominator as they weren't executed
        - ERROR status is counted as FAILED for consistency
    """
    total = len(test_results)
    passed = sum(1 for r in test_results if r.status == ParsedTestStatus.PASSED)
    # Count both FAILED and ERROR as failed
    failed = sum(1 for r in test_results if r.status in (ParsedTestStatus.FAILED, ParsedTestStatus.ERROR))
    skipped = sum(1 for r in test_results if r.status == ParsedTestStatus.SKIPPED)

    # Calculate pass rate (matches existing JobSummary logic)
    # See docstring for edge case handling
    executed = total - skipped
    if executed == 0:
        # Business decision: If all tests are skipped, consider it 100% pass rate
        # This indicates the test suite wasn't applicable rather than a failure
        pass_rate = 100.0 if total > 0 else 0.0
    else:
        pass_rate = round((passed / executed) * 100, 2)

    return {
        'total': total,
        'passed': passed,
        'failed': failed,  # Includes both FAILED and ERROR statuses
        'skipped': skipped,
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
    jenkins_url: Optional[str] = None,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None
) -> Job:
    """
    Get existing job or create new one.

    Args:
        db: Database session
        module: Parent module object
        job_id: Jenkins job number (e.g., "8")
        jenkins_url: Optional Jenkins build URL
        version: Optional version extracted from job title (e.g., "7.0.0.0")
        parent_job_id: Optional parent Jenkins job number (e.g., "11", "15")

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
            version=version,
            parent_job_id=parent_job_id,
            downloaded_at=datetime.now(timezone.utc)
        )
        db.add(job)
        db.flush()
    else:
        # Update fields if not set
        if version and not job.version:
            job.version = version
        if parent_job_id and not job.parent_job_id:
            job.parent_job_id = parent_job_id
        db.flush()

    return job


def import_job(
    db: Session,
    release_name: str,
    module_name: str,
    job_id: str,
    job_path: str,
    jenkins_url: Optional[str] = None,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None,
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
        version: Optional version extracted from job title (e.g., "7.0.0.0")
        parent_job_id: Optional parent Jenkins job number (e.g., "11", "15")
        skip_if_exists: If True, skip if job already exists

    Returns:
        Tuple of (Job object, number of test results imported)
    """
    # Get or create hierarchy
    release = get_or_create_release(db, release_name, jenkins_url)
    module = get_or_create_module(db, release, module_name)
    job = get_or_create_job(db, module, job_id, jenkins_url, version, parent_job_id)

    # Check if job already has test results
    existing_count = db.query(TestResult).filter(TestResult.job_id == job.id).count()
    if skip_if_exists and existing_count > 0:
        logger.info(f"Job {release_name}/{module_name}/{job_id} already has {existing_count} results, skipping")
        return job, 0

    # Parse log files using existing parser
    parsed_results = parse_job_directory(job_path)

    if not parsed_results:
        logger.warning(f"No test results found in {job_path}")
        return job, 0

    # Calculate statistics
    stats = calculate_job_statistics(parsed_results)

    # Update job statistics
    job.total = stats['total']
    job.passed = stats['passed']
    job.failed = stats['failed']  # Includes both FAILED and ERROR statuses
    job.skipped = stats['skipped']
    job.pass_rate = stats['pass_rate']

    # Build priority lookup from TestcaseMetadata
    # This maps test_name -> priority for faster lookups
    testcase_names = [r.test_name for r in parsed_results]
    metadata_records = db.query(
        TestcaseMetadata.testcase_name,
        TestcaseMetadata.priority
    ).filter(
        TestcaseMetadata.testcase_name.in_(testcase_names)
    ).all()

    priority_lookup = {record.testcase_name: record.priority for record in metadata_records}
    logger.debug(f"Built priority lookup for {len(priority_lookup)} testcases out of {len(testcase_names)}")

    # Convert and insert/update test results using upsert pattern
    # This prevents duplicates when tests are rerun or appear multiple times in logs
    inserted = 0
    updated = 0

    for parsed_result in parsed_results:
        # Check if this test result already exists (by unique test key within job)
        existing = db.query(TestResult).filter(
            TestResult.job_id == job.id,
            TestResult.file_path == parsed_result.file_path,
            TestResult.class_name == parsed_result.class_name,
            TestResult.test_name == parsed_result.test_name
        ).first()

        if existing:
            # Update existing record (prefer newer data, especially for reruns)
            existing.status = convert_test_status(parsed_result.status)
            existing.setup_ip = parsed_result.setup_ip
            existing.topology = parsed_result.topology
            existing.order_index = parsed_result.order_index
            existing.was_rerun = parsed_result.was_rerun
            existing.rerun_still_failed = parsed_result.rerun_still_failed
            existing.failure_message = parsed_result.failure_message or None
            # Update priority from metadata lookup
            existing.priority = priority_lookup.get(parsed_result.test_name)
            # Update testcase_module derived from file path
            existing.testcase_module = extract_module_from_path(parsed_result.file_path)
            updated += 1
            logger.debug(f"Updated existing test result: {parsed_result.test_name}")
        else:
            # Insert new test result
            # Lookup priority from TestcaseMetadata
            priority = priority_lookup.get(parsed_result.test_name)

            test_result = TestResult(
                job_id=job.id,
                file_path=parsed_result.file_path,
                class_name=parsed_result.class_name,
                test_name=parsed_result.test_name,
                status=convert_test_status(parsed_result.status),
                priority=priority,  # Set priority from metadata lookup
                setup_ip=parsed_result.setup_ip,
                topology=parsed_result.topology,
                order_index=parsed_result.order_index,
                was_rerun=parsed_result.was_rerun,
                rerun_still_failed=parsed_result.rerun_still_failed,
                failure_message=parsed_result.failure_message or None,
                testcase_module=extract_module_from_path(parsed_result.file_path)  # Derive module from file path
            )
            db.add(test_result)
            inserted += 1

    db.flush()

    if updated > 0:
        logger.info(f"Inserted {inserted} new test results, updated {updated} existing")

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
        logger.warning(f"Module path not found: {module_path}")
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
                logger.info(f"Imported job {release_name}/{module_name}/{job_id}: {test_count} tests")

        except (IntegrityError, SQLAlchemyError) as e:
            logger.error(
                f"Database error importing job {release_name}/{module_name}/{job_id}: {e}",
                exc_info=True
            )
            db.rollback()
            continue
        except Exception as e:
            # For unexpected errors, log with full traceback but don't re-raise
            # This allows the import process to continue for other jobs
            logger.exception(
                f"Unexpected error importing job {release_name}/{module_name}/{job_id}: {e}"
            )
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
        logger.warning(f"Release path not found: {release_path}")
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

        except (IntegrityError, SQLAlchemyError) as e:
            logger.error(
                f"Database error importing module {release_name}/{module_name}: {e}",
                exc_info=True
            )
            db.rollback()
            continue
        except Exception as e:
            logger.exception(
                f"Unexpected error importing module {release_name}/{module_name}: {e}"
            )
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
        logger.info(f"=== Importing release: {release_name} ===")

        try:
            modules, jobs, tests = import_release(
                db=db,
                release_name=release_name,
                logs_base_path=logs_base_path,
                skip_existing_jobs=skip_existing_jobs
            )

            results[release_name] = (modules, jobs, tests)
            logger.info(f"Release {release_name}: {modules} modules, {jobs} jobs, {tests} tests")

            # Commit after each release
            db.commit()

        except (IntegrityError, SQLAlchemyError) as e:
            logger.error(
                f"Database error importing release {release_name}: {e}",
                exc_info=True
            )
            db.rollback()
            continue
        except Exception as e:
            logger.exception(
                f"Unexpected error importing release {release_name}: {e}"
            )
            db.rollback()
            continue

    return results


class ImportService:
    """
    Service class for importing test results from logs into database.
    Provides a class interface to the import functions.
    """

    def __init__(self, db: Session):
        """
        Initialize import service.

        Args:
            db: Database session
        """
        self.db = db

    def import_job(
        self,
        release_name: str,
        module_name: str,
        job_id: str,
        job_path: Optional[str] = None,
        jenkins_url: Optional[str] = None,
        version: Optional[str] = None,
        parent_job_id: Optional[str] = None,
        skip_if_exists: bool = True
    ) -> Tuple[Job, int]:
        """
        Import a single job from logs directory into database.

        Args:
            release_name: Release name (e.g., "7.0.0.0")
            module_name: Module name (e.g., "business_policy")
            job_id: Job ID (e.g., "8")
            job_path: Path to job directory (if None, auto-construct from logs base path)
            jenkins_url: Optional Jenkins build URL
            version: Optional version extracted from job title (e.g., "7.0.0.0")
            parent_job_id: Optional parent Jenkins job number (e.g., "11", "15")
            skip_if_exists: If True, skip if job already exists

        Returns:
            Tuple of (Job object, number of test results imported)
        """
        # Auto-construct path if not provided
        if job_path is None:
            from app.config import get_settings
            settings = get_settings()
            job_path = str(Path(settings.LOGS_BASE_PATH) / release_name / module_name / job_id)

        return import_job(
            db=self.db,
            release_name=release_name,
            module_name=module_name,
            job_id=job_id,
            job_path=job_path,
            jenkins_url=jenkins_url,
            version=version,
            parent_job_id=parent_job_id,
            skip_if_exists=skip_if_exists
        )
