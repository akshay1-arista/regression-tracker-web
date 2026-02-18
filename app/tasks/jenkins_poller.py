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
    Poll Jenkins unified parent job and route modules to releases by version.

    UNIFIED PARENT JOB ARCHITECTURE:
    All releases (7.0, 6.4, 6.1) share the same jenkins_job_url pointing to
    a unified parent job. Each module job within a build may have different
    versions, so we extract version from each module's displayName and route
    it to the correct release.

    Checks for new MAIN JOB builds (e.g., job 15, 16, 17) and imports
    all module jobs, routing them to the appropriate release based on version.

    Args:
        db: Database session
        release: Release object (used to get unified parent URL)
    """
    started_at = datetime.utcnow()

    # Get all active releases for unified processing
    active_releases = db.query(Release).filter(Release.is_active == True).all()

    if not active_releases:
        logger.info("No active releases found, skipping poll")
        return

    # Use unified parent URL (all releases should share same URL)
    unified_parent_url = release.jenkins_job_url

    if not unified_parent_url:
        logger.warning(f"Release {release.name} has no Jenkins job URL configured, skipping")
        log_polling_result(db, release.id, 'failed', 0, "No Jenkins job URL configured")
        return

    # Calculate min_build across all releases to avoid missing any
    min_build = min((r.last_processed_build or 0) for r in active_releases)

    logger.info(f"Polling unified parent (min_build={min_build} across {len(active_releases)} active releases)")
    logger.info(f"Active releases: {', '.join([r.name for r in active_releases])}")

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
            # Get list of ALL builds for the unified parent job
            all_builds = client.get_job_builds(
                unified_parent_url,
                min_build=min_build
            )

            if not all_builds:
                logger.info(f"No new builds found for unified parent (last processed: {min_build})")
                log_polling_result(db, release.id, 'success', 0, None)
                return

            logger.info(f"Found {len(all_builds)} new main job builds: {all_builds}")

            # Download artifacts for new builds
            downloader = ArtifactDownloader(client, settings.LOGS_BASE_PATH)

            # Track modules downloaded per release
            modules_by_release = {}  # release_name -> count

            # Process each new main job build
            for main_build_num in reversed(all_builds):  # Process oldest first
                logger.info(f"Processing main job build {main_build_num}...")

                # Construct main job build URL
                main_build_url = f"{unified_parent_url.rstrip('/')}/{main_build_num}/"

                # Download build_map.json from this specific build
                build_map = client.download_build_map(main_build_url)

                if not build_map:
                    logger.warning(f"Failed to download build_map.json from build {main_build_num}, skipping")
                    continue

                # Parse build_map to get module jobs
                from app.services.jenkins_service import parse_build_map, extract_module_metadata, map_version_to_release
                from app.services.import_service import get_or_create_release
                module_jobs = parse_build_map(build_map, main_build_url)

                logger.info(f"Build {main_build_num}: Found {len(module_jobs)} modules")

                # Extract parent build version as fallback (if module version unavailable)
                parent_version = None
                try:
                    parent_build_info = client.get_job_info(main_build_url)
                    parent_display_name = parent_build_info.get('displayName', '')
                    if parent_display_name:
                        from app.services.jenkins_service import extract_version_from_title
                        parent_version = extract_version_from_title(parent_display_name)
                        if parent_version:
                            logger.debug(f"Parent build {main_build_num} version: {parent_version}")
                except Exception as e:
                    logger.debug(f"Could not extract parent build version: {e}")

                # Download and import each module job
                for module_name, (job_url, job_id) in module_jobs.items():
                    try:
                        # Extract version and timestamp from module job
                        version, executed_at = extract_module_metadata(client, job_url, module_name)

                        # FALLBACK STRATEGY: If module version unavailable, use parent build version
                        if not version and parent_version:
                            logger.info(f"  {module_name}: Using parent build version {parent_version} (module version unavailable)")
                            version = parent_version

                        if not version:
                            logger.error(f"  {module_name}: No version available (module and parent both failed), skipping")
                            continue

                        # Map version to release name
                        release_name = map_version_to_release(version)

                        if not release_name:
                            logger.error(f"  {module_name}: Version {version} → no release mapping, skipping")
                            continue

                        logger.info(f"  {module_name}: version={version} → release={release_name}")

                        # Get or auto-create release (auto-creation happens here)
                        target_release = get_or_create_release(db, release_name, unified_parent_url)

                        # Get or create module under correct release
                        module = db.query(Module).filter(
                            Module.release_id == target_release.id,
                            Module.name == module_name
                        ).first()

                        if not module:
                            module = Module(
                                release_id=target_release.id,
                                name=module_name
                            )
                            db.add(module)
                            db.commit()
                            db.refresh(module)

                        # Check if job already exists
                        existing_job = db.query(Job).filter(
                            Job.module_id == module.id,
                            Job.job_id == job_id
                        ).first()

                        if existing_job:
                            logger.info(f"  Job {release_name}/{module_name}/{job_id} already exists, skipping")
                            # Still count as success
                            if release_name not in modules_by_release:
                                modules_by_release[release_name] = 0
                            modules_by_release[release_name] += 1
                            continue

                        # Download artifacts
                        result = downloader._download_module_artifacts(
                            module_name,
                            job_url,
                            job_id,
                            release_name,  # Use mapped release, not original
                            skip_existing=True
                        )

                        if result:
                            # Import to database with version and parent job ID
                            import_service = ImportService(db)
                            import_service.import_job(
                                release_name,  # Use mapped release
                                module_name,
                                job_id,
                                jenkins_url=job_url,
                                version=version,
                                parent_job_id=str(main_build_num),
                                executed_at=executed_at
                            )

                            # Cleanup artifacts after successful import to save disk space
                            if settings.CLEANUP_ARTIFACTS_AFTER_IMPORT:
                                from app.utils.cleanup import cleanup_artifacts
                                cleanup_artifacts(settings.LOGS_BASE_PATH, release_name, module_name, job_id)

                            # Track success per release
                            if release_name not in modules_by_release:
                                modules_by_release[release_name] = 0
                            modules_by_release[release_name] += 1

                            logger.info(f"  Successfully imported {release_name}/{module_name} job {job_id}")

                    except (requests.RequestException, ValueError) as e:
                        logger.error(f"Error downloading/importing {module_name} job {job_id}: {e}")
                        # Continue with next module
                    except Exception as e:
                        logger.critical(f"Unexpected error downloading {module_name} job {job_id}: {e}", exc_info=True)
                        # Continue with next module

                # Update last_processed_build for ALL active releases
                # (they share same parent, so all advance together)
                for active_release in active_releases:
                    active_release.last_processed_build = main_build_num
                    db.commit()

                logger.info(f"Updated all releases to build {main_build_num}")

            # Log final summary per release
            total_modules = sum(modules_by_release.values())
            logger.info(f"Polling complete: {total_modules} total modules imported")
            for release_name, count in modules_by_release.items():
                logger.info(f"  {release_name}: {count} modules")

            # Log success (use original release for tracking)
            log_polling_result(db, release.id, 'success', total_modules, None)

        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error(f"Error during polling: {e}", exc_info=True)
            log_polling_result(db, release.id, 'failed', 0, str(e))
        except Exception as e:
            logger.critical(f"Unexpected error during polling: {e}", exc_info=True)
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
