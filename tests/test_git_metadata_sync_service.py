"""
Tests for Git-based metadata synchronization service.

Tests cover:
- Git repository operations (clone, pull, validation)
- AST parsing of pytest markers
- Metadata comparison and synchronization
- Parametrized test handling
- Error handling and edge cases
"""
import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, PropertyMock
from datetime import datetime

from app.services.git_metadata_sync_service import (
    GitRepositoryManager,
    PytestMetadataExtractor,
    MetadataSyncService,
    SYNC_TYPE_MANUAL,
    SYNC_STATUS_SUCCESS,
    CHANGE_TYPE_ADDED,
    CHANGE_TYPE_UPDATED,
    CHANGE_TYPE_REMOVED,
)
from app.models.db_models import (
    MetadataSyncLog,
    TestcaseMetadata,
    TestcaseMetadataChange,
    Release,
)


# ==================== Fixtures ====================


@pytest.fixture
def temp_git_repo():
    """Create a temporary directory for Git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_release(db_session):
    """Create a mock release for testing."""
    release = Release(
        name="7.0.0.0",
        git_branch="master",
        is_active=True
    )
    db_session.add(release)
    db_session.commit()
    return release


@pytest.fixture
def mock_config():
    """Create mock application settings."""
    mock = Mock()
    mock.GIT_REPO_URL = "git@github.com:test/repo.git"
    mock.GIT_REPO_LOCAL_PATH = "/tmp/test_repo"
    mock.GIT_REPO_BRANCH = "master"
    mock.GIT_REPO_SSH_KEY_PATH = ""
    mock.GIT_SSH_STRICT_HOST_KEY_CHECKING = True
    mock.TEST_DISCOVERY_BASE_PATH = "tests"
    mock.TEST_DISCOVERY_STAGING_CONFIG = "staging.ini"
    return mock


# ==================== GitRepositoryManager Tests ====================


class TestGitRepositoryManager:
    """Tests for GitRepositoryManager class."""

    def test_validate_config_valid_ssh_url(self, temp_git_repo):
        """Test validation with valid SSH URL."""
        manager = GitRepositoryManager(
            repo_url="git@github.com:test/repo.git",
            local_path=str(temp_git_repo),
            branch="master"
        )
        assert manager.repo_url == "git@github.com:test/repo.git"

    def test_validate_config_valid_https_url(self, temp_git_repo):
        """Test validation with valid HTTPS URL."""
        manager = GitRepositoryManager(
            repo_url="https://github.com/test/repo.git",
            local_path=str(temp_git_repo),
            branch="master"
        )
        assert manager.repo_url == "https://github.com/test/repo.git"

    def test_validate_config_empty_url(self, temp_git_repo):
        """Test validation fails with empty URL."""
        with pytest.raises(ValueError, match="Repository URL is required"):
            GitRepositoryManager(
                repo_url="",
                local_path=str(temp_git_repo),
                branch="master"
            )

    def test_validate_config_dangerous_protocol(self, temp_git_repo):
        """Test validation fails with dangerous protocol."""
        with pytest.raises(ValueError, match="Unsupported or dangerous protocol"):
            GitRepositoryManager(
                repo_url="file:///etc/passwd",
                local_path=str(temp_git_repo),
                branch="master"
            )

    def test_validate_ssh_key_not_found(self, temp_git_repo):
        """Test validation fails with missing SSH key."""
        with pytest.raises(ValueError, match="SSH key not found"):
            GitRepositoryManager(
                repo_url="git@github.com:test/repo.git",
                local_path=str(temp_git_repo),
                branch="master",
                ssh_key_path="/nonexistent/key.pem"
            )

    def test_validate_ssh_key_permissions_warning(self, temp_git_repo, caplog):
        """Test warning for overly permissive SSH key."""
        # Create a temporary SSH key with wrong permissions
        key_file = temp_git_repo / "id_rsa"
        key_file.write_text("fake ssh key")
        key_file.chmod(0o644)  # Too permissive

        # Skip test on Windows (no Unix permissions)
        if os.name == 'nt':
            pytest.skip("Unix permissions test not applicable on Windows")

        manager = GitRepositoryManager(
            repo_url="git@github.com:test/repo.git",
            local_path=str(temp_git_repo / "repo"),
            branch="master",
            ssh_key_path=str(key_file)
        )

        # Check warning was logged
        assert "overly permissive permissions" in caplog.text

    def test_strict_host_key_checking_default(self, temp_git_repo):
        """Test strict host key checking is enabled by default."""
        manager = GitRepositoryManager(
            repo_url="git@github.com:test/repo.git",
            local_path=str(temp_git_repo),
            branch="master"
        )
        assert manager.strict_host_key_checking is True

    def test_strict_host_key_checking_disabled_warning(self, temp_git_repo, caplog):
        """Test warning when strict host key checking is disabled."""
        manager = GitRepositoryManager(
            repo_url="git@github.com:test/repo.git",
            local_path=str(temp_git_repo),
            branch="master",
            strict_host_key_checking=False
        )
        assert "host key checking is disabled" in caplog.text.lower()

    def test_git_env_with_ssh_key(self, temp_git_repo):
        """Test Git environment variables with SSH key."""
        key_file = temp_git_repo / "id_rsa"
        key_file.write_text("fake ssh key")

        manager = GitRepositoryManager(
            repo_url="git@github.com:test/repo.git",
            local_path=str(temp_git_repo / "repo"),
            branch="master",
            ssh_key_path=str(key_file),
            strict_host_key_checking=True
        )

        env = manager._get_git_env()
        assert "GIT_SSH_COMMAND" in env
        assert str(key_file) in env["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=yes" in env["GIT_SSH_COMMAND"]

    @patch('app.services.git_metadata_sync_service.Repo.clone_from')
    def test_clone_new_repository(self, mock_clone, temp_git_repo):
        """Test cloning a new repository."""
        # Mock the cloned repository
        mock_repo = Mock()
        mock_repo.head.commit.hexsha = "abc123"
        mock_repo.active_branch.name = "master"
        mock_clone.return_value = mock_repo

        manager = GitRepositoryManager(
            repo_url="https://github.com/test/repo.git",
            local_path=str(temp_git_repo / "repo"),
            branch="master"
        )

        success, commit_hash = manager.clone_or_pull()

        assert success is True
        assert commit_hash == "abc123"
        mock_clone.assert_called_once()


# ==================== PytestMetadataExtractor Tests ====================


class TestPytestMetadataExtractor:
    """Tests for PytestMetadataExtractor class."""

    def test_discover_tests_empty_directory(self, temp_git_repo):
        """Test discovery with empty directory."""
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        tests, failed_files = extractor.discover_tests()
        assert tests == []
        assert failed_files == []

    def test_extract_topology_from_decorator(self, temp_git_repo):
        """Test extracting topology from @pytest.mark.testbed decorator."""
        # Create a test file with pytest markers
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
import pytest

@pytest.mark.testbed(topology='5-site')
class TestExample:
    def test_something(self):
        pass
""")

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        tests, failed_files = extractor.discover_tests()

        assert len(tests) == 1
        assert tests[0]['topology'] == '5-site'
        assert tests[0]['testcase_name'] == 'test_something'
        assert tests[0]['test_class_name'] == 'TestExample'
        assert failed_files == []

    def test_extract_testmanagement_decorator(self, temp_git_repo):
        """Test extracting metadata from @pytest.mark.testmanagement decorator."""
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
import pytest

@pytest.mark.testbed(topology='3-site')
@pytest.mark.testmanagement(qtest_tc_id='TC-12345', case=678, priority='P0')
class TestExample:
    def test_something(self):
        pass
""")

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        tests, failed_files = extractor.discover_tests()

        assert len(tests) == 1
        assert tests[0]['testcase_id'] == 'TC-12345'
        assert tests[0]['testrail_id'] == '678'
        assert tests[0]['priority'] == 'P0'

    def test_skip_file_without_topology(self, temp_git_repo):
        """Test that tests without topology are skipped."""
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
import pytest

class TestExample:
    def test_something(self):
        pass
""")

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        tests, failed_files = extractor.discover_tests()

        assert len(tests) == 0  # No topology, should be skipped

    def test_handle_syntax_error_in_test_file(self, temp_git_repo):
        """Test handling of syntax errors in test files."""
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_broken.py"
        test_file.write_text("this is not valid python syntax $$$$")

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        tests, failed_files = extractor.discover_tests()

        assert len(failed_files) == 1
        assert "test_broken.py" in failed_files[0]

    def test_high_failure_rate_raises_exception(self, temp_git_repo):
        """Test that high failure rate raises exception."""
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        # Create 10 broken files
        for i in range(10):
            test_file = tests_dir / f"test_broken_{i}.py"
            test_file.write_text("invalid syntax $$$$")

        extractor = PytestMetadataExtractor(
            repo_path=temp_git_repo,
            tests_base_path="tests",
            staging_config_path="staging.ini"
        )

        with pytest.raises(Exception, match="failure rate too high"):
            extractor.discover_tests()


# ==================== MetadataSyncService Tests ====================


class TestMetadataSyncService:
    """Tests for MetadataSyncService class."""

    def test_normalize_test_name(self):
        """Test test name normalization (remove parametrization)."""
        assert MetadataSyncService._normalize_test_name("test_foo") == "test_foo"
        assert MetadataSyncService._normalize_test_name("test_foo[True]") == "test_foo"
        assert MetadataSyncService._normalize_test_name("test_foo[1]") == "test_foo"
        assert MetadataSyncService._normalize_test_name("test_foo[param-value]") == "test_foo"

    def test_get_existing_metadata_release_precedence(self, db_session, mock_release, mock_config):
        """Test that release-specific metadata takes precedence over global."""
        # Create global metadata
        global_metadata = TestcaseMetadata(
            testcase_name="test_example",
            topology="3-site",
            priority="P2",
            release_id=None  # Global
        )
        db_session.add(global_metadata)

        # Create release-specific metadata
        release_metadata = TestcaseMetadata(
            testcase_name="test_example",
            topology="5-site",
            priority="P0",
            release_id=mock_release.id  # Release-specific
        )
        db_session.add(release_metadata)
        db_session.commit()

        # Create service
        service = MetadataSyncService(db_session, mock_config, mock_release)
        existing = service._get_existing_metadata()

        # Release-specific should win
        assert existing["test_example"].topology == "5-site"
        assert existing["test_example"].priority == "P0"

    def test_compare_metadata_parametrized_tests(self, db_session, mock_release, mock_config):
        """Test that parametrized tests are matched to base test."""
        # Existing parametrized tests in database
        for param in ["True", "False"]:
            metadata = TestcaseMetadata(
                testcase_name=f"test_foo[{param}]",
                topology="3-site",
                release_id=mock_release.id
            )
            db_session.add(metadata)
        db_session.commit()

        service = MetadataSyncService(db_session, mock_config, mock_release)
        existing = service._get_existing_metadata()

        # Discovered test (base name, no parametrization)
        discovered = [
            {
                "testcase_name": "test_foo",
                "topology": "5-site",  # Changed
                "module": "business_policy",
                "test_class_name": "TestFoo",
                "test_path": "tests/test_foo.py",
                "test_state": "PROD",
                "testcase_id": "",
                "testrail_id": "",
                "priority": ""
            }
        ]

        to_add, to_update, to_remove = service._compare_metadata(discovered, existing)

        # Both parametrized variants should be updated
        assert len(to_add) == 0  # No new tests
        assert len(to_update) == 2  # Both parametrized variants updated
        assert len(to_remove) == 0  # Nothing removed

    def test_conditional_priority_update(self, db_session, mock_release, mock_config):
        """Test that priority is only updated when existing value is NULL."""
        # Existing test with manual priority
        existing = TestcaseMetadata(
            testcase_name="test_example",
            topology="5-site",
            priority="P0",  # Manually set
            release_id=mock_release.id
        )
        db_session.add(existing)
        db_session.commit()

        service = MetadataSyncService(db_session, mock_config, mock_release)

        # New data with different priority
        new_data = {
            "topology": "5-site",
            "priority": "P2"  # Different from database
        }

        # Should NOT update priority (existing is not NULL)
        needs_update = service._needs_update(existing, new_data)
        assert needs_update is False

    def test_conditional_priority_update_null_existing(self, db_session, mock_release, mock_config):
        """Test that priority IS updated when existing value is NULL."""
        # Existing test with NULL priority
        existing = TestcaseMetadata(
            testcase_name="test_example",
            topology="5-site",
            priority=None,  # NULL
            release_id=mock_release.id
        )
        db_session.add(existing)
        db_session.commit()

        service = MetadataSyncService(db_session, mock_config, mock_release)

        # New data with priority
        new_data = {
            "topology": "5-site",
            "priority": "P1"
        }

        # SHOULD update priority (existing is NULL)
        needs_update = service._needs_update(existing, new_data)
        assert needs_update is True

    def test_apply_updates_with_batching(self, db_session, mock_release, mock_config):
        """Test that database updates are batched correctly."""
        service = MetadataSyncService(db_session, mock_config, mock_release)

        # Create sync log
        sync_log = MetadataSyncLog(
            status='in_progress',
            sync_type=SYNC_TYPE_MANUAL,
            release_id=mock_release.id
        )
        db_session.add(sync_log)
        db_session.commit()

        # Prepare large batch of new tests (> BATCH_SIZE)
        to_add = [
            {
                "testcase_name": f"test_{i}",
                "topology": "5-site",
                "module": "test_module",
                "test_class_name": "TestClass",
                "test_path": "tests/test.py",
                "test_state": "PROD",
                "testcase_id": "",
                "testrail_id": "",
                "priority": ""
            }
            for i in range(1500)  # Exceeds batch size (1000)
        ]

        stats = service._apply_updates(to_add, [], [], sync_log.id)

        assert stats["added"] == 1500
        assert stats["updated"] == 0
        assert stats["removed"] == 0

        # Verify all added to database
        count = db_session.query(TestcaseMetadata).filter(
            TestcaseMetadata.release_id == mock_release.id
        ).count()
        assert count == 1500

    def test_sync_metadata_tracks_failed_files(self, db_session, mock_release, mock_config):
        """Test that failed files are tracked in sync log."""
        with patch.object(GitRepositoryManager, 'clone_or_pull') as mock_clone:
            with patch.object(PytestMetadataExtractor, 'discover_tests') as mock_discover:
                # Mock successful Git pull
                mock_clone.return_value = (True, "abc123")

                # Mock discovery with failed files
                mock_discover.return_value = (
                    [{"testcase_name": "test_1", "topology": "5-site", "module": "m1",
                      "test_class_name": "T", "test_path": "p", "test_state": "PROD",
                      "testcase_id": "", "testrail_id": "", "priority": ""}],
                    ["/path/to/failed1.py", "/path/to/failed2.py"]  # Failed files
                )

                service = MetadataSyncService(db_session, mock_config, mock_release)
                result = service.sync_metadata(SYNC_TYPE_MANUAL)

                # Check failed files in result
                assert result["failed_file_count"] == 2
                assert len(result["failed_files"]) == 2

                # Check failed files in database log
                sync_log = db_session.query(MetadataSyncLog).filter(
                    MetadataSyncLog.release_id == mock_release.id
                ).first()

                error_details = json.loads(sync_log.error_details)
                assert error_details["failed_file_count"] == 2


# ==================== Integration Tests ====================


class TestMetadataSyncIntegration:
    """Integration tests for full sync workflow."""

    def test_full_sync_workflow(self, db_session, mock_release, mock_config, temp_git_repo):
        """Test complete sync workflow from Git to database."""
        # Setup test repository with real test files
        tests_dir = temp_git_repo / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_integration.py"
        test_file.write_text("""
import pytest

@pytest.mark.testbed(topology='5-site')
@pytest.mark.testmanagement(qtest_tc_id='TC-001', priority='P0')
class TestIntegration:
    def test_new_feature(self):
        pass
""")

        # Mock Git operations
        with patch.object(GitRepositoryManager, 'clone_or_pull') as mock_clone:
            mock_clone.return_value = (True, "abc123")

            # Update config to use temp directory
            mock_config.GIT_REPO_LOCAL_PATH = str(temp_git_repo)
            mock_config.TEST_DISCOVERY_BASE_PATH = "tests"

            service = MetadataSyncService(db_session, mock_config, mock_release)
            result = service.sync_metadata(SYNC_TYPE_MANUAL)

            # Verify results
            assert result["status"] == SYNC_STATUS_SUCCESS
            assert result["added"] == 1
            assert result["updated"] == 0
            assert result["removed"] == 0

            # Verify database
            metadata = db_session.query(TestcaseMetadata).filter(
                TestcaseMetadata.testcase_name == "test_new_feature"
            ).first()

            assert metadata is not None
            assert metadata.topology == "5-site"
            assert metadata.test_case_id == "TC-001"
            assert metadata.priority == "P0"

            # Verify sync log
            sync_log = db_session.query(MetadataSyncLog).first()
            assert sync_log.status == SYNC_STATUS_SUCCESS
            assert sync_log.git_commit_hash == "abc123"
