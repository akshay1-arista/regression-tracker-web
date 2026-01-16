"""
Jenkins Background Polling Task.

Automatically polls Jenkins for new builds and imports them to the database.
"""
import logging
import json
from datetime import datetime
from typing import List, Tuple

import requests

from app.database import get_db_context
from app.models.db_models import Release, Module, Job, JenkinsPollingLog, AppSettings
from app.services.jenkins_service import JenkinsClient, ArtifactDownloader, detect_new_builds
from app.services.import_service import ImportService
from app.config import get_settings
from app.utils.security import CredentialsManager


logger = logging.getLogger(__name__)


async def poll_jenkins_for_all_releases():
    """
    Poll Jenkins for all active releases and import new builds.

    This function runs as a scheduled background task.
    """
    logger.info("Starting Jenkins polling cycle...")

    with get_db_context() as db:
        # Get all active releases
        active_releases = db.query(Release).filter(Release.is_active == True).all()

        if not active_releases:
            logger.info("No active releases found, skipping poll")
            return

        logger.info(f"Polling {len(active_releases)} active releases")

        for release in active_releases:
            try:
                await poll_release(db, release)
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error polling release {release.name}: {e}", exc_info=True)
                # Log failure but continue with other releases
                log_polling_result(db, release.id, 'failed', 0, str(e))
            except Exception as e:
                # Unexpected errors should be logged as critical
                logger.critical(f"Unexpected error polling release {release.name}: {e}", exc_info=True)
                log_polling_result(db, release.id, 'failed', 0, f"Unexpected error: {str(e)}")

    logger.info("Jenkins polling cycle completed")


async def poll_release(db, release: Release):
    """
    Poll Jenkins for a single release and import new builds.

    Checks for new MAIN JOB builds (e.g., job 15, 16, 17) and imports
    all module jobs from each new main job build.

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

    # Get Jenkins credentials from environment variables (secure)
    try:
        jenkins_url, jenkins_user, jenkins_token = CredentialsManager.get_jenkins_credentials()
    except ValueError as e:
        logger.error(f"Jenkins credentials not configured: {e}")
        log_polling_result(db, release.id, 'failed', 0, "Jenkins credentials not configured")
        return

    # Create Jenkins client with context manager for proper resource cleanup
    with JenkinsClient(jenkins_url, jenkins_user, jenkins_token) as client:
        try:
            # Get list of ALL builds for the main job
            # (e.g., [17, 16, 15, 14, ...])
            all_builds = client.get_job_builds(
                release.jenkins_job_url,
                min_build=release.last_processed_build or 0
            )

            if not all_builds:
                logger.info(f"No new builds found for {release.name} (last processed: {release.last_processed_build})")
                log_polling_result(db, release.id, 'success', 0, None)
                return

            logger.info(f"Found {len(all_builds)} new main job builds for {release.name}: {all_builds}")

            # Download artifacts for new builds
            downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH)

            total_modules_downloaded = 0

            # Process each new main job build
            for main_build_num in reversed(all_builds):  # Process oldest first
                logger.info(f"Processing main job build {main_build_num}...")

                # Construct main job build URL
                main_build_url = f"{release.jenkins_job_url.rstrip('/')}/{main_build_num}/"

                # Download build_map.json from this specific build
                build_map = client.download_build_map(main_build_url)

                if not build_map:
                    logger.warning(f"Failed to download build_map.json from build {main_build_num}, skipping")
                    continue

                # Parse build_map to get module jobs
                from app.services.jenkins_service import parse_build_map
                module_jobs = parse_build_map(build_map, main_build_url)

                logger.info(f"Found {len(module_jobs)} modules in build {main_build_num}")

                # Download and import each module job
                for module_name, (job_url, job_id) in module_jobs.items():
                    try:
                        logger.info(f"  Downloading {module_name} job {job_id}...")

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

                        # Check if already exists
                        existing_job = db.query(Job).filter(
                            Job.module_id == module.id,
                            Job.job_id == job_id
                        ).first()

                        if existing_job:
                            logger.info(f"  Job {module_name}/{job_id} already exists, skipping")
                            continue

                        # Fetch job info from Jenkins to get displayName (version)
                        version = None
                        try:
                            job_info = client.get_job_info(job_url)
                            display_name = job_info.get('displayName', '')
                            if display_name:
                                from app.services.jenkins_service import extract_version_from_title
                                version = extract_version_from_title(display_name)
                                logger.debug(f"  Extracted version: {version} from: {display_name}")
                        except Exception as e:
                            logger.warning(f"  Failed to fetch job info for version: {e}")

                        # Download artifacts
                        result = downloader._download_module_artifacts(
                            module_name,
                            job_url,
                            job_id,
                            release.name,
                            skip_existing=True
                        )

                        if result:
                            # Import to database with version and parent job ID
                            import_service = ImportService(db)
                            import_service.import_job(
                                release.name,
                                module_name,
                                job_id,
                                jenkins_url=job_url,
                                version=version,
                                parent_job_id=str(main_build_num)
                            )

                            total_modules_downloaded += 1
                            logger.info(f"  Successfully imported {module_name} job {job_id} (version: {version})")

                    except (requests.RequestException, ValueError) as e:
                        logger.error(f"Error downloading/importing {module_name} job {job_id}: {e}")
                        # Continue with next module
                    except Exception as e:
                        logger.critical(f"Unexpected error downloading {module_name} job {job_id}: {e}", exc_info=True)
                        # Continue with next module

                # Update last_processed_build after successfully processing this main build
                release.last_processed_build = main_build_num
                db.commit()
                logger.info(f"Updated last_processed_build to {main_build_num}")

            # Log success
            log_polling_result(db, release.id, 'success', total_modules_downloaded, None)
            logger.info(f"Polling completed for {release.name}: {total_modules_downloaded} modules imported from {len(all_builds)} main job builds")

        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error(f"Error during polling for {release.name}: {e}", exc_info=True)
            log_polling_result(db, release.id, 'failed', 0, str(e))
        except Exception as e:
            logger.critical(f"Unexpected error during polling for {release.name}: {e}", exc_info=True)
            log_polling_result(db, release.id, 'failed', 0, f"Unexpected error: {str(e)}")


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
