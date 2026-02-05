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


async def run_metadata_sync(sync_type: str = "scheduled"):
    """
    Run metadata sync from Git repository.

    This function runs as a scheduled background task.

    Args:
        sync_type: Type of sync - 'scheduled', 'manual', or 'startup'
    """
    logger.info(f"Starting metadata sync ({sync_type})...")

    settings = get_settings()

    # Check if sync is configured
    if not settings.GIT_REPO_URL:
        logger.warning("GIT_REPO_URL not configured, skipping sync")
        return

    with get_db_context() as db:
        try:
            # Create sync service
            service = MetadataSyncService(db, settings)

            # Run sync
            result = service.sync_metadata(sync_type=sync_type)

            logger.info(f"Metadata sync completed: {result}")

        except Exception as e:
            logger.error(f"Metadata sync failed: {e}", exc_info=True)
            _log_sync_failure(db, sync_type, str(e))


def _log_sync_failure(db, sync_type: str, error_message: str):
    """Log sync failure to database."""
    # Rollback any pending transaction before creating failure log
    db.rollback()

    log_entry = MetadataSyncLog(
        status="failed",
        sync_type=sync_type,
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
