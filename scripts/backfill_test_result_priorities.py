#!/usr/bin/env python3
"""
Backfill priority field for existing test results.

This script updates test_results.priority by looking up values from testcase_metadata.
Useful for fixing existing data that was imported before priority mapping was implemented.

Usage:
    # Backfill all test results
    python3 scripts/backfill_test_result_priorities.py

    # Backfill specific release
    python3 scripts/backfill_test_result_priorities.py --release 6.1

    # Backfill specific release and job
    python3 scripts/backfill_test_result_priorities.py --release 6.1 --job 144

    # Dry run (show what would be updated without making changes)
    python3 scripts/backfill_test_result_priorities.py --dry-run
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.models.db_models import Base, TestResult, TestcaseMetadata, Job, Module, Release
from app.config import get_settings

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_priorities(
    release_name=None,
    job_id=None,
    dry_run=False
):
    """
    Backfill priority field for test results.

    Args:
        release_name: Optional release name to filter by (e.g., "6.1")
        job_id: Optional job ID to filter by (e.g., "144")
        dry_run: If True, show what would be updated without making changes

    Returns:
        Tuple of (total_processed, updated_count, not_found_count)
    """
    # Create database connection
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Build query for test results that need priority updates
        query = db.query(TestResult).join(
            Job, TestResult.job_id == Job.id
        ).join(
            Module, Job.module_id == Module.id
        ).join(
            Release, Module.release_id == Release.id
        )

        # Apply filters if provided
        if release_name:
            query = query.filter(Release.name == release_name)
            logger.info(f"Filtering by release: {release_name}")

        if job_id:
            query = query.filter(Job.job_id == job_id)
            logger.info(f"Filtering by job: {job_id}")

        # Get all test results matching filters
        test_results = query.all()
        total = len(test_results)

        logger.info(f"Found {total} test results to process")

        if total == 0:
            logger.warning("No test results found matching criteria")
            return 0, 0, 0

        # Get unique test names for batch lookup
        test_names = list(set(tr.test_name for tr in test_results))
        logger.info(f"Querying metadata for {len(test_names)} unique test names")

        # Build priority lookup from TestcaseMetadata
        metadata_records = db.query(
            TestcaseMetadata.testcase_name,
            TestcaseMetadata.priority
        ).filter(
            TestcaseMetadata.testcase_name.in_(test_names)
        ).all()

        priority_lookup = {record.testcase_name: record.priority for record in metadata_records}
        logger.info(f"Found metadata for {len(priority_lookup)} test names")

        # Update test results
        updated = 0
        not_found = 0
        skipped = 0

        for test_result in test_results:
            priority = priority_lookup.get(test_result.test_name)

            if priority is not None:
                # Check if priority is different
                if test_result.priority != priority:
                    if dry_run:
                        logger.info(
                            f"[DRY RUN] Would update {test_result.test_name}: "
                            f"{test_result.priority} -> {priority}"
                        )
                    else:
                        old_priority = test_result.priority
                        test_result.priority = priority
                        logger.debug(
                            f"Updated {test_result.test_name}: {old_priority} -> {priority}"
                        )
                    updated += 1
                else:
                    skipped += 1
            else:
                # No metadata found for this test
                if test_result.priority is None:
                    logger.debug(f"No metadata found for: {test_result.test_name}")
                    not_found += 1
                else:
                    # Already has a priority and no metadata exists
                    skipped += 1

        if not dry_run:
            db.commit()
            logger.info(f"✓ Database committed successfully")
        else:
            logger.info(f"[DRY RUN] No changes made to database")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total test results processed: {total}")
        logger.info(f"Updated with priority:        {updated}")
        logger.info(f"No metadata found:            {not_found}")
        logger.info(f"Already correct/skipped:      {skipped}")
        logger.info("=" * 60)

        return total, updated, not_found

    except Exception as e:
        logger.error(f"Error during backfill: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill priority field for test results from testcase metadata"
    )
    parser.add_argument(
        '--release',
        type=str,
        help='Filter by release name (e.g., "6.1")'
    )
    parser.add_argument(
        '--job',
        type=str,
        help='Filter by job ID (e.g., "144")'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )

    args = parser.parse_args()

    logger.info("Starting priority backfill process")
    if args.dry_run:
        logger.info("*** DRY RUN MODE - No changes will be made ***")

    try:
        total, updated, not_found = backfill_priorities(
            release_name=args.release,
            job_id=args.job,
            dry_run=args.dry_run
        )

        if args.dry_run:
            logger.info("\nRun without --dry-run to apply these changes")
        else:
            logger.info("\n✓ Priority backfill completed successfully!")

        sys.exit(0)

    except Exception as e:
        logger.error(f"\n✗ Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
