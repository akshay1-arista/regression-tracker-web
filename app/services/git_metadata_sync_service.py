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


class GitRepositoryManager:
    """Manages Git repository operations for test discovery."""

    def __init__(
        self,
        repo_url: str,
        local_path: str,
        branch: str = "master",
        ssh_key_path: Optional[str] = None,
    ):
        """
        Initialize Git repository manager.

        Args:
            repo_url: Git repository URL (SSH or HTTPS)
            local_path: Local path for repository clone
            branch: Branch to track
            ssh_key_path: Optional path to SSH private key
        """
        self.repo_url = repo_url
        self.local_path = Path(local_path)
        self.branch = branch
        self.ssh_key_path = ssh_key_path

    def clone_or_pull(self) -> Tuple[bool, str]:
        """
        Clone repository if not exists, otherwise pull latest changes.

        Returns:
            Tuple of (success, commit_hash)

        Raises:
            GitCommandError: If Git operation fails
        """
        try:
            if self.local_path.exists() and (self.local_path / ".git").exists():
                logger.info(f"Pulling latest changes from {self.repo_url}")
                repo = Repo(self.local_path)
                origin = repo.remotes.origin

                # Configure Git environment for SSH
                if self.ssh_key_path:
                    with repo.git.custom_environment(**self._get_git_env()):
                        origin.pull()
                else:
                    origin.pull()

                commit_hash = repo.head.commit.hexsha
                logger.info(f"Pulled latest: {commit_hash}")
            else:
                logger.info(f"Cloning repository {self.repo_url}")
                self.local_path.parent.mkdir(parents=True, exist_ok=True)

                # Use shallow clone for performance
                repo = Repo.clone_from(
                    self.repo_url,
                    self.local_path,
                    depth=50,
                    single_branch=True,
                    branch=self.branch,
                    env=self._get_git_env(),
                )
                commit_hash = repo.head.commit.hexsha
                logger.info(f"Cloned repository: {commit_hash}")

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
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.ssh_key_path} -o StrictHostKeyChecking=no"
            )
        return env

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

    def discover_tests(self) -> List[Dict[str, str]]:
        """
        Discover all tests and extract metadata.

        Returns:
            List of test metadata dictionaries

        Raises:
            Exception: If discovery fails
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
                tests = self._extract_from_file(test_file, staging_tests)
                all_tests.extend(tests)
            except SyntaxError as e:
                logger.warning(f"Skipping {test_file}: Invalid syntax - {e}")
                failed_files.append(str(test_file))
            except Exception as e:
                logger.error(f"Error parsing {test_file}: {e}", exc_info=True)
                failed_files.append(str(test_file))

        logger.info(
            f"Extracted {len(all_tests)} test cases ({len(failed_files)} files failed)"
        )
        return all_tests

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
                            result["testrail_id"] = str(self._get_value(keyword.value))
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

    def __init__(self, db: Session, config: Settings):
        """
        Initialize metadata sync service.

        Args:
            db: Database session
            config: Application settings
        """
        self.db = db
        self.config = config
        self.git_manager = GitRepositoryManager(
            repo_url=config.GIT_REPO_URL,
            local_path=config.GIT_REPO_LOCAL_PATH,
            branch=config.GIT_REPO_BRANCH,
            ssh_key_path=config.GIT_REPO_SSH_KEY_PATH,
        )
        self.extractor = PytestMetadataExtractor(
            repo_path=Path(config.GIT_REPO_LOCAL_PATH),
            tests_base_path=config.TEST_DISCOVERY_BASE_PATH,
            staging_config_path=config.TEST_DISCOVERY_STAGING_CONFIG,
        )

    def sync_metadata(self, sync_type: str = "manual") -> Dict[str, Any]:
        """
        Run full sync operation.

        Args:
            sync_type: Type of sync ('scheduled' or 'manual')

        Returns:
            Dictionary with sync statistics

        Raises:
            Exception: If sync fails
        """
        sync_log = MetadataSyncLog(
            status='in_progress',
            sync_type=sync_type,
            started_at=datetime.utcnow()
        )
        self.db.add(sync_log)
        self.db.flush()  # Get sync_log.id

        try:
            # Step 1: Git pull
            logger.info("Step 1: Pulling latest Git changes")
            success, commit_hash = self.git_manager.clone_or_pull()
            sync_log.git_commit_hash = commit_hash

            # Step 2: Discover tests
            logger.info("Step 2: Discovering tests from repository")
            discovered_tests = self.extractor.discover_tests()
            sync_log.tests_discovered = len(discovered_tests)

            # Step 3: Compare with database
            logger.info("Step 3: Comparing with existing metadata")
            existing_metadata = self._get_existing_metadata()
            to_add, to_update, to_remove = self._compare_metadata(
                discovered_tests, existing_metadata
            )

            # Step 4: Apply updates
            logger.info(
                f"Step 4: Applying updates (add={len(to_add)}, update={len(to_update)}, remove={len(to_remove)})"
            )
            stats = self._apply_updates(to_add, to_update, to_remove, sync_log.id)

            # Update sync log
            sync_log.tests_added = stats["added"]
            sync_log.tests_updated = stats["updated"]
            sync_log.tests_removed = stats["removed"]
            sync_log.status = "success"
            sync_log.completed_at = datetime.utcnow()

            self.db.commit()

            logger.info(f"Sync completed successfully: {stats}")
            return {"status": "success", **stats}

        except Exception as e:
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            sync_log.completed_at = datetime.utcnow()
            self.db.commit()

            logger.error(f"Sync failed: {e}", exc_info=True)
            raise

    def _get_existing_metadata(self) -> Dict[str, TestcaseMetadata]:
        """Get all existing metadata keyed by testcase_name."""
        records = self.db.query(TestcaseMetadata).all()
        return {record.testcase_name: record for record in records}

    def _compare_metadata(
        self, discovered: List[Dict], existing: Dict[str, TestcaseMetadata]
    ) -> Tuple[List, List, List]:
        """Compare discovered tests with database."""
        to_add = []
        to_update = []
        discovered_names = set()

        for test in discovered:
            testcase_name = test["testcase_name"]
            discovered_names.add(testcase_name)

            if testcase_name not in existing:
                to_add.append(test)
            else:
                # Check if update needed
                existing_record = existing[testcase_name]
                if self._needs_update(existing_record, test):
                    to_update.append((existing_record, test))

        # Find removed tests (soft delete)
        to_remove = [
            record for name, record in existing.items() if name not in discovered_names
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
    ) -> Dict[str, int]:
        """Apply database changes with audit trail."""

        # Add new tests
        for test_data in to_add:
            record = TestcaseMetadata(
                testcase_name=test_data["testcase_name"],
                test_class_name=test_data.get("test_class_name", ""),
                module=test_data.get("module", ""),
                topology=test_data.get("topology", ""),
                test_path=test_data.get("test_path", ""),
                test_state=test_data.get("test_state", "PROD"),
                test_case_id=test_data.get("testcase_id", ""),
                testrail_id=test_data.get("testrail_id", ""),
                priority=test_data.get("priority", "") or None,
            )
            self.db.add(record)

            # Log change
            change = TestcaseMetadataChange(
                sync_log_id=sync_log_id,
                testcase_name=test_data["testcase_name"],
                change_type="added",
                new_values=json.dumps(test_data),
            )
            self.db.add(change)

        # Update existing tests
        for existing, new_data in to_update:
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
                change_type="updated",
                old_values=json.dumps(old_values),
                new_values=json.dumps(new_data),
            )
            self.db.add(change)

        # Remove tests (soft delete - just log)
        for record in to_remove:
            old_values = self._serialize_metadata(record)
            change = TestcaseMetadataChange(
                sync_log_id=sync_log_id,
                testcase_name=record.testcase_name,
                change_type="removed",
                old_values=json.dumps(old_values),
            )
            self.db.add(change)
            # Note: Not deleting from database, just logging

        self.db.commit()

        return {
            "added": len(to_add),
            "updated": len(to_update),
            "removed": len(to_remove),
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
