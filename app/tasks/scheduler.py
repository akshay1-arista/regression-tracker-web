"""
Background Task Scheduler using APScheduler.

Manages scheduled tasks for automatic Jenkins polling.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.database import get_db_context
from app.models.db_models import AppSettings


logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


def update_bugs_task():
    """Background task to update bug mappings from Jenkins."""
    from app.services.bug_updater_service import BugUpdaterService

    settings = get_settings()

    with get_db_context() as db:
        try:
            service = BugUpdaterService(
                db=db,
                jenkins_user=settings.JENKINS_USER,
                jenkins_token=settings.JENKINS_API_TOKEN,
                jenkins_bug_url=settings.JENKINS_BUG_DATA_URL,
                verify_ssl=settings.JENKINS_VERIFY_SSL
            )
            stats = service.update_bug_mappings()
            logger.info(f"Bug update completed: {stats}")
        except Exception as e:
            logger.error(f"Bug update failed: {e}", exc_info=True)


def start_scheduler():
    """
    Start the APScheduler instance.

    This is called during FastAPI lifespan startup.
    """
    settings = get_settings()

    # Import here to avoid circular imports
    from app.tasks.jenkins_poller import poll_jenkins_for_all_releases

    # Check if auto-update is enabled
    with get_db_context() as db:
        auto_update_setting = db.query(AppSettings).filter(
            AppSettings.key == 'AUTO_UPDATE_ENABLED'
        ).first()

        auto_update_enabled = True  # Default
        if auto_update_setting:
            import json
            auto_update_enabled = json.loads(auto_update_setting.value)

        if auto_update_enabled:
            # Get polling interval (check both old and new setting names for backwards compatibility)
            interval_setting = db.query(AppSettings).filter(
                AppSettings.key == 'POLLING_INTERVAL_HOURS'
            ).first()

            # Fallback to old POLLING_INTERVAL_MINUTES for backwards compatibility
            if not interval_setting:
                interval_setting = db.query(AppSettings).filter(
                    AppSettings.key == 'POLLING_INTERVAL_MINUTES'
                ).first()

            interval_hours = 12.0  # Default: 12 hours
            if interval_setting:
                import json
                interval_value = json.loads(interval_setting.value)

                # Convert minutes to hours if using old setting
                if interval_setting.key == 'POLLING_INTERVAL_MINUTES':
                    interval_hours = interval_value / 60.0
                    logger.warning(f"Using deprecated POLLING_INTERVAL_MINUTES setting. Please migrate to POLLING_INTERVAL_HOURS")
                else:
                    interval_hours = float(interval_value)

            logger.info(f"Starting Jenkins polling scheduler (interval: {interval_hours} hours)")

            scheduler.add_job(
                poll_jenkins_for_all_releases,
                trigger=IntervalTrigger(hours=interval_hours),
                id='jenkins_poller',
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
                name='Jenkins Polling Task'
            )
        else:
            logger.info("Auto-update disabled, scheduler not started")

        # Add per-release metadata sync jobs if enabled
        sync_enabled_setting = db.query(AppSettings).filter(
            AppSettings.key == 'METADATA_SYNC_ENABLED'
        ).first()

        sync_enabled = False
        if sync_enabled_setting:
            import json
            sync_enabled = json.loads(sync_enabled_setting.value)

        if sync_enabled:
            # Get global interval setting (can be overridden per-release in future)
            interval_setting = db.query(AppSettings).filter(
                AppSettings.key == 'METADATA_SYNC_INTERVAL_HOURS'
            ).first()

            interval_hours = 24.0  # Default
            if interval_setting:
                import json
                interval_hours = float(json.loads(interval_setting.value))

            # Schedule sync job for each active release with git_branch configured
            from app.models.db_models import Release
            from app.tasks.metadata_sync_poller import run_metadata_sync_for_release

            releases = db.query(Release).filter(
                Release.is_active == True,
                Release.git_branch.isnot(None)  # Only releases with git_branch
            ).all()

            for release in releases:
                logger.info(f"Scheduling metadata sync for {release.name} (branch: {release.git_branch}, interval: {interval_hours}h)")

                scheduler.add_job(
                    run_metadata_sync_for_release,
                    trigger=IntervalTrigger(hours=interval_hours),
                    id=f'metadata_sync_{release.id}',  # Unique per release
                    replace_existing=True,
                    max_instances=1,
                    name=f'Metadata Sync - {release.name}',
                    kwargs={'release_id': release.id, 'sync_type': 'scheduled'}
                )

            if not releases:
                logger.warning("No active releases with git_branch configured for metadata sync")

    # Add bug updater job (daily at 2 AM)
    logger.info("Adding bug updater job (daily at 2 AM)")
    scheduler.add_job(
        update_bugs_task,
        trigger=CronTrigger(hour=2, minute=0),  # 2 AM daily
        id='bug_updater',
        replace_existing=True,
        max_instances=1,
        name='Bug Mappings Updater'
    )

    scheduler.start()
    logger.info("Scheduler started with Jenkins poller and bug updater")


def stop_scheduler():
    """
    Stop the APScheduler instance.

    This is called during FastAPI lifespan shutdown.
    """
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")


def update_polling_schedule(enabled: bool, interval_hours: float):
    """
    Update the polling schedule dynamically.

    Args:
        enabled: Whether polling should be enabled
        interval_hours: Polling interval in hours (can be fractional, e.g. 0.5 = 30 min)
    """
    from app.tasks.jenkins_poller import poll_jenkins_for_all_releases

    if enabled:
        logger.info(f"Updating polling schedule: enabled, interval={interval_hours}h")

        # Remove existing job if present
        if scheduler.get_job('jenkins_poller'):
            scheduler.remove_job('jenkins_poller')

        # Add new job with updated interval
        scheduler.add_job(
            poll_jenkins_for_all_releases,
            trigger=IntervalTrigger(hours=interval_hours),
            id='jenkins_poller',
            replace_existing=True,
            max_instances=1,
            name='Jenkins Polling Task'
        )
    else:
        logger.info("Disabling polling schedule")

        # Remove job if present
        if scheduler.get_job('jenkins_poller'):
            scheduler.remove_job('jenkins_poller')


def update_metadata_sync_schedule(enabled: bool, interval_hours: float, release_id: int = None):
    """
    Update metadata sync schedule dynamically for all releases or a specific release.

    Args:
        enabled: Whether metadata sync should be enabled
        interval_hours: Sync interval in hours
        release_id: Optional release ID to update specific release (None = all releases)
    """
    from app.tasks.metadata_sync_poller import run_metadata_sync_for_release
    from app.database import get_db_context
    from app.models.db_models import Release

    if release_id:
        # Update single release
        job_id = f'metadata_sync_{release_id}'

        if enabled:
            with get_db_context() as db:
                release = db.query(Release).filter(Release.id == release_id).first()
                if not release or not release.git_branch:
                    logger.warning(f"Release {release_id} not found or has no git_branch")
                    return

                logger.info(f"Updating metadata sync for {release.name}: enabled, interval={interval_hours}h")

                # Remove existing job if present
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)

                # Add new job with updated interval
                scheduler.add_job(
                    run_metadata_sync_for_release,
                    trigger=IntervalTrigger(hours=interval_hours),
                    id=job_id,
                    replace_existing=True,
                    max_instances=1,
                    name=f'Metadata Sync - {release.name}',
                    kwargs={'release_id': release_id, 'sync_type': 'scheduled'}
                )
        else:
            logger.info(f"Disabling metadata sync for release {release_id}")

            # Remove job if present
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
    else:
        # Update all releases
        with get_db_context() as db:
            releases = db.query(Release).filter(
                Release.is_active == True,
                Release.git_branch.isnot(None)
            ).all()

            for release in releases:
                update_metadata_sync_schedule(enabled, interval_hours, release.id)


def get_scheduler_status() -> dict:
    """
    Get current scheduler status.

    Returns:
        Dict with scheduler info
    """
    job = scheduler.get_job('jenkins_poller')

    if job:
        next_run = job.next_run_time
        return {
            'running': scheduler.running,
            'job_enabled': True,
            'next_run': next_run.isoformat() if next_run else None,
            'job_name': job.name
        }
    else:
        return {
            'running': scheduler.running,
            'job_enabled': False,
            'next_run': None,
            'job_name': None
        }
