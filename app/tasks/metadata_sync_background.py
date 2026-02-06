"""
Metadata Sync Background Task with Progress Tracking.

Provides job-based metadata synchronization with real-time progress updates via SSE.
"""
import logging
import traceback
from typing import Optional

from app.config import get_settings
from app.database import get_db_context
from app.models.db_models import Release
from app.services.git_metadata_sync_service import (
    MetadataSyncService,
    SYNC_TYPE_MANUAL,
    SYNC_TYPE_SCHEDULED,
)
from app.utils.job_tracker import JobTracker

logger = logging.getLogger(__name__)

# Global job tracker instance
_job_tracker: Optional[JobTracker] = None


def get_job_tracker() -> JobTracker:
    """Get or create global job tracker instance."""
    global _job_tracker
    if _job_tracker is None:
        settings = get_settings()
        _job_tracker = JobTracker(redis_url=settings.REDIS_URL if settings.REDIS_URL else None)
    return _job_tracker


async def run_metadata_sync_with_tracking(
    release_id: int,
    job_id: str,
    sync_type: str = SYNC_TYPE_MANUAL
):
    """
    Run metadata sync for a specific release with job tracking.

    Args:
        release_id: Release ID to sync metadata for
        job_id: Job ID for tracking progress
        sync_type: Type of sync - 'scheduled', 'manual', or 'startup'
    """
    tracker = get_job_tracker()
    settings = get_settings()

    # Initialize job
    tracker.start_job(job_id, f"Metadata sync for release {release_id}")

    try:
        # Check if sync is configured
        if not settings.GIT_REPO_URL:
            error_msg = "GIT_REPO_URL not configured"
            logger.warning(error_msg)
            tracker.log_message(job_id, f"ERROR: {error_msg}")
            tracker.complete_job(job_id, success=False, error=error_msg)
            return

        with get_db_context() as db:
            # Get release
            release = db.query(Release).filter(Release.id == release_id).first()

            if not release:
                error_msg = f"Release {release_id} not found"
                logger.error(error_msg)
                tracker.log_message(job_id, f"ERROR: {error_msg}")
                tracker.complete_job(job_id, success=False, error=error_msg)
                return

            if not release.git_branch:
                error_msg = f"Release {release.name} has no git_branch configured"
                logger.warning(error_msg)
                tracker.log_message(job_id, f"WARNING: {error_msg}")
                tracker.complete_job(job_id, success=False, error=error_msg)
                return

            tracker.log_message(job_id, f"Starting metadata sync for release: {release.name}")
            tracker.log_message(job_id, f"Git branch: {release.git_branch}")

            # Create sync service with release
            service = MetadataSyncService(db, settings, release)

            # Define progress callback
            def progress_callback(message: str):
                tracker.log_message(job_id, message)

            # Run sync
            tracker.log_message(job_id, "Initializing sync service...")
            result = service.sync_metadata(
                sync_type=sync_type,
                progress_callback=progress_callback
            )

            # Log results
            tracker.log_message(job_id, "")
            tracker.log_message(job_id, "=== Sync Complete ===")
            tracker.log_message(job_id, f"Tests discovered: {result.get('tests_discovered', 0)}")
            tracker.log_message(job_id, f"Tests added: {result['added']}")
            tracker.log_message(job_id, f"Tests updated: {result['updated']}")
            tracker.log_message(job_id, f"Tests removed: {result['removed']}")

            if result.get('failed_files'):
                failed_count = result.get('failed_file_count', 0)
                tracker.log_message(job_id, f"Files failed to parse: {failed_count}")

            tracker.log_message(job_id, "")
            tracker.log_message(job_id, f"Sync completed successfully for {release.name}")

            # Mark job complete
            tracker.complete_job(job_id, success=True)

            logger.info(f"Metadata sync completed for {release.name}: {result}")

    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()

        logger.error(
            f"Metadata sync failed for release {release_id}: {error_msg}",
            exc_info=True
        )

        tracker.log_message(job_id, "")
        tracker.log_message(job_id, "=== Sync Failed ===")
        tracker.log_message(job_id, f"ERROR: {error_msg}")
        tracker.log_message(job_id, "")
        tracker.log_message(job_id, "Traceback:")
        for line in error_trace.split('\n'):
            if line.strip():
                tracker.log_message(job_id, line)

        tracker.complete_job(job_id, success=False, error=error_msg)


async def run_metadata_sync_all_releases(
    job_id: str,
    sync_type: str = SYNC_TYPE_SCHEDULED
):
    """
    Run metadata sync for all active releases with job tracking.

    Args:
        job_id: Job ID for tracking progress
        sync_type: Type of sync - 'scheduled' or 'startup'
    """
    tracker = get_job_tracker()
    settings = get_settings()

    # Initialize job
    tracker.start_job(job_id, "Metadata sync for all active releases")

    try:
        # Check if sync is configured
        if not settings.GIT_REPO_URL:
            error_msg = "GIT_REPO_URL not configured"
            logger.warning(error_msg)
            tracker.log_message(job_id, f"WARNING: {error_msg}")
            tracker.complete_job(job_id, success=False, error=error_msg)
            return

        with get_db_context() as db:
            # Get all active releases with git_branch configured
            releases = db.query(Release).filter(
                Release.is_active == True,
                Release.git_branch.isnot(None)
            ).all()

            if not releases:
                msg = "No active releases with git_branch configured"
                logger.warning(msg)
                tracker.log_message(job_id, f"WARNING: {msg}")
                tracker.complete_job(job_id, success=True)
                return

            tracker.log_message(job_id, f"Found {len(releases)} active releases to sync")
            tracker.log_message(job_id, "")

            success_count = 0
            failed_count = 0

            for i, release in enumerate(releases, 1):
                tracker.log_message(job_id, f"=== [{i}/{len(releases)}] Syncing: {release.name} ===")

                try:
                    service = MetadataSyncService(db, settings, release)

                    # Define progress callback
                    def progress_callback(message: str):
                        tracker.log_message(job_id, f"  {message}")

                    # Run sync
                    result = service.sync_metadata(
                        sync_type=sync_type,
                        progress_callback=progress_callback
                    )

                    tracker.log_message(
                        job_id,
                        f"  ✓ {release.name}: {result['added']} added, "
                        f"{result['updated']} updated, {result['removed']} removed"
                    )
                    success_count += 1

                except Exception as e:
                    tracker.log_message(job_id, f"  ✗ {release.name}: {str(e)}")
                    logger.error(f"Failed to sync {release.name}: {e}", exc_info=True)
                    failed_count += 1

                tracker.log_message(job_id, "")

            # Summary
            tracker.log_message(job_id, "=== Sync Summary ===")
            tracker.log_message(job_id, f"Total releases: {len(releases)}")
            tracker.log_message(job_id, f"Successful: {success_count}")
            tracker.log_message(job_id, f"Failed: {failed_count}")

            tracker.complete_job(job_id, success=(failed_count == 0))

            logger.info(f"Metadata sync completed for all releases: {success_count} succeeded, {failed_count} failed")

    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()

        logger.error(f"Metadata sync for all releases failed: {error_msg}", exc_info=True)

        tracker.log_message(job_id, "")
        tracker.log_message(job_id, "=== Sync Failed ===")
        tracker.log_message(job_id, f"ERROR: {error_msg}")
        tracker.log_message(job_id, "")
        tracker.log_message(job_id, "Traceback:")
        for line in error_trace.split('\n'):
            if line.strip():
                tracker.log_message(job_id, line)

        tracker.complete_job(job_id, success=False, error=error_msg)
