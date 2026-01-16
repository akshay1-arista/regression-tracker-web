"""
Jenkins Service - Wraps existing jenkins_downloader.py for web application use.

Provides:
- Manual Jenkins download with progress logging
- New build detection (compares build_map with database)
- Background polling integration
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.auth import HTTPBasicAuth
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Release, Module, Job


logger = logging.getLogger(__name__)


class JenkinsClient:
    """
    Handles Jenkins REST API interactions.

    Use as context manager for proper resource cleanup:
        with JenkinsClient(url, user, token) as client:
            client.download_artifact(...)
    """

    def __init__(self, url: str, user: str, api_token: str):
        """
        Initialize Jenkins client.

        Args:
            url: Jenkins server URL
            user: Jenkins username
            api_token: Jenkins API token
        """
        self.url = url.rstrip('/')
        self.auth = HTTPBasicAuth(user, api_token)
        self.session = requests.Session()
        self.session.auth = self.auth

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up session."""
        self.close()
        return False

    def close(self):
        """Close the requests session to free resources."""
        if hasattr(self, 'session') and self.session:
            self.session.close()

    def _make_request(self, url: str, max_retries: int = 3) -> requests.Response:
        """
        Make HTTP request with retry logic.

        Args:
            url: URL to request
            max_retries: Maximum number of retry attempts

        Returns:
            Response object

        Raises:
            requests.RequestException: If request fails after retries
        """
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                if response.status_code == 401:
                    raise Exception("Authentication failed. Check your Jenkins credentials.") from e
                elif response.status_code == 404:
                    raise Exception(f"Job not found: {url}") from e
                else:
                    raise
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Request failed, retrying in {wait_time}s... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Request failed after {max_retries} attempts: {url}") from e

    def get_artifacts_list(self, job_url: str) -> List[Dict]:
        """
        Get list of artifacts for a Jenkins job.

        Args:
            job_url: Jenkins job URL

        Returns:
            List of artifact dictionaries with 'relativePath' and 'fileName'
        """
        job_url = job_url.rstrip('/')
        api_url = f"{job_url}/api/json?tree=artifacts[relativePath,fileName]"

        logger.debug(f"Getting artifacts list from: {api_url}")
        response = self._make_request(api_url)
        data = response.json()

        return data.get('artifacts', [])

    def download_artifact(self, job_url: str, relative_path: str, dest_path: str) -> bool:
        """
        Download a single artifact from Jenkins.

        Args:
            job_url: Jenkins job URL
            relative_path: Relative path of artifact within job
            dest_path: Local destination path

        Returns:
            True if download successful, False otherwise
        """
        job_url = job_url.rstrip('/')
        artifact_url = f"{job_url}/artifact/{relative_path}"

        try:
            logger.debug(f"Downloading: {relative_path}")
            response = self._make_request(artifact_url)

            # Create parent directories if needed
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            # Write artifact to file
            with open(dest_path, 'wb') as f:
                f.write(response.content)

            return True
        except Exception as e:
            logger.error(f"Failed to download {relative_path}: {e}")
            return False

    def get_job_builds(self, job_url: str, min_build: int = 0) -> List[int]:
        """
        Get list of all build numbers for a Jenkins job.

        Args:
            job_url: Jenkins job URL (without build number)
            min_build: Only return builds greater than this number

        Returns:
            List of build numbers, sorted descending (newest first)
        """
        job_url = job_url.rstrip('/')
        api_url = f"{job_url}/api/json?tree=builds[number]"

        logger.debug(f"Getting builds from: {api_url}")
        response = self._make_request(api_url)
        data = response.json()

        builds = data.get('builds', [])
        build_numbers = [b['number'] for b in builds if b['number'] > min_build]

        # Sort descending (newest first)
        build_numbers.sort(reverse=True)

        logger.info(f"Found {len(build_numbers)} builds (> {min_build})")
        return build_numbers

    def get_job_info(self, job_url: str) -> Dict:
        """
        Get job information including displayName (title).

        Args:
            job_url: Jenkins job URL (with build number)

        Returns:
            Dict with job info including displayName, url, number, etc.
        """
        job_url = job_url.rstrip('/')
        api_url = f"{job_url}/api/json?tree=displayName,url,number,result,timestamp"

        logger.debug(f"Getting job info from: {api_url}")
        response = self._make_request(api_url)

        return response.json()

    def download_build_map(self, main_job_url: str) -> Optional[Dict]:
        """
        Download and parse build_map.json from main job.

        Args:
            main_job_url: Main Jenkins job URL (with build number)

        Returns:
            Parsed build_map.json as dict, or None if not found
        """
        artifacts = self.get_artifacts_list(main_job_url)

        # Find build_map.json
        build_map_artifact = None
        for artifact in artifacts:
            if artifact['fileName'] == 'build_map.json':
                build_map_artifact = artifact
                break

        if not build_map_artifact:
            logger.warning("build_map.json not found in main job artifacts")
            return None

        # Download to temporary location
        job_url = main_job_url.rstrip('/')
        artifact_url = f"{job_url}/artifact/{build_map_artifact['relativePath']}"

        logger.info("Downloading build_map.json...")
        response = self._make_request(artifact_url)

        return response.json()


class ArtifactDownloader:
    """Orchestrates artifact downloading for regression tracker."""

    def __init__(self, client: JenkinsClient, logs_base_path: str, log_callback: Optional[Callable[[str], None]] = None):
        """
        Initialize artifact downloader.

        Args:
            client: JenkinsClient instance
            logs_base_path: Base path for logs directory
            log_callback: Optional callback function for progress logging (for SSE)
        """
        self.client = client
        self.logs_base = logs_base_path
        self.log_callback = log_callback

    def _log(self, message: str):
        """Log message using callback if available, otherwise use logger."""
        if self.log_callback:
            self.log_callback(message)
        else:
            logger.info(message)

    def download_for_release(
        self,
        main_job_url: str,
        release: str,
        skip_existing: bool = False
    ) -> Dict[str, str]:
        """
        Download all artifacts for a release.

        Args:
            main_job_url: Main Jenkins job URL (MODULE-RUN-ESXI-IPV4-ALL)
            release: Release version (e.g., "7.0.0.0")
            skip_existing: Skip download if files already exist

        Returns:
            Dict mapping module -> job_id
        """
        # Download build_map.json
        self._log(f"Downloading build_map.json for release {release}...")
        build_map = self.client.download_build_map(main_job_url)
        if not build_map:
            self._log("ERROR: Failed to download build_map.json")
            return {}

        # Parse build_map to extract module job information
        module_jobs = parse_build_map(build_map, main_job_url)
        self._log(f"Found {len(module_jobs)} modules in build_map.json")

        # Download artifacts for each module in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_module = {
                executor.submit(
                    self._download_module_artifacts,
                    module,
                    job_url,
                    job_id,
                    release,
                    skip_existing
                ): module
                for module, (job_url, job_id) in module_jobs.items()
            }

            for future in as_completed(future_to_module):
                module = future_to_module[future]
                try:
                    job_id = future.result()
                    if job_id:
                        results[module] = job_id
                except Exception as e:
                    self._log(f"ERROR downloading artifacts for {module}: {e}")

        return results

    def _download_module_artifacts(
        self,
        module: str,
        job_url: str,
        job_id: str,
        release: str,
        skip_existing: bool
    ) -> Optional[str]:
        """
        Download artifacts for a single module.

        Args:
            module: Module name (e.g., "business_policy")
            job_url: Module job URL
            job_id: Job number
            release: Release version
            skip_existing: Skip if files already exist

        Returns:
            Job ID if successful, None otherwise
        """
        self._log(f"Downloading {module} (job {job_id})...")

        # Create destination directory
        dest_dir = os.path.join(self.logs_base, release, module, job_id)

        # Check if already exists and skip if requested
        if skip_existing and os.path.exists(dest_dir):
            existing_files = list(Path(dest_dir).rglob('*.order.txt'))
            if existing_files:
                self._log(f"  Skipping {module} (already exists)")
                return job_id

        os.makedirs(dest_dir, exist_ok=True)

        # Get all artifacts
        artifacts = self.client.get_artifacts_list(job_url)

        # Filter for .order.txt files and junit XML files
        order_txt_files = [
            a for a in artifacts
            if a['relativePath'].startswith('hapy/') and a['fileName'].endswith('.order.txt')
        ]
        junit_files = [
            a for a in artifacts
            if a['relativePath'].startswith('hapy/reports/junit/') and a['fileName'].endswith('.xml')
        ]

        # Download .order.txt files
        order_count = 0
        for artifact in order_txt_files:
            filename = artifact['fileName']
            dest_path = os.path.join(dest_dir, filename)

            if self.client.download_artifact(job_url, artifact['relativePath'], dest_path):
                order_count += 1

        # Download junit files
        junit_count = 0
        for artifact in junit_files:
            relative_path = artifact['relativePath']

            # Strip 'hapy/reports/' prefix to get 'junit/<topology>/<file>.xml'
            if relative_path.startswith('hapy/reports/'):
                relative_junit_path = relative_path[13:]
            else:
                relative_junit_path = relative_path

            dest_path = os.path.join(dest_dir, relative_junit_path)

            if self.client.download_artifact(job_url, artifact['relativePath'], dest_path):
                junit_count += 1

        self._log(f"  Downloaded {order_count} .order.txt files")
        self._log(f"  Downloaded {junit_count} junit XML files")

        return job_id if (order_count > 0 or junit_count > 0) else None


def parse_build_map(build_map_json: Dict, main_job_url: str) -> Dict[str, Tuple[str, str]]:
    """
    Parse build_map.json to extract module job information.

    Args:
        build_map_json: Parsed build_map.json content
        main_job_url: Main job URL to construct module job URLs

    Returns:
        Dict mapping module_name -> (job_url, job_number)
    """
    module_jobs = {}

    # Extract base URL from main job URL
    base_url_match = re.match(r'(.*)/job/[^/]+/\d+/?$', main_job_url.rstrip('/'))
    if not base_url_match:
        logger.error(f"Could not parse main job URL: {main_job_url}")
        return module_jobs

    base_url = base_url_match.group(1)

    # Parse build_map structure: {"MODULE_JOB_NAME": job_id_int, ...}
    for job_name, job_id in build_map_json.items():
        job_id_str = str(job_id)

        # Construct full job URL
        jenkins_job_name = job_name.replace('_', '-')
        job_url = f"{base_url}/job/{jenkins_job_name}/{job_id_str}/"

        # Normalize module name
        module_name = normalize_module_name(job_name)

        module_jobs[module_name] = (job_url, job_id_str)

    return module_jobs


def normalize_module_name(job_key: str) -> str:
    """
    Normalize Jenkins job key to module name.

    Args:
        job_key: Key from build_map.json (e.g., "BUSINESS_POLICY_ESXI")

    Returns:
        Normalized module name (e.g., "business_policy")
    """
    normalized = job_key.lower().replace('-', '_')

    # Remove common suffixes
    for suffix in ['_esxi', '_module_esxi', '_module']:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
            break

    return normalized


def extract_version_from_title(job_title: str) -> Optional[str]:
    """
    Extract version from Jenkins job title.

    Args:
        job_title: Jenkins job displayName
                   (e.g., "REL: Release_7.0 | VER: 7.0.0.0 | MOD: FULL-RUN | PRIO: ALL | master")

    Returns:
        Version string (e.g., "7.0.0.0") or None if not found
    """
    # Pattern to match "VER: X.X.X.X"
    version_pattern = r'VER:\s*(\d+\.\d+\.\d+\.\d+)'
    match = re.search(version_pattern, job_title)

    if match:
        return match.group(1)

    logger.debug(f"No version found in job title: {job_title}")
    return None


def detect_new_builds(db: Session, release_name: str, build_map: Dict) -> List[Tuple[str, str, str]]:
    """
    Detect new builds by comparing build_map with database.

    Args:
        db: Database session
        release_name: Release name (e.g., "7.0.0.0")
        build_map: Parsed build_map.json

    Returns:
        List of (module_name, job_url, job_id) for new builds
    """
    new_builds = []

    # Get release from database
    release = db.query(Release).filter(Release.name == release_name).first()
    if not release:
        logger.warning(f"Release {release_name} not found in database")
        return new_builds

    # Parse build_map to get module jobs
    # (We don't have main_job_url here, so we'll skip URL construction)
    for job_name, job_id in build_map.items():
        job_id_str = str(job_id)
        module_name = normalize_module_name(job_name)

        # Check if module exists
        module = db.query(Module).filter(
            Module.release_id == release.id,
            Module.name == module_name
        ).first()

        if not module:
            # Module doesn't exist in database - this is a new module
            logger.info(f"New module detected: {module_name}")
            new_builds.append((module_name, "", job_id_str))
            continue

        # Check if job exists
        job = db.query(Job).filter(
            Job.module_id == module.id,
            Job.job_id == job_id_str
        ).first()

        if not job:
            # Job doesn't exist - this is a new build
            logger.info(f"New build detected: {module_name} job {job_id_str}")
            new_builds.append((module_name, "", job_id_str))

    return new_builds
