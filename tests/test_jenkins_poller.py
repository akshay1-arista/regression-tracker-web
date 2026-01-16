"""
Tests for Jenkins background polling task.

Tests for app/tasks/jenkins_poller.py:
- Polling logic for all releases
- Single release polling
- New build detection
- Error handling (requests, JSON, credentials)
- Resource cleanup (context managers)
- Logging behavior
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
import json

import requests

from app.tasks.jenkins_poller import (
    poll_jenkins_for_all_releases,
    poll_release,
    log_polling_result
)
from app.models.db_models import Release, Module, Job


@pytest.fixture
def mock_db_context():
    """Mock database context manager."""
    mock_db = MagicMock()
    mock_context = MagicMock()
    mock_context.__enter__ = Mock(return_value=mock_db)
    mock_context.__exit__ = Mock(return_value=False)

    with patch('app.tasks.jenkins_poller.get_db_context', return_value=mock_context):
        yield mock_db


@pytest.fixture
def mock_release():
    """Create a mock release."""
    release = Mock(spec=Release)
    release.id = 1
    release.name = "7.0.0.0"
    release.jenkins_job_url = "https://jenkins.example.com/job/test-job"
    release.is_active = True
    return release


@pytest.fixture
def mock_jenkins_credentials():
    """Mock Jenkins credentials."""
    with patch('app.tasks.jenkins_poller.CredentialsManager.get_jenkins_credentials') as mock_creds:
        mock_creds.return_value = (
            "https://jenkins.example.com",
            "testuser",
            "testtoken"
        )
        yield mock_creds


@pytest.fixture
def mock_jenkins_client():
    """Mock JenkinsClient."""
    with patch('app.tasks.jenkins_poller.JenkinsClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client
        yield mock_client


class TestPollJenkinsForAllReleases:
    """Tests for poll_jenkins_for_all_releases function."""

    @pytest.mark.asyncio
    async def test_no_active_releases(self, mock_db_context):
        """Test polling when no active releases exist."""
        # Mock query to return no releases
        mock_db_context.query.return_value.filter.return_value.all.return_value = []

        await poll_jenkins_for_all_releases()

        # Should not raise exception
        # Verify query was called
        mock_db_context.query.assert_called()

    @pytest.mark.asyncio
    async def test_polls_all_active_releases(self, mock_db_context, mock_release):
        """Test that all active releases are polled."""
        release2 = Mock(spec=Release)
        release2.id = 2
        release2.name = "7.1.0.0"
        release2.jenkins_job_url = "https://jenkins.example.com/job/test-job-2"
        release2.is_active = True

        mock_db_context.query.return_value.filter.return_value.all.return_value = [
            mock_release, release2
        ]

        with patch('app.tasks.jenkins_poller.poll_release') as mock_poll:
            mock_poll.return_value = None  # Make it async compatible

            await poll_jenkins_for_all_releases()

            # Should call poll_release for each release
            assert mock_poll.call_count == 2
            mock_poll.assert_any_call(mock_db_context, mock_release)
            mock_poll.assert_any_call(mock_db_context, release2)

    @pytest.mark.asyncio
    async def test_continues_on_request_exception(self, mock_db_context, mock_release):
        """Test that polling continues when RequestException occurs."""
        release2 = Mock(spec=Release)
        release2.id = 2
        release2.name = "7.1.0.0"
        release2.jenkins_job_url = "https://jenkins.example.com/job/test-job-2"
        release2.is_active = True

        mock_db_context.query.return_value.filter.return_value.all.return_value = [
            mock_release, release2
        ]

        with patch('app.tasks.jenkins_poller.poll_release') as mock_poll:
            # First release fails, second succeeds
            mock_poll.side_effect = [
                requests.RequestException("Connection error"),
                None
            ]

            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_jenkins_for_all_releases()

                # Should log failure for first release
                mock_log.assert_any_call(mock_db_context, mock_release.id, 'failed', 0, mock_poll.side_effect[0])

                # Should still attempt second release
                assert mock_poll.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_on_json_decode_error(self, mock_db_context, mock_release):
        """Test that polling continues when JSONDecodeError occurs."""
        mock_db_context.query.return_value.filter.return_value.all.return_value = [mock_release]

        with patch('app.tasks.jenkins_poller.poll_release') as mock_poll:
            mock_poll.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_jenkins_for_all_releases()

                # Should log failure
                assert mock_log.called

    @pytest.mark.asyncio
    async def test_continues_on_value_error(self, mock_db_context, mock_release):
        """Test that polling continues when ValueError occurs."""
        mock_db_context.query.return_value.filter.return_value.all.return_value = [mock_release]

        with patch('app.tasks.jenkins_poller.poll_release') as mock_poll:
            mock_poll.side_effect = ValueError("Invalid value")

            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_jenkins_for_all_releases()

                # Should log failure
                assert mock_log.called

    @pytest.mark.asyncio
    async def test_logs_unexpected_exceptions_as_critical(self, mock_db_context, mock_release):
        """Test that unexpected exceptions are logged as critical."""
        mock_db_context.query.return_value.filter.return_value.all.return_value = [mock_release]

        with patch('app.tasks.jenkins_poller.poll_release') as mock_poll:
            mock_poll.side_effect = RuntimeError("Unexpected error")

            with patch('app.tasks.jenkins_poller.logger') as mock_logger:
                with patch('app.tasks.jenkins_poller.log_polling_result'):
                    await poll_jenkins_for_all_releases()

                    # Should log as critical
                    mock_logger.critical.assert_called()


class TestPollRelease:
    """Tests for poll_release function."""

    @pytest.mark.asyncio
    async def test_skips_release_without_jenkins_url(self, mock_db_context, mock_release):
        """Test that releases without Jenkins URL are skipped."""
        mock_release.jenkins_job_url = None

        await poll_release(mock_db_context, mock_release)

        # Should not attempt to get credentials or create client
        # No exceptions should be raised

    @pytest.mark.asyncio
    async def test_fails_when_credentials_not_configured(self, mock_db_context, mock_release):
        """Test that polling fails when credentials not configured."""
        with patch('app.tasks.jenkins_poller.CredentialsManager.get_jenkins_credentials') as mock_creds:
            mock_creds.side_effect = ValueError("Credentials not configured")

            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_release(mock_db_context, mock_release)

                # Should log failure
                mock_log.assert_called_once_with(
                    mock_db_context,
                    mock_release.id,
                    'failed',
                    0,
                    "Jenkins credentials not configured"
                )

    @pytest.mark.asyncio
    async def test_uses_jenkins_client_context_manager(
        self, mock_db_context, mock_release, mock_jenkins_credentials
    ):
        """Test that JenkinsClient is used as context manager."""
        with patch('app.tasks.jenkins_poller.JenkinsClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.download_build_map.return_value = None
            mock_client_class.return_value = mock_client

            await poll_release(mock_db_context, mock_release)

            # Verify context manager was used
            mock_client.__enter__.assert_called_once()
            mock_client.__exit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_downloads_build_map(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that build_map.json is downloaded."""
        mock_jenkins_client.download_build_map.return_value = None

        await poll_release(mock_db_context, mock_release)

        # Should attempt to download build_map
        mock_jenkins_client.download_build_map.assert_called_once_with(
            mock_release.jenkins_job_url
        )

    @pytest.mark.asyncio
    async def test_fails_when_build_map_download_fails(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that polling fails when build_map download fails."""
        mock_jenkins_client.download_build_map.return_value = None

        with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
            await poll_release(mock_db_context, mock_release)

            # Should log failure
            mock_log.assert_called_once_with(
                mock_db_context,
                mock_release.id,
                'failed',
                0,
                "Failed to download build_map.json"
            )

    @pytest.mark.asyncio
    async def test_detects_new_builds(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that new builds are detected."""
        mock_build_map = {"modules": {"business_policy": ["8", "9"]}}
        mock_jenkins_client.download_build_map.return_value = mock_build_map

        with patch('app.tasks.jenkins_poller.detect_new_builds') as mock_detect:
            mock_detect.return_value = []  # No new builds

            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_release(mock_db_context, mock_release)

                # Should call detect_new_builds
                mock_detect.assert_called_once_with(
                    mock_db_context,
                    mock_release.name,
                    mock_build_map
                )

                # Should log success with 0 modules
                mock_log.assert_called_once_with(
                    mock_db_context,
                    mock_release.id,
                    'success',
                    0,
                    None
                )

    @pytest.mark.asyncio
    async def test_downloads_and_imports_new_builds(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that new builds are downloaded and imported."""
        mock_build_map = {"modules": {"business_policy": ["8"]}}
        mock_jenkins_client.download_build_map.return_value = mock_build_map

        new_builds = [
            ("business_policy", "https://jenkins.example.com/job/bp", "8")
        ]

        # Mock module query
        mock_module = Mock(spec=Module)
        mock_module.id = 1
        mock_module.name = "business_policy"
        mock_db_context.query.return_value.filter.return_value.first.return_value = mock_module

        with patch('app.tasks.jenkins_poller.detect_new_builds') as mock_detect:
            mock_detect.return_value = new_builds

            with patch('app.tasks.jenkins_poller.parse_build_map') as mock_parse:
                mock_parse.return_value = {
                    "business_policy": ("https://jenkins.example.com/job/bp", ["8"])
                }

                with patch('app.tasks.jenkins_poller.ArtifactDownloader') as mock_downloader_class:
                    mock_downloader = Mock()
                    mock_downloader._download_module_artifacts.return_value = True
                    mock_downloader_class.return_value = mock_downloader

                    with patch('app.tasks.jenkins_poller.ImportService') as mock_import_class:
                        mock_import_service = Mock()
                        mock_import_class.return_value = mock_import_service

                        with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                            await poll_release(mock_db_context, mock_release)

                            # Should download artifacts
                            mock_downloader._download_module_artifacts.assert_called_once()

                            # Should import to database
                            mock_import_service.import_job.assert_called_once_with(
                                mock_release.name,
                                "business_policy",
                                "8"
                            )

                            # Should log success with 1 module
                            mock_log.assert_called_once_with(
                                mock_db_context,
                                mock_release.id,
                                'success',
                                1,
                                None
                            )

    @pytest.mark.asyncio
    async def test_creates_module_if_not_exists(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that module is created if it doesn't exist."""
        mock_build_map = {"modules": {"new_module": ["1"]}}
        mock_jenkins_client.download_build_map.return_value = mock_build_map

        new_builds = [
            ("new_module", "https://jenkins.example.com/job/nm", "1")
        ]

        # Mock module query to return None (doesn't exist)
        mock_db_context.query.return_value.filter.return_value.first.return_value = None

        with patch('app.tasks.jenkins_poller.detect_new_builds') as mock_detect:
            mock_detect.return_value = new_builds

            with patch('app.tasks.jenkins_poller.parse_build_map') as mock_parse:
                mock_parse.return_value = {
                    "new_module": ("https://jenkins.example.com/job/nm", ["1"])
                }

                with patch('app.tasks.jenkins_poller.ArtifactDownloader') as mock_downloader_class:
                    mock_downloader = Mock()
                    mock_downloader._download_module_artifacts.return_value = True
                    mock_downloader_class.return_value = mock_downloader

                    with patch('app.tasks.jenkins_poller.ImportService'):
                        with patch('app.tasks.jenkins_poller.log_polling_result'):
                            await poll_release(mock_db_context, mock_release)

                            # Should create new module
                            mock_db_context.add.assert_called()
                            mock_db_context.commit.assert_called()

    @pytest.mark.asyncio
    async def test_continues_on_module_download_error(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that polling continues when module download fails."""
        mock_build_map = {"modules": {"module1": ["1"], "module2": ["1"]}}
        mock_jenkins_client.download_build_map.return_value = mock_build_map

        new_builds = [
            ("module1", "https://jenkins.example.com/job/m1", "1"),
            ("module2", "https://jenkins.example.com/job/m2", "1"),
        ]

        mock_module = Mock(spec=Module)
        mock_db_context.query.return_value.filter.return_value.first.return_value = mock_module

        with patch('app.tasks.jenkins_poller.detect_new_builds') as mock_detect:
            mock_detect.return_value = new_builds

            with patch('app.tasks.jenkins_poller.parse_build_map') as mock_parse:
                mock_parse.return_value = {
                    "module1": ("https://jenkins.example.com/job/m1", ["1"]),
                    "module2": ("https://jenkins.example.com/job/m2", ["1"]),
                }

                with patch('app.tasks.jenkins_poller.ArtifactDownloader') as mock_downloader_class:
                    mock_downloader = Mock()
                    # First module fails, second succeeds
                    mock_downloader._download_module_artifacts.side_effect = [
                        requests.RequestException("Download failed"),
                        True
                    ]
                    mock_downloader_class.return_value = mock_downloader

                    with patch('app.tasks.jenkins_poller.ImportService'):
                        with patch('app.tasks.jenkins_poller.logger') as mock_logger:
                            with patch('app.tasks.jenkins_poller.log_polling_result'):
                                await poll_release(mock_db_context, mock_release)

                                # Should log error for first module
                                mock_logger.error.assert_called()

                                # Should continue to second module
                                assert mock_downloader._download_module_artifacts.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_request_exception_during_polling(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that RequestException during polling is handled."""
        mock_jenkins_client.download_build_map.side_effect = requests.RequestException("Connection error")

        with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
            await poll_release(mock_db_context, mock_release)

            # Should log failure
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[2] == 'failed'

    @pytest.mark.asyncio
    async def test_handles_json_decode_error_during_polling(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that JSONDecodeError during polling is handled."""
        mock_jenkins_client.download_build_map.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
            await poll_release(mock_db_context, mock_release)

            # Should log failure
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[2] == 'failed'

    @pytest.mark.asyncio
    async def test_logs_unexpected_exception_as_critical(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test that unexpected exceptions are logged as critical."""
        mock_jenkins_client.download_build_map.side_effect = RuntimeError("Unexpected error")

        with patch('app.tasks.jenkins_poller.logger') as mock_logger:
            with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                await poll_release(mock_db_context, mock_release)

                # Should log as critical
                mock_logger.critical.assert_called()

                # Should log failure with "Unexpected error" prefix
                mock_log.assert_called_once()
                args = mock_log.call_args[0]
                assert "Unexpected error" in args[4]


class TestLogPollingResult:
    """Tests for log_polling_result function."""

    def test_logs_success_result(self, mock_db_context):
        """Test logging successful polling result."""
        release_id = 1
        modules_downloaded = 5

        log_polling_result(mock_db_context, release_id, 'success', modules_downloaded, None)

        # Should add log entry
        mock_db_context.add.assert_called_once()
        mock_db_context.commit.assert_called_once()

        # Verify log entry fields
        log_entry = mock_db_context.add.call_args[0][0]
        assert log_entry.release_id == release_id
        assert log_entry.status == 'success'
        assert log_entry.modules_downloaded == modules_downloaded
        assert log_entry.error_message is None

    def test_logs_failed_result(self, mock_db_context):
        """Test logging failed polling result."""
        release_id = 1
        error_message = "Connection timeout"

        log_polling_result(mock_db_context, release_id, 'failed', 0, error_message)

        # Should add log entry
        mock_db_context.add.assert_called_once()
        mock_db_context.commit.assert_called_once()

        # Verify log entry fields
        log_entry = mock_db_context.add.call_args[0][0]
        assert log_entry.release_id == release_id
        assert log_entry.status == 'failed'
        assert log_entry.modules_downloaded == 0
        assert log_entry.error_message == error_message

    def test_log_includes_timestamps(self, mock_db_context):
        """Test that log entry includes timestamps."""
        log_polling_result(mock_db_context, 1, 'success', 0, None)

        log_entry = mock_db_context.add.call_args[0][0]
        assert hasattr(log_entry, 'started_at')
        assert hasattr(log_entry, 'completed_at')
        assert isinstance(log_entry.started_at, datetime)
        assert isinstance(log_entry.completed_at, datetime)


class TestPollingIntegration:
    """Integration tests for polling workflow."""

    @pytest.mark.asyncio
    async def test_complete_polling_workflow(
        self, mock_db_context, mock_release, mock_jenkins_credentials, mock_jenkins_client
    ):
        """Test complete polling workflow from start to finish."""
        # Setup
        mock_build_map = {"modules": {"business_policy": ["8"]}}
        mock_jenkins_client.download_build_map.return_value = mock_build_map

        new_builds = [("business_policy", "https://jenkins.example.com/job/bp", "8")]

        mock_module = Mock(spec=Module)
        mock_module.id = 1
        mock_db_context.query.return_value.filter.return_value.first.return_value = mock_module

        # Execute
        with patch('app.tasks.jenkins_poller.detect_new_builds', return_value=new_builds):
            with patch('app.tasks.jenkins_poller.parse_build_map') as mock_parse:
                mock_parse.return_value = {
                    "business_policy": ("https://jenkins.example.com/job/bp", ["8"])
                }

                with patch('app.tasks.jenkins_poller.ArtifactDownloader') as mock_downloader_class:
                    mock_downloader = Mock()
                    mock_downloader._download_module_artifacts.return_value = True
                    mock_downloader_class.return_value = mock_downloader

                    with patch('app.tasks.jenkins_poller.ImportService') as mock_import_class:
                        mock_import = Mock()
                        mock_import_class.return_value = mock_import

                        with patch('app.tasks.jenkins_poller.log_polling_result') as mock_log:
                            await poll_release(mock_db_context, mock_release)

                            # Verify complete workflow
                            mock_jenkins_client.download_build_map.assert_called_once()
                            mock_downloader._download_module_artifacts.assert_called_once()
                            mock_import.import_job.assert_called_once()
                            mock_log.assert_called_once_with(
                                mock_db_context,
                                mock_release.id,
                                'success',
                                1,
                                None
                            )
