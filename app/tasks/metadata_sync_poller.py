"""
Metadata Sync Background Task.

Automatically syncs test metadata from Git repository on a scheduled basis.
"""
import logging
from datetime import datetime

from app.config import get_settings
from app.database import get_db_context
from app.models.db_models import MetadataSyncLog
from app.services.git_metadata_sync_service import MetadataSyncService

logger = logging.getLogger(__name__)


async def run_metadata_sync_for_release(release_id: int, sync_type: str = "scheduled"):
    """
    Run metadata sync for a specific release from its Git branch.

    This function runs as a scheduled background task.

    Args:
        release_id: Release ID to sync metadata for
        sync_type: Type of sync - 'scheduled', 'manual', or 'startup'
    """
    logger.info(f"Starting metadata sync for release {release_id} ({sync_type})...")

    settings = get_settings()

    # Check if sync is configured
    if not settings.GIT_REPO_URL:
        logger.warning("GIT_REPO_URL not configured, skipping sync")
        return

    with get_db_context() as db:
        try:
            # Get release
            from app.models.db_models import Release
            release = db.query(Release).filter(Release.id == release_id).first()

            if not release:
                logger.error(f"Release {release_id} not found")
                return

            if not release.git_branch:
                logger.warning(f"Release {release.name} has no git_branch configured, skipping sync")
                return

            # Create sync service with release
            service = MetadataSyncService(db, settings, release)

            # Run sync
            result = service.sync_metadata(sync_type=sync_type)

            logger.info(f"Metadata sync completed for {release.name}: {result}")

        except Exception as e:
            logger.error(f"Metadata sync failed for release {release_id}: {e}", exc_info=True)
            _log_sync_failure(db, sync_type, release_id, str(e))


async def run_metadata_sync(sync_type: str = "scheduled"):
    """
    Run metadata sync from Git repository for all active releases.

    DEPRECATED: Use run_metadata_sync_for_release instead.
    This function is kept for backward compatibility.

    Args:
        sync_type: Type of sync - 'scheduled', 'manual', or 'startup'
    """
    logger.warning("run_metadata_sync() is deprecated. Use run_metadata_sync_for_release() instead.")

    settings = get_settings()

    # Check if sync is configured
    if not settings.GIT_REPO_URL:
        logger.warning("GIT_REPO_URL not configured, skipping sync")
        return

    with get_db_context() as db:
        from app.models.db_models import Release
        releases = db.query(Release).filter(
            Release.is_active == True,
            Release.git_branch.isnot(None)
        ).all()

        for release in releases:
            await run_metadata_sync_for_release(release.id, sync_type)


def _log_sync_failure(db, sync_type: str, release_id: int, error_message: str):
    """Log sync failure to database."""
    # Rollback any pending transaction before creating failure log
    db.rollback()

    log_entry = MetadataSyncLog(
        status="failed",
        sync_type=sync_type,
        release_id=release_id,
        tests_discovered=0,
        tests_added=0,
        tests_updated=0,
        tests_removed=0,
        error_message=error_message,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
