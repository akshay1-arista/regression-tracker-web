#!/usr/bin/env python3
"""
Backfill executed_at field for existing jobs by fetching timestamps from Jenkins API.

This script queries all jobs with NULL executed_at values and populates them
with the actual Jenkins execution timestamp from the Jenkins API.

Usage:
    python scripts/backfill_executed_at.py [--dry-run] [--batch-size 100] [--limit 1000]

Examples:
    # Dry run to see what would be updated
    python scripts/backfill_executed_at.py --dry-run

    # Backfill all jobs
    python scripts/backfill_executed_at.py

    # Backfill first 500 jobs only
    python scripts/backfill_executed_at.py --limit 500

    # Use smaller batch size for slower connections
    python scripts/backfill_executed_at.py --batch-size 50
"""
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.db_models import Job
from app.services.jenkins_service import JenkinsClient
from app.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_jobs_without_executed_at(db: Session, limit: Optional[int] = None) -> List[Job]:
    """
    Get all jobs with NULL executed_at and valid jenkins_url.

    Args:
        db: Database session
        limit: Optional limit on number of jobs to fetch

    Returns:
        List of Job objects needing backfill
    """
    query = db.query(Job).filter(
        Job.executed_at.is_(None),
        Job.jenkins_url.isnot(None),
        Job.jenkins_url != ''
    ).order_by(Job.created_at.desc())  # Process newest first

    if limit:
        query = query.limit(limit)

    jobs = query.all()
    logger.info(f"Found {len(jobs)} jobs without executed_at timestamp")
    return jobs


def fetch_jenkins_timestamp(jenkins_url: str, client: JenkinsClient) -> Optional[datetime]:
    """
    Fetch execution timestamp from Jenkins API for a specific job.

    Args:
        jenkins_url: Full Jenkins job URL (e.g., "https://jenkins.../job/Release/123/")
        client: JenkinsClient instance

    Returns:
        datetime object of execution time, or None if failed
    """
    try:
        job_info = client.get_job_info(jenkins_url)
        timestamp_ms = job_info.get('timestamp')

        if timestamp_ms:
            executed_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            return executed_at
        else:
            logger.warning(f"No timestamp found in Jenkins response for {jenkins_url}")
            return None

    except Exception as e:
        logger.error(f"Failed to fetch timestamp for {jenkins_url}: {e}")
        return None


def backfill_job_timestamps(
    db: Session,
    jobs: List[Job],
    client: JenkinsClient,
    dry_run: bool = False,
    batch_size: int = 100,
    workers: int = 5
) -> dict:
    """
    Backfill executed_at timestamps for a list of jobs.

    Args:
        db: Database session
        jobs: List of jobs to backfill
        client: JenkinsClient instance
        dry_run: If True, don't commit changes to database
        batch_size: Commit after this many successful updates
        workers: Number of parallel workers for Jenkins API calls (default: 5)

    Returns:
        Dict with statistics
    """
    stats = {
        'total': len(jobs),
        'success': 0,
        'failed': 0,
        'skipped': 0
    }

    # Use parallel processing for faster API calls
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit all jobs for parallel timestamp fetching
        future_to_job = {
            executor.submit(fetch_jenkins_timestamp, job.jenkins_url, client): job
            for job in jobs
        }

        # Process completed futures
        for idx, future in enumerate(as_completed(future_to_job), 1):
            job = future_to_job[future]
            try:
                logger.info(f"[{idx}/{stats['total']}] Processing job_id={job.job_id}, module={job.module.name}, jenkins_url={job.jenkins_url[:80]}...")

                # Get timestamp result
                executed_at = future.result()

                if executed_at:
                    if not dry_run:
                        job.executed_at = executed_at
                        db.flush()
                        stats['success'] += 1
                    else:
                        stats['success'] += 1
                        logger.info(f"  [DRY RUN] Would set executed_at to {executed_at.isoformat()}")
                else:
                    stats['failed'] += 1
                    logger.warning(f"  Failed to fetch timestamp")

                # Commit in batches for better performance
                if not dry_run and stats['success'] % batch_size == 0:
                    db.commit()
                    logger.info(f"  Committed batch of {batch_size} updates")

            except Exception as e:
                logger.error(f"  Error processing job {job.id}: {e}")
                stats['failed'] += 1
                if not dry_run:
                    db.rollback()

    # Final commit for remaining jobs
    if not dry_run and stats['success'] > 0:
        db.commit()
        logger.info(f"Final commit for remaining updates")

    return stats


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Backfill executed_at field for existing jobs from Jenkins API"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without committing to database'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Commit after this many successful updates (default: 100)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of jobs to process (default: all)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=5,
        help='Number of parallel workers for Jenkins API calls (default: 5)'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load settings
    settings = get_settings()

    if not settings.JENKINS_URL:
        logger.error("JENKINS_URL not configured in settings")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Jenkins Execution Timestamp Backfill Script")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}")
    logger.info(f"Jenkins URL: {settings.JENKINS_URL}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Parallel workers: {args.workers}")
    if args.limit:
        logger.info(f"Limit: {args.limit} jobs")
    logger.info("=" * 60)
    logger.info("")

    # Create database session
    db = SessionLocal()

    try:
        # Get jobs needing backfill
        jobs = get_jobs_without_executed_at(db, limit=args.limit)

        if not jobs:
            logger.info("No jobs found requiring backfill. All jobs already have executed_at timestamps!")
            return

        # Confirm before proceeding (unless dry-run)
        if not args.dry_run:
            response = input(f"\nFound {len(jobs)} jobs to backfill. Proceed? [y/N]: ")
            if response.lower() != 'y':
                logger.info("Cancelled by user")
                return

        # Create Jenkins client
        client = JenkinsClient(
            url=settings.JENKINS_URL,
            user=settings.JENKINS_USER,
            api_token=settings.JENKINS_API_TOKEN
        )

        # Backfill timestamps
        logger.info("")
        logger.info("Starting backfill process...")
        logger.info("")

        start_time = datetime.now()
        stats = backfill_job_timestamps(
            db=db,
            jobs=jobs,
            client=client,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            workers=args.workers
        )
        end_time = datetime.now()

        # Print summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("Backfill Complete")
        logger.info("=" * 60)
        logger.info(f"Total jobs processed: {stats['total']}")
        logger.info(f"Successfully updated: {stats['success']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Skipped: {stats['skipped']}")
        logger.info(f"Time elapsed: {end_time - start_time}")

        if args.dry_run:
            logger.info("")
            logger.info("DRY RUN - No changes were committed to database")
            logger.info("Run without --dry-run to apply changes")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        db.rollback()
        sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)

    finally:
        db.close()


if __name__ == '__main__':
    main()
