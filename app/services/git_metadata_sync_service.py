"""
Git-based pytest metadata synchronization service.

This service automatically syncs test metadata from a Git repository containing
pytest tests with markers. It extracts metadata from pytest decorators using AST
parsing and updates the database with discovered tests.
"""
import ast
import configparser
import json
import logging
import os
import stat
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from git import Repo
from git.exc import GitCommandError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.db_models import (
    MetadataSyncLog,
    TestcaseMetadata,
    TestcaseMetadataChange,
)

logger = logging.getLogger(__name__)

# Global lock to prevent concurrent Git operations on the same repository
_git_operation_lock = threading.Lock()

# Constants
SYNC_TYPE_MANUAL = "manual"
SYNC_TYPE_SCHEDULED = "scheduled"
SYNC_TYPE_STARTUP = "startup"

SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_FAILED = "failed"
SYNC_STATUS_IN_PROGRESS = "in_progress"

CHANGE_TYPE_ADDED = "added"
CHANGE_TYPE_UPDATED = "updated"
CHANGE_TYPE_REMOVED = "removed"

# Resource limits
MAX_FILE_SIZE_MB = 10  # Max size for AST parsing
MAX_REPO_SIZE_MB = 5000  # Max repository size
GIT_OPERATION_TIMEOUT_SECONDS = 300  # 5 minutes
BATCH_SIZE = 1000  # Database batch size


class GitRepositoryManager:
    """Manages Git repository operations for test discovery."""

    def __init__(
        self,
        repo_url: str,
        local_path: str,
        branch: str = "master",
        ssh_key_path: Optional[str] = None,
        strict_host_key_checking: bool = True,
        timeout: int = GIT_OPERATION_TIMEOUT_SECONDS,
    ):
        """
        Initialize Git repository manager.

        Args:
            repo_url: Git repository URL (SSH or HTTPS)
            local_path: Local path for repository clone
            branch: Branch to track
            ssh_key_path: Optional path to SSH private key
            strict_host_key_checking: Enable SSH host key verification (recommended)
            timeout: Timeout for Git operations in seconds

        Raises:
            ValueError: If configuration is invalid
        """
        self._validate_config(repo_url, ssh_key_path)

        self.repo_url = repo_url
        self.local_path = Path(local_path)
        self.branch = branch
        self.ssh_key_path = ssh_key_path
        self.strict_host_key_checking = strict_host_key_checking
        self.timeout = timeout

        if not strict_host_key_checking:
            logger.warning(
                "SSH host key checking is disabled. "
                "This is insecure and should only be used in development."
            )

    def _validate_config(self, repo_url: str, ssh_key_path: Optional[str]) -> None:
        """
        Validate Git configuration.

        Args:
            repo_url: Git repository URL
            ssh_key_path: SSH key path

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate repository URL
        if not repo_url:
            raise ValueError("Repository URL is required")

        # Prevent dangerous protocols
        dangerous_protocols = ["file://", "ftp://", "ftps://"]
        if any(repo_url.startswith(proto) for proto in dangerous_protocols):
            raise ValueError(f"Unsupported or dangerous protocol in URL: {repo_url}")

        # Validate SSH key if provided
        if ssh_key_path:
            ssh_key = Path(ssh_key_path)

            if not ssh_key.exists():
                raise ValueError(f"SSH key not found: {ssh_key_path}")

            if not ssh_key.is_file():
                raise ValueError(f"SSH key path is not a file: {ssh_key_path}")

            # Check permissions (should be 600 or 400)
            if os.name != 'nt':  # Unix-like systems
                file_mode = ssh_key.stat().st_mode
                permissions = stat.filemode(file_mode)

                # Check if file is readable by others or group
                if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
                    logger.warning(
                        f"SSH key has overly permissive permissions: {permissions}. "
                        f"Recommended: 600 (rw-------). File: {ssh_key_path}"
                    )

                # Check if file is not readable by owner
                if not file_mode & stat.S_IRUSR:
                    raise ValueError(f"SSH key is not readable: {ssh_key_path}")

    def clone_or_pull(self) -> Tuple[bool, str]:
        """
        Clone repository if not exists, otherwise checkout branch and pull latest changes.

        Returns:
            Tuple of (success, commit_hash)

        Raises:
            GitCommandError: If Git operation fails
            ValueError: If repository validation fails
            TimeoutError: If operation exceeds timeout
        """
        try:
            # Check repository size before operations
            self._check_repo_size()

            if self.local_path.exists() and (self.local_path / ".git").exists():
                logger.info(f"Repository exists, checking out branch '{self.branch}'")
                repo = Repo(self.local_path)
                origin = repo.remotes.origin

                # Fetch latest from origin (force to handle shallow clone conflicts)
                if self.ssh_key_path:
                    with repo.git.custom_environment(**self._get_git_env()):
                        origin.fetch(force=True, prune=True)
                else:
                    origin.fetch(force=True, prune=True)

                # Checkout the target branch
                if self.branch not in repo.heads:
                    # Create local branch tracking remote
                    logger.info(f"Creating local branch '{self.branch}' tracking origin/{self.branch}")
                    repo.create_head(self.branch, origin.refs[self.branch])

                # Checkout branch
                repo.heads[self.branch].checkout()
                logger.info(f"Checked out branch '{self.branch}'")

                # Pull latest changes
                logger.info(f"Pulling latest changes from origin/{self.branch}")
                if self.ssh_key_path:
                    with repo.git.custom_environment(**self._get_git_env()):
                        origin.pull(self.branch)
                else:
                    origin.pull(self.branch)

                commit_hash = repo.head.commit.hexsha
                logger.info(f"Pulled latest: {commit_hash}")
            else:
                logger.info(f"Cloning repository {self.repo_url} (branch: {self.branch})")
                self.local_path.parent.mkdir(parents=True, exist_ok=True)

                # Clone with all branches for flexibility
                repo = Repo.clone_from(
                    self.repo_url,
                    self.local_path,
                    env=self._get_git_env(),
                )

                # Checkout the target branch
                if self.branch != repo.active_branch.name:
                    logger.info(f"Checking out branch '{self.branch}'")
                    repo.heads[self.branch].checkout()

                commit_hash = repo.head.commit.hexsha
                logger.info(f"Cloned repository on branch '{self.branch}': {commit_hash}")

            return True, commit_hash

        except GitCommandError as e:
            logger.error(f"Git operation failed: {e}")
            raise
        except Exception as e:
            logger.critical(
                f"Unexpected error in Git operation: {e}", exc_info=True
            )
            raise

    def _get_git_env(self) -> dict:
        """Get environment variables for Git operations."""
        env = {}
        if self.ssh_key_path:
            host_key_check = "no" if not self.strict_host_key_checking else "yes"
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.ssh_key_path} "
                f"-o StrictHostKeyChecking={host_key_check} "
                f"-o ConnectTimeout={self.timeout}"
            )
        return env

    def _check_repo_size(self) -> None:
        """
        Check if repository size is within limits.

        Raises:
            ValueError: If repository exceeds size limit
        """
        if not self.local_path.exists():
            return

        # Calculate repository size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(self.local_path):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                try:
                    total_size += filepath.stat().st_size
                except (OSError, FileNotFoundError):
                    continue

        size_mb = total_size / (1024 * 1024)
        logger.info(f"Repository size: {size_mb:.2f} MB")

        if size_mb > MAX_REPO_SIZE_MB:
            raise ValueError(
                f"Repository size ({size_mb:.2f} MB) exceeds limit ({MAX_REPO_SIZE_MB} MB). "
                "Consider using shallow clones or cleaning up the repository."
            )

    def get_file_path(self, relative_path: str) -> Path:
        """
        Get absolute path for file within repo.

        Args:
            relative_path: Path relative to repository root

        Returns:
            Absolute path to file
        """
        return self.local_path / relative_path


class PytestMetadataExtractor:
    """Extracts test metadata using AST parsing of pytest markers."""

    def __init__(
        self, repo_path: Path, tests_base_path: str, staging_config_path: str
    ):
        """
        Initialize pytest metadata extractor.

        Args:
            repo_path: Path to Git repository
            tests_base_path: Path to tests directory (relative to repo root)
            staging_config_path: Path to staging config file (relative to repo root)
        """
        self.repo_path = repo_path
        self.tests_base_path = repo_path / tests_base_path
        self.staging_config_path = repo_path / staging_config_path

    def discover_tests(self) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Discover all tests and extract metadata.

        Returns:
            Tuple of (test_metadata_list, failed_files_list)

        Raises:
            Exception: If discovery fails critically
        """
        logger.info(f"Discovering tests in {self.tests_base_path}")

        # Load staging tests
        staging_tests = self._load_staging_tests()
        logger.info(f"Loaded {len(staging_tests)} staging tests")

        # Find test files
        test_files = self._find_test_files()
        logger.info(f"Found {len(test_files)} test files")

        # Extract metadata from each file
        all_tests = []
        failed_files = []

        for test_file in test_files:
            try:
                # Check file size before parsing
                file_size_mb = test_file.stat().st_size / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    logger.warning(
                        f"Skipping {test_file}: File too large ({file_size_mb:.2f} MB > {MAX_FILE_SIZE_MB} MB)"
                    )
                    failed_files.append(str(test_file))
                    continue

                tests = self._extract_from_file(test_file, staging_tests)
                all_tests.extend(tests)
            except SyntaxError as e:
                logger.warning(f"Skipping {test_file}: Invalid syntax - {e}")
                failed_files.append(str(test_file))
            except Exception as e:
                logger.error(f"Error parsing {test_file}: {e}", exc_info=True)
                failed_files.append(str(test_file))

        # Calculate failure rate
        total_files = len(test_files)
        failure_rate = (len(failed_files) / total_files * 100) if total_files > 0 else 0

        logger.info(
            f"Extracted {len(all_tests)} test cases from {total_files - len(failed_files)} files "
            f"({len(failed_files)} files failed, {failure_rate:.1f}% failure rate)"
        )

        # Fail if failure rate is too high
        if failure_rate > 10 and len(failed_files) > 5:
            raise Exception(
                f"Test discovery failure rate too high: {failure_rate:.1f}% "
                f"({len(failed_files)}/{total_files} files failed). "
                "This may indicate a systemic issue with the repository or parser."
            )

        return all_tests, failed_files

    def _load_staging_tests(self) -> Set[str]:
        """Load test names from dp_staging.ini."""
        staging_tests = set()

        if not self.staging_config_path.exists():
            logger.warning(f"Staging config not found: {self.staging_config_path}")
            return staging_tests

        try:
            config = configparser.ConfigParser()
            config.read(self.staging_config_path)

            if "STAGING" in config and "testcases" in config["STAGING"]:
                testcases_str = config["STAGING"]["testcases"]
                staging_tests = {
                    tc.strip() for tc in testcases_str.split(",") if tc.strip()
                }
        except Exception as e:
            logger.warning(f"Could not parse staging config: {e}")

        return staging_tests

    def _find_test_files(self) -> List[Path]:
        """Find all test files."""
        test_files = []
        for root, dirs, files in os.walk(self.tests_base_path):
            for file in files:
                if file.endswith("_test.py") or (
                    file.startswith("test_") and file.endswith(".py")
                ):
                    test_files.append(Path(root) / file)
        return sorted(test_files)

    def _extract_from_file(
        self, file_path: Path, staging_tests: Set[str]
    ) -> List[Dict]:
        """Extract test metadata from file using AST parsing."""
        tests = []

        # Parse AST
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        # Calculate paths
        rel_path = file_path.relative_to(self.tests_base_path.parent)
        path_str = str(rel_path)
        module = (
            rel_path.parts[1] if len(rel_path.parts) > 1 else ""
        )  # Extract module from path

        # Find test classes and functions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                # Class-level decorators
                class_topology = self._get_topology_from_decorators(
                    node.decorator_list
                )
                class_tm = self._get_testmanagement_from_decorators(
                    node.decorator_list
                )

                # Find test methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith(
                        "test_"
                    ):
                        method_topology = self._get_topology_from_decorators(
                            item.decorator_list
                        )
                        method_tm = self._get_testmanagement_from_decorators(
                            item.decorator_list
                        )

                        topology = method_topology or class_topology
                        testcase_id = (
                            method_tm["testcase_id"] or class_tm["testcase_id"]
                        )
                        testrail_id = (
                            method_tm["testrail_id"] or class_tm["testrail_id"]
                        )
                        priority = method_tm["priority"] or class_tm["priority"]

                        if topology:  # Only include tests with topology
                            tests.append(
                                {
                                    "testcase_name": item.name,
                                    "test_class_name": node.name,
                                    "module": module,
                                    "topology": topology,
                                    "test_path": path_str,
                                    "test_state": (
                                        "STAGING" if item.name in staging_tests else "PROD"
                                    ),
                                    "testcase_id": testcase_id or "",
                                    "testrail_id": testrail_id or "",
                                    "priority": priority or "",
                                }
                            )

            elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                # Standalone test function
                topology = self._get_topology_from_decorators(node.decorator_list)
                tm = self._get_testmanagement_from_decorators(node.decorator_list)

                if topology:
                    tests.append(
                        {
                            "testcase_name": node.name,
                            "test_class_name": "",
                            "module": module,
                            "topology": topology,
                            "test_path": path_str,
                            "test_state": (
                                "STAGING" if node.name in staging_tests else "PROD"
                            ),
                            "testcase_id": tm["testcase_id"] or "",
                            "testrail_id": tm["testrail_id"] or "",
                            "priority": tm["priority"] or "",
                        }
                    )

        return tests

    def _get_topology_from_decorators(self, decorators: List) -> Optional[str]:
        """Extract topology from @pytest.mark.testbed decorator."""
        for decorator in decorators:
            if isinstance(decorator, ast.Call):
                if self._is_testbed_decorator(decorator):
                    for keyword in decorator.keywords:
                        if keyword.arg == "topology":
                            if isinstance(keyword.value, ast.Constant):
                                return keyword.value.value
                            elif isinstance(keyword.value, ast.Str):
                                return keyword.value.s
        return None

    def _get_testmanagement_from_decorators(
        self, decorators: List
    ) -> Dict[str, Optional[str]]:
        """Extract metadata from @pytest.mark.testmanagement decorator."""
        result = {"testcase_id": None, "testrail_id": None, "priority": None}

        for decorator in decorators:
            if isinstance(decorator, ast.Call):
                if self._is_testmanagement_decorator(decorator):
                    for keyword in decorator.keywords:
                        if keyword.arg == "qtest_tc_id":
                            result["testcase_id"] = self._get_string_value(
                                keyword.value
                            )
                        elif keyword.arg == "case":
                            case_value = self._get_value(keyword.value)
                            if case_value:
                                # Add "C" prefix to TestRail ID (e.g., 867789 -> C867789)
                                result["testrail_id"] = f"C{case_value}"
                            else:
                                result["testrail_id"] = None
                        elif keyword.arg == "priority":
                            result["priority"] = self._get_string_value(keyword.value)

        return result

    @staticmethod
    def _is_testbed_decorator(decorator: ast.Call) -> bool:
        """Check if decorator is pytest.mark.testbed."""
        if isinstance(decorator.func, ast.Attribute):
            if (
                isinstance(decorator.func.value, ast.Attribute)
                and getattr(decorator.func.value, "attr", None) == "mark"
                and getattr(decorator.func, "attr", None) == "testbed"
            ):
                return True
        return False

    @staticmethod
    def _is_testmanagement_decorator(decorator: ast.Call) -> bool:
        """Check if decorator is pytest.mark.testmanagement."""
        if isinstance(decorator.func, ast.Attribute):
            if (
                isinstance(decorator.func.value, ast.Attribute)
                and getattr(decorator.func.value, "attr", None) == "mark"
                and getattr(decorator.func, "attr", None) == "testmanagement"
            ):
                return True
        return False

    @staticmethod
    def _get_value(node):
        """Extract value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, (ast.Str, ast.Num)):
            return node.s if isinstance(node, ast.Str) else node.n
        return None

    @staticmethod
    def _get_string_value(node) -> Optional[str]:
        """Extract string value from AST node."""
        value = PytestMetadataExtractor._get_value(node)
        return str(value) if value is not None else None


class MetadataSyncService:
    """Orchestrates metadata synchronization from Git to database."""

    def __init__(self, db: Session, config: Settings, release: 'Release'):
        """
        Initialize metadata sync service.

        Args:
            db: Database session
            config: Application settings
            release: Release object to sync metadata for
        """
        self.db = db
        self.config = config
        self.release = release

        # Use release-specific Git branch but shared local path
        git_branch = release.git_branch or config.GIT_REPO_BRANCH
        local_path = config.GIT_REPO_LOCAL_PATH  # Shared repository for all releases

        self.git_manager = GitRepositoryManager(
            repo_url=config.GIT_REPO_URL,
            local_path=local_path,
            branch=git_branch,
            ssh_key_path=config.GIT_REPO_SSH_KEY_PATH,
            strict_host_key_checking=config.GIT_SSH_STRICT_HOST_KEY_CHECKING,
        )
        self.extractor = PytestMetadataExtractor(
            repo_path=Path(local_path),
            tests_base_path=config.TEST_DISCOVERY_BASE_PATH,
            staging_config_path=config.TEST_DISCOVERY_STAGING_CONFIG,
        )

    def sync_metadata(self, sync_type: str = SYNC_TYPE_MANUAL, progress_callback=None) -> Dict[str, Any]:
        """
        Run full sync operation.

        Args:
            sync_type: Type of sync ('scheduled', 'manual', or 'startup')
            progress_callback: Optional callback for progress updates (callable)

        Returns:
            Dictionary with sync statistics

        Raises:
            Exception: If sync fails
        """
        sync_log = MetadataSyncLog(
            status=SYNC_STATUS_IN_PROGRESS,
            sync_type=sync_type,
            release_id=self.release.id,
            started_at=datetime.utcnow()
        )
        self.db.add(sync_log)
        self.db.flush()  # Get sync_log.id

        failed_files = []

        try:
            # Use global lock to prevent concurrent Git operations
            logger.info(f"Acquiring lock for Git operations on branch '{self.git_manager.branch}'")
            if progress_callback:
                progress_callback(f"Acquiring Git lock for branch '{self.git_manager.branch}'")

            with _git_operation_lock:
                # Step 1: Checkout branch and pull latest changes
                logger.info(f"Step 1: Checking out branch '{self.git_manager.branch}' and pulling latest changes")
                if progress_callback:
                    progress_callback(f"Pulling latest changes from branch '{self.git_manager.branch}'")

                success, commit_hash = self.git_manager.clone_or_pull()
                sync_log.git_commit_hash = commit_hash

                # Step 2: Discover tests (must be done while holding lock to ensure consistency)
                logger.info("Step 2: Discovering tests from repository")
                if progress_callback:
                    progress_callback("Discovering tests from repository")

                discovered_tests, failed_files = self.extractor.discover_tests()
                sync_log.tests_discovered = len(discovered_tests)

            logger.info("Released lock after Git operations")
            if progress_callback:
                progress_callback(f"Discovered {len(discovered_tests)} tests ({len(failed_files)} files failed)")

            # Step 3: Compare with database
            logger.info("Step 3: Comparing with existing metadata")
            if progress_callback:
                progress_callback("Comparing with existing metadata")

            existing_metadata = self._get_existing_metadata()
            to_add, to_update, to_remove = self._compare_metadata(
                discovered_tests, existing_metadata
            )

            # Step 4: Apply updates with batching
            logger.info(
                f"Step 4: Applying updates (add={len(to_add)}, update={len(to_update)}, remove={len(to_remove)})"
            )
            if progress_callback:
                progress_callback(
                    f"Applying updates: {len(to_add)} new, {len(to_update)} updated, {len(to_remove)} removed"
                )

            stats = self._apply_updates(to_add, to_update, to_remove, sync_log.id, progress_callback)

            # Update sync log
            sync_log.tests_added = stats["added"]
            sync_log.tests_updated = stats["updated"]
            sync_log.tests_removed = stats["removed"]
            sync_log.status = SYNC_STATUS_SUCCESS

            # Store failed files in error_details
            if failed_files:
                sync_log.error_details = json.dumps({
                    "failed_files": failed_files,
                    "failed_file_count": len(failed_files)
                })

            sync_log.completed_at = datetime.utcnow()

            self.db.commit()

            logger.info(f"Sync completed successfully: {stats}")
            if progress_callback:
                progress_callback(
                    f"Sync completed: {stats['added']} added, {stats['updated']} updated, "
                    f"{stats['removed']} removed"
                )

            return {
                "status": SYNC_STATUS_SUCCESS,
                "failed_files": failed_files,
                "failed_file_count": len(failed_files),
                **stats
            }

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            sync_log.status = SYNC_STATUS_FAILED
            sync_log.error_message = f"{error_type}: {error_msg}"
            sync_log.error_details = json.dumps({
                "error_type": error_type,
                "failed_files": failed_files,
                "failed_file_count": len(failed_files),
                "release_name": self.release.name,
                "git_branch": self.git_manager.branch,
            })
            sync_log.completed_at = datetime.utcnow()
            self.db.commit()

            logger.error(
                f"Metadata sync failed for release {self.release.name} "
                f"(branch: {self.git_manager.branch}): {error_msg}",
                extra={"release_id": self.release.id, "error_type": error_type},
                exc_info=True
            )

            if progress_callback:
                progress_callback(f"Sync failed: {error_msg}")

            raise

    def _get_existing_metadata(self) -> Dict[str, TestcaseMetadata]:
        """
        Get existing metadata for this release.

        Returns metadata keyed by testcase_name. Release-specific metadata
        takes precedence over global metadata (release_id = NULL).
        """
        records = self.db.query(TestcaseMetadata).filter(
            (TestcaseMetadata.release_id == self.release.id) | (TestcaseMetadata.release_id.is_(None))
        ).all()

        # Build lookup with precedence: release-specific > global
        result = {}
        for record in records:
            if record.release_id == self.release.id:
                # Release-specific metadata always wins
                result[record.testcase_name] = record
            elif record.testcase_name not in result:
                # Use global metadata only if no release-specific exists
                result[record.testcase_name] = record

        return result

    def _get_previously_removed_tests(self) -> set:
        """
        Get set of test names that were marked as removed in previous syncs.

        This prevents re-logging the same tests as "removed" on every sync.
        Release-aware: checks both release-specific and global metadata.
        """
        removed_tests = self.db.query(TestcaseMetadata.testcase_name).filter(
            TestcaseMetadata.is_removed == True,
            (TestcaseMetadata.release_id == self.release.id) | (TestcaseMetadata.release_id.is_(None))
        ).distinct().all()

        return {test[0] for test in removed_tests}

    @staticmethod
    def _normalize_test_name(testcase_name: str) -> str:
        """
        Normalize test name by removing parametrization suffixes.

        Examples:
            test_foo[True] -> test_foo
            test_bar[1] -> test_bar
            test_baz[param1-value1] -> test_baz
        """
        import re
        # Remove parametrization suffix: [anything]
        return re.sub(r'\[.*?\]$', '', testcase_name)

    def _compare_metadata(
        self, discovered: List[Dict], existing: Dict[str, TestcaseMetadata]
    ) -> Tuple[List, List, List]:
        """
        Compare discovered tests with database.

        Handles parametrized tests by matching base names:
        - test_foo[True] and test_foo[False] both match test_foo from Git
        - Updates all parametrized variants when base test is found
        """
        to_add = []
        to_update = []
        discovered_base_names = set()
        matched_existing = set()

        # Build map of base names to discovered tests
        discovered_by_base = {}
        for test in discovered:
            base_name = self._normalize_test_name(test["testcase_name"])
            discovered_base_names.add(base_name)
            discovered_by_base[base_name] = test

        # Match existing tests (including parametrized variants) to discovered base tests
        for existing_name, existing_record in existing.items():
            base_name = self._normalize_test_name(existing_name)

            if base_name in discovered_base_names:
                # Found match - mark as matched (so it won't be removed)
                matched_existing.add(existing_name)
                discovered_test = discovered_by_base[base_name]

                # CRITICAL: Check if existing record is Global or release-specific
                if existing_record.release_id is None:
                    # This is Global metadata and we're syncing for a specific release
                    # → CREATE a new release-specific record (don't modify Global!)
                    if self._needs_update(existing_record, discovered_test):
                        to_add.append(discovered_test)
                else:
                    # This is release-specific metadata for THIS release
                    # → UPDATE the existing release-specific record
                    if self._needs_update(existing_record, discovered_test):
                        to_update.append((existing_record, discovered_test))
            # else: test will be considered removed below

        # Add new tests (only if exact match doesn't exist AND base doesn't exist)
        for test in discovered:
            testcase_name = test["testcase_name"]
            base_name = self._normalize_test_name(testcase_name)

            # Check if exact name or any parametrized variant already exists
            has_exact_match = testcase_name in existing
            has_parametrized_variant = any(
                self._normalize_test_name(name) == base_name
                for name in existing.keys()
            )

            if not has_exact_match and not has_parametrized_variant:
                to_add.append(test)

        # Get tests that were already marked as removed in previous syncs
        previously_removed = self._get_previously_removed_tests()

        # Find removed tests (not matched to any discovered base name)
        # Exclude tests that were already marked as removed in previous syncs
        to_remove = [
            record for name, record in existing.items()
            if name not in matched_existing and name not in previously_removed
        ]

        return to_add, to_update, to_remove

    def _needs_update(self, existing: TestcaseMetadata, new_data: Dict) -> bool:
        """Check if existing record needs updating."""
        # Always update these fields if different
        if existing.topology != new_data.get("topology"):
            return True
        if existing.module != new_data.get("module"):
            return True
        if existing.test_state != new_data.get("test_state"):
            return True
        if existing.test_class_name != new_data.get("test_class_name"):
            return True
        if existing.test_path != new_data.get("test_path"):
            return True
        if existing.test_case_id != new_data.get("testcase_id"):
            return True
        if existing.testrail_id != new_data.get("testrail_id"):
            return True

        # Conditionally update priority (only if existing is NULL)
        if existing.priority is None and new_data.get("priority"):
            return True

        return False

    def _apply_updates(
        self,
        to_add: List[Dict],
        to_update: List[Tuple],
        to_remove: List[TestcaseMetadata],
        sync_log_id: int,
        progress_callback=None,
    ) -> Dict[str, int]:
        """
        Apply database changes with audit trail using batching.

        Args:
            to_add: List of test metadata to add
            to_update: List of (existing, new_data) tuples to update
            to_remove: List of TestcaseMetadata records to mark as removed
            sync_log_id: ID of the sync log
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with counts of added, updated, and removed tests
        """
        # Add new tests in batches
        added_count = 0
        for i in range(0, len(to_add), BATCH_SIZE):
            batch = to_add[i:i + BATCH_SIZE]

            for test_data in batch:
                record = TestcaseMetadata(
                    release_id=self.release.id,
                    testcase_name=test_data["testcase_name"],
                    test_class_name=test_data.get("test_class_name", ""),
                    module=test_data.get("module", ""),
                    topology=test_data.get("topology", ""),
                    test_path=test_data.get("test_path", ""),
                    test_state=test_data.get("test_state", "PROD"),
                    test_case_id=test_data.get("testcase_id", ""),
                    testrail_id=test_data.get("testrail_id", ""),
                    priority=test_data.get("priority", "") or None,
                    is_removed=False,
                )
                self.db.add(record)

                # Log change
                change = TestcaseMetadataChange(
                    sync_log_id=sync_log_id,
                    testcase_name=test_data["testcase_name"],
                    change_type=CHANGE_TYPE_ADDED,
                    new_values=json.dumps(test_data),
                )
                self.db.add(change)

            # Commit batch
            self.db.commit()
            added_count += len(batch)

            if progress_callback and len(to_add) > BATCH_SIZE:
                progress_callback(f"Added {added_count}/{len(to_add)} new tests")

        # Update existing tests in batches
        updated_count = 0
        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i:i + BATCH_SIZE]

            for existing, new_data in batch:
                old_values = self._serialize_metadata(existing)

                # Apply updates
                existing.topology = new_data.get("topology", "")
                existing.module = new_data.get("module", "")
                existing.test_state = new_data.get("test_state", "PROD")
                existing.test_class_name = new_data.get("test_class_name", "")
                existing.test_path = new_data.get("test_path", "")
                existing.test_case_id = new_data.get("testcase_id", "")
                existing.testrail_id = new_data.get("testrail_id", "")

                # Conditional priority update
                if existing.priority is None and new_data.get("priority"):
                    existing.priority = new_data["priority"]

                # Log change
                change = TestcaseMetadataChange(
                    sync_log_id=sync_log_id,
                    testcase_name=existing.testcase_name,
                    change_type=CHANGE_TYPE_UPDATED,
                    old_values=json.dumps(old_values),
                    new_values=json.dumps(new_data),
                )
                self.db.add(change)

            # Commit batch
            self.db.commit()
            updated_count += len(batch)

            if progress_callback and len(to_update) > BATCH_SIZE:
                progress_callback(f"Updated {updated_count}/{len(to_update)} tests")

        # Remove tests (soft delete with is_removed flag) in batches
        removed_count = 0
        for i in range(0, len(to_remove), BATCH_SIZE):
            batch = to_remove[i:i + BATCH_SIZE]

            for record in batch:
                old_values = self._serialize_metadata(record)

                # Mark as removed instead of deleting
                record.is_removed = True

                # Log change
                change = TestcaseMetadataChange(
                    sync_log_id=sync_log_id,
                    testcase_name=record.testcase_name,
                    change_type=CHANGE_TYPE_REMOVED,
                    old_values=json.dumps(old_values),
                )
                self.db.add(change)

            # Commit batch
            self.db.commit()
            removed_count += len(batch)

            if progress_callback and len(to_remove) > BATCH_SIZE:
                progress_callback(f"Removed {removed_count}/{len(to_remove)} tests")

        logger.info(
            f"Database updates completed: {added_count} added, "
            f"{updated_count} updated, {removed_count} removed"
        )

        return {
            "added": added_count,
            "updated": updated_count,
            "removed": removed_count,
        }

    @staticmethod
    def _serialize_metadata(record: TestcaseMetadata) -> Dict:
        """Serialize metadata record for logging."""
        return {
            "testcase_name": record.testcase_name,
            "test_class_name": record.test_class_name,
            "module": record.module,
            "topology": record.topology,
            "test_path": record.test_path,
            "test_state": record.test_state,
            "test_case_id": record.test_case_id,
            "testrail_id": record.testrail_id,
            "priority": record.priority,
        }
