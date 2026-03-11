"""
Tests for Global → Release-specific metadata conversion during Git sync.

This test verifies that when syncing for a specific release, if Global metadata
exists for a test, it creates a NEW release-specific record instead of updating
the Global record.
"""
import pytest
from unittest.mock import Mock, patch

from app.services.git_metadata_sync_service import MetadataSyncService
from app.models.db_models import TestcaseMetadata, Release


class TestGlobalToReleaseConversion:
    """Test conversion of Global metadata to release-specific during sync."""

    def test_global_to_release_creates_new_record(self):
        """
        Test that syncing for a specific release creates NEW release-specific
        records when only Global metadata exists (doesn't update Global).
        """
        # Setup: Create a mock release
        mock_release = Mock(spec=Release)
        mock_release.id = 2
        mock_release.name = "7.0"

        # Create mock DB session and config
        mock_db = Mock()
        mock_config = Mock()
        mock_config.GIT_REPO_URL = "https://github.com/test/repo.git"
        mock_config.GIT_REPO_LOCAL_PATH = "/tmp/test_repo"
        mock_config.GIT_REPO_BRANCH = "master"
        mock_config.GIT_REPO_SSH_KEY_PATH = None
        mock_config.GIT_SSH_STRICT_HOST_KEY_CHECKING = True
        mock_config.TEST_DISCOVERY_BASE_PATH = "tests"
        mock_config.TEST_DISCOVERY_STAGING_CONFIG = "staging.ini"

        service = MetadataSyncService(mock_db, mock_config, mock_release)

        # Simulate existing Global metadata
        global_record = Mock(spec=TestcaseMetadata)
        global_record.testcase_name = "test_example"
        global_record.release_id = None  # Global
        global_record.topology = "3-site"
        global_record.priority = "P1"
        global_record.module = "routing"
        global_record.test_state = "PROD"
        global_record.test_class_name = "TestRouting"
        global_record.test_path = "tests/routing/test_example.py"
        global_record.test_case_id = "TC-001"
        global_record.testrail_id = "C12345"

        existing = {
            "test_example": global_record
        }

        # Simulate discovered test with different topology
        discovered = [
            {
                "testcase_name": "test_example",
                "topology": "5-site",  # Changed
                "module": "routing",
                "test_class_name": "TestRouting",
                "test_path": "tests/routing/test_example.py",
                "test_state": "PROD",
                "testcase_id": "TC-001",
                "testrail_id": "C12345",
                "priority": "P1"
            }
        ]

        # Run comparison (patch _get_previously_removed_tests to avoid DB queries)
        with patch.object(service, '_get_previously_removed_tests', return_value=set()):
            to_add, to_update, to_remove = service._compare_metadata(discovered, existing)

        # ASSERTIONS
        # 1. Should ADD a new release-specific record (not update Global)
        assert len(to_add) == 1
        assert to_add[0]["testcase_name"] == "test_example"
        assert to_add[0]["topology"] == "5-site"

        # 2. Should NOT update the Global record
        assert len(to_update) == 0

        # 3. Should NOT remove anything
        assert len(to_remove) == 0

    def test_release_specific_to_release_updates_existing(self):
        """
        Test that syncing for a specific release UPDATES existing release-specific
        records (doesn't create duplicates).
        """
        # Setup
        mock_release = Mock(spec=Release)
        mock_release.id = 2
        mock_release.name = "7.0"

        mock_db = Mock()
        mock_config = Mock()
        mock_config.GIT_REPO_URL = "https://github.com/test/repo.git"
        mock_config.GIT_REPO_LOCAL_PATH = "/tmp/test_repo"
        mock_config.GIT_REPO_BRANCH = "master"
        mock_config.GIT_REPO_SSH_KEY_PATH = None
        mock_config.GIT_SSH_STRICT_HOST_KEY_CHECKING = True
        mock_config.TEST_DISCOVERY_BASE_PATH = "tests"
        mock_config.TEST_DISCOVERY_STAGING_CONFIG = "staging.ini"

        service = MetadataSyncService(mock_db, mock_config, mock_release)

        # Simulate existing release-specific metadata
        release_record = Mock(spec=TestcaseMetadata)
        release_record.testcase_name = "test_example"
        release_record.release_id = 2  # Same as mock_release.id
        release_record.topology = "3-site"
        release_record.priority = "P1"
        release_record.module = "routing"
        release_record.test_state = "PROD"
        release_record.test_class_name = "TestRouting"
        release_record.test_path = "tests/routing/test_example.py"
        release_record.test_case_id = "TC-001"
        release_record.testrail_id = "C12345"

        existing = {
            "test_example": release_record
        }

        # Simulate discovered test with different topology
        discovered = [
            {
                "testcase_name": "test_example",
                "topology": "5-site",  # Changed
                "module": "routing",
                "test_class_name": "TestRouting",
                "test_path": "tests/routing/test_example.py",
                "test_state": "PROD",
                "testcase_id": "TC-001",
                "testrail_id": "C12345",
                "priority": "P1"
            }
        ]

        # Run comparison (patch _get_previously_removed_tests to avoid DB queries)
        with patch.object(service, '_get_previously_removed_tests', return_value=set()):
            to_add, to_update, to_remove = service._compare_metadata(discovered, existing)

        # ASSERTIONS
        # 1. Should NOT add a new record
        assert len(to_add) == 0

        # 2. Should UPDATE the existing release-specific record
        assert len(to_update) == 1
        assert to_update[0][0] == release_record  # existing record
        assert to_update[0][1]["topology"] == "5-site"  # new data

        # 3. Should NOT remove anything
        assert len(to_remove) == 0

    def test_global_no_changes_no_add(self):
        """
        Test that if Global metadata exists and discovered data is identical,
        no new release-specific record is created (optimization).
        """
        # Setup
        mock_release = Mock(spec=Release)
        mock_release.id = 2

        mock_db = Mock()
        mock_config = Mock()
        mock_config.GIT_REPO_URL = "https://github.com/test/repo.git"
        mock_config.GIT_REPO_LOCAL_PATH = "/tmp/test_repo"
        mock_config.GIT_REPO_BRANCH = "master"
        mock_config.GIT_REPO_SSH_KEY_PATH = None
        mock_config.GIT_SSH_STRICT_HOST_KEY_CHECKING = True
        mock_config.TEST_DISCOVERY_BASE_PATH = "tests"
        mock_config.TEST_DISCOVERY_STAGING_CONFIG = "staging.ini"

        service = MetadataSyncService(mock_db, mock_config, mock_release)

        # Global metadata (identical to discovered)
        global_record = Mock(spec=TestcaseMetadata)
        global_record.testcase_name = "test_example"
        global_record.release_id = None  # Global
        global_record.topology = "3-site"
        global_record.priority = "P1"
        global_record.module = "routing"
        global_record.test_state = "PROD"
        global_record.test_class_name = "TestRouting"
        global_record.test_path = "tests/routing/test_example.py"
        global_record.test_case_id = "TC-001"
        global_record.testrail_id = "C12345"

        existing = {
            "test_example": global_record
        }

        # Discovered test (identical to Global)
        discovered = [
            {
                "testcase_name": "test_example",
                "topology": "3-site",  # Same
                "module": "routing",
                "test_class_name": "TestRouting",
                "test_path": "tests/routing/test_example.py",
                "test_state": "PROD",
                "testcase_id": "TC-001",
                "testrail_id": "C12345",
                "priority": "P1"
            }
        ]

        # Run comparison (patch _get_previously_removed_tests to avoid DB queries)
        with patch.object(service, '_get_previously_removed_tests', return_value=set()):
            to_add, to_update, to_remove = service._compare_metadata(discovered, existing)

        # ASSERTIONS
        # No changes needed - don't create unnecessary release-specific record
        assert len(to_add) == 0
        assert len(to_update) == 0
        assert len(to_remove) == 0
