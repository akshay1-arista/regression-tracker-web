"""
Cleanup utilities for artifact management.

Provides functions to delete downloaded artifacts after they've been imported to the database.
"""
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def cleanup_artifacts(
    logs_base_path: str,
    release_name: str,
    module_name: str,
    job_id: str
) -> bool:
    """
    Delete downloaded artifacts after they've been imported to database.

    This saves disk space by removing the raw JUnit XML files and .order.txt files
    once they've been parsed and stored in the database.

    Args:
        logs_base_path: Base logs directory path
        release_name: Release name (e.g., "7.0.0.0")
        module_name: Module name (e.g., "business_policy")
        job_id: Job ID (e.g., "8")

    Returns:
        True if cleanup successful, False otherwise
    """
    job_dir = Path(logs_base_path) / release_name / module_name / job_id

    if not job_dir.exists():
        logger.warning(f"Cleanup: Directory does not exist: {job_dir}")
        return False

    try:
        # Delete the entire job directory
        shutil.rmtree(job_dir)
        logger.info(f"Cleaned up artifacts: {release_name}/{module_name}/{job_id}")

        # Try to clean up empty parent directories
        _cleanup_empty_parents(job_dir.parent)

        return True
    except Exception as e:
        logger.error(f"Failed to cleanup artifacts at {job_dir}: {e}")
        return False


def _cleanup_empty_parents(directory: Path, max_levels: int = 2):
    """
    Recursively remove empty parent directories.

    Args:
        directory: Starting directory
        max_levels: Maximum number of parent levels to check
    """
    for _ in range(max_levels):
        if not directory.exists():
            break

        try:
            # Only remove if directory is empty
            if not any(directory.iterdir()):
                directory.rmdir()
                logger.debug(f"Removed empty directory: {directory}")
                directory = directory.parent
            else:
                # Directory not empty, stop
                break
        except (OSError, PermissionError) as e:
            logger.debug(f"Could not remove directory {directory}: {e}")
            break
