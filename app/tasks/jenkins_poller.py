"""
Jenkins Background Polling Task.

Automatically polls Jenkins for new builds and imports them to the database.
"""
import logging
import json
from datetime import datetime
from typing import List, Tuple

from app.database import SessionLocal
from app.models.db_models import Release, Module, Job, JenkinsPollingLog, AppSettings
from app.services.jenkins_service import JenkinsClient, ArtifactDownloader, detect_new_builds
from app.services.import_service import ImportService
from app.config import get_settings


logger = logging.getLogger(__name__)


async def poll_jenkins_for_all_releases():
    """
    Poll Jenkins for all active releases and import new builds.

    This function runs as a scheduled background task.
    """
    logger.info("Starting Jenkins polling cycle...")

    db = SessionLocal()
    try:
        # Get all active releases
        active_releases = db.query(Release).filter(Release.is_active == True).all()

        if not active_releases:
            logger.info("No active releases found, skipping poll")
            return

        logger.info(f"Polling {len(active_releases)} active releases")

        for release in active_releases:
            try:
                await poll_release(db, release)
            except Exception as e:
                logger.error(f"Error polling release {release.name}: {e}", exc_info=True)
                # Log failure but continue with other releases
                log_polling_result(db, release.id, 'failed', 0, str(e))

    finally:
        db.close()

    logger.info("Jenkins polling cycle completed")


async def poll_release(db, release: Release):
    """
    Poll Jenkins for a single release and import new builds.

    Args:
        db: Database session
        release: Release object
    """
    started_at = datetime.utcnow()
    logger.info(f"Polling release: {release.name}")

    # Check if release has Jenkins job URL configured
    if not release.jenkins_job_url:
        logger.warning(f"Release {release.name} has no Jenkins job URL configured, skipping")
        return

    settings = get_settings()

    # Get Jenkins credentials from app settings
    jenkins_url_setting = db.query(AppSettings).filter(
        AppSettings.key == 'JENKINS_URL'
    ).first()
    jenkins_user_setting = db.query(AppSettings).filter(
        AppSettings.key == 'JENKINS_USER'
    ).first()
    jenkins_token_setting = db.query(AppSettings).filter(
        AppSettings.key == 'JENKINS_API_TOKEN'
    ).first()

    if not all([jenkins_url_setting, jenkins_user_setting, jenkins_token_setting]):
        logger.error("Jenkins credentials not configured in app settings")
        log_polling_result(db, release.id, 'failed', 0, "Jenkins credentials not configured")
        return

    # Create Jenkins client
    jenkins_url = json.loads(jenkins_url_setting.value)
    jenkins_user = json.loads(jenkins_user_setting.value)
    jenkins_token = json.loads(jenkins_token_setting.value)

    client = JenkinsClient(jenkins_url, jenkins_user, jenkins_token)

    try:
        # Download build_map.json
        build_map = client.download_build_map(release.jenkins_job_url)

        if not build_map:
            logger.warning(f"Failed to download build_map.json for {release.name}")
            log_polling_result(db, release.id, 'failed', 0, "Failed to download build_map.json")
            return

        # Detect new builds
        new_builds = detect_new_builds(db, release.name, build_map)

        if not new_builds:
            logger.info(f"No new builds found for {release.name}")
            log_polling_result(db, release.id, 'success', 0, None)
            return

        logger.info(f"Found {len(new_builds)} new builds for {release.name}")

        # Download artifacts for new builds
        downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH)

        modules_downloaded = 0
        for module_name, job_url, job_id in new_builds:
            try:
                logger.info(f"Downloading {module_name} job {job_id}...")

                # Get or create module
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
                    db.commit()
                    db.refresh(module)

                # Construct job URL from build_map info
                # This is simplified - in real usage, parse_build_map would provide full URLs
                # For now, we'll download using the main job URL pattern
                from app.services.jenkins_service import parse_build_map
                module_jobs = parse_build_map(build_map, release.jenkins_job_url)

                if module_name in module_jobs:
                    job_url, _ = module_jobs[module_name]

                    # Download artifacts
                    result = downloader._download_module_artifacts(
                        module_name,
                        job_url,
                        job_id,
                        release.name,
                        skip_existing=True
                    )

                    if result:
                        # Import to database
                        import_service = ImportService(db)
                        import_service.import_job(release.name, module_name, job_id)

                        modules_downloaded += 1
                        logger.info(f"Successfully imported {module_name} job {job_id}")

            except Exception as e:
                logger.error(f"Error downloading/importing {module_name} job {job_id}: {e}")
                # Continue with next module

        # Log success
        log_polling_result(db, release.id, 'success', modules_downloaded, None)
        logger.info(f"Polling completed for {release.name}: {modules_downloaded} modules imported")

    except Exception as e:
        logger.error(f"Error during polling for {release.name}: {e}", exc_info=True)
        log_polling_result(db, release.id, 'failed', 0, str(e))


def log_polling_result(
    db,
    release_id: int,
    status: str,
    modules_downloaded: int,
    error_message: str = None
):
    """
    Log polling result to database.

    Args:
        db: Database session
        release_id: Release ID
        status: 'success', 'failed', or 'partial'
        modules_downloaded: Number of modules successfully downloaded
        error_message: Error message if status is 'failed'
    """
    log_entry = JenkinsPollingLog(
        release_id=release_id,
        status=status,
        modules_downloaded=modules_downloaded,
        error_message=error_message,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow()
    )

    db.add(log_entry)
    db.commit()
