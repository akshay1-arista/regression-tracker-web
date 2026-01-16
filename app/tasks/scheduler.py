"""
Background Task Scheduler using APScheduler.

Manages scheduled tasks for automatic Jenkins polling.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.database import SessionLocal
from app.models.db_models import AppSettings


logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


def start_scheduler():
    """
    Start the APScheduler instance.

    This is called during FastAPI lifespan startup.
    """
    settings = get_settings()

    # Import here to avoid circular imports
    from app.tasks.jenkins_poller import poll_jenkins_for_all_releases

    # Check if auto-update is enabled
    db = SessionLocal()
    try:
        auto_update_setting = db.query(AppSettings).filter(
            AppSettings.key == 'AUTO_UPDATE_ENABLED'
        ).first()

        auto_update_enabled = True  # Default
        if auto_update_setting:
            import json
            auto_update_enabled = json.loads(auto_update_setting.value)

        if auto_update_enabled:
            # Get polling interval
            interval_setting = db.query(AppSettings).filter(
                AppSettings.key == 'POLLING_INTERVAL_MINUTES'
            ).first()

            interval_minutes = 15  # Default
            if interval_setting:
                import json
                interval_minutes = json.loads(interval_setting.value)

            logger.info(f"Starting Jenkins polling scheduler (interval: {interval_minutes} minutes)")

            scheduler.add_job(
                poll_jenkins_for_all_releases,
                trigger=IntervalTrigger(minutes=interval_minutes),
                id='jenkins_poller',
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
                name='Jenkins Polling Task'
            )
        else:
            logger.info("Auto-update disabled, scheduler not started")
    finally:
        db.close()

    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    """
    Stop the APScheduler instance.

    This is called during FastAPI lifespan shutdown.
    """
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")


def update_polling_schedule(enabled: bool, interval_minutes: int):
    """
    Update the polling schedule dynamically.

    Args:
        enabled: Whether polling should be enabled
        interval_minutes: Polling interval in minutes
    """
    from app.tasks.jenkins_poller import poll_jenkins_for_all_releases

    if enabled:
        logger.info(f"Updating polling schedule: enabled, interval={interval_minutes}m")

        # Remove existing job if present
        if scheduler.get_job('jenkins_poller'):
            scheduler.remove_job('jenkins_poller')

        # Add new job with updated interval
        scheduler.add_job(
            poll_jenkins_for_all_releases,
            trigger=IntervalTrigger(minutes=interval_minutes),
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
