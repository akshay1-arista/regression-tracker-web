"""
Tests for metadata sync admin endpoints and background tasks.

Tests cover:
- Per-release sync trigger endpoint
- All-releases sync trigger endpoint
- SSE progress streaming
- Job tracking integration
"""
import json
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.models.db_models import Release, MetadataSyncLog
from app.main import app


@pytest.fixture
def admin_headers():
    """Headers with admin PIN for authenticated requests."""
    return {"X-Admin-PIN": "1234"}  # Test PIN


@pytest.fixture
def mock_releases(db_session):
    """Create mock releases for testing."""
    releases = [
        Release(name="7.0.0.0", git_branch="master", is_active=True),
        Release(name="6.4.0.0", git_branch="release/6.4", is_active=True),
        Release(name="5.4.0.0", git_branch=None, is_active=True),  # No git_branch
    ]
    for release in releases:
        db_session.add(release)
    db_session.commit()
    return releases


class TestMetadataSyncEndpoints:
    """Tests for metadata sync API endpoints."""

    def test_trigger_sync_for_release_success(self, client: TestClient, admin_headers, mock_releases):
        """Test triggering sync for a specific release."""
        release = mock_releases[0]  # 7.0.0.0

        with patch('app.routers.admin.BackgroundTasks.add_task') as mock_add_task:
            response = client.post(
                f"/api/v1/admin/metadata-sync/trigger/{release.id}",
                headers=admin_headers
            )

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "started"
            assert "job_id" in data
            assert release.name in data["message"]

            # Verify background task was queued
            mock_add_task.assert_called_once()

    def test_trigger_sync_for_release_not_found(self, client: TestClient, admin_headers):
        """Test triggering sync for non-existent release."""
        response = client.post(
            "/api/v1/admin/metadata-sync/trigger/999",
            headers=admin_headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_trigger_sync_for_release_no_git_branch(self, client: TestClient, admin_headers, mock_releases):
        """Test triggering sync for release without git_branch."""
        release = mock_releases[2]  # 5.4.0.0 (no git_branch)

        response = client.post(
            f"/api/v1/admin/metadata-sync/trigger/{release.id}",
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "no git_branch" in response.json()["detail"].lower()

    def test_trigger_sync_all_releases(self, client: TestClient, admin_headers, mock_releases):
        """Test triggering sync for all active releases."""
        with patch('app.routers.admin.BackgroundTasks.add_task') as mock_add_task:
            response = client.post(
                "/api/v1/admin/metadata-sync/trigger",
                headers=admin_headers
            )

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "started"
            assert "job_id" in data
            assert "all active releases" in data["message"].lower()

            # Verify background task was queued
            mock_add_task.assert_called_once()

    def test_trigger_sync_requires_admin_pin(self, client: TestClient, mock_releases):
        """Test that sync trigger requires admin PIN."""
        # No PIN header
        response = client.post(
            f"/api/v1/admin/metadata-sync/trigger/{mock_releases[0].id}"
        )

        assert response.status_code in [401, 403]

        # Invalid PIN
        response = client.post(
            f"/api/v1/admin/metadata-sync/trigger/{mock_releases[0].id}",
            headers={"X-Admin-PIN": "wrong_pin"}
        )

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_progress_stream_endpoint(self, client: TestClient, admin_headers):
        """Test SSE progress streaming endpoint."""
        job_id = "test-job-123"

        # Mock job tracker
        mock_tracker = Mock()
        mock_tracker.get_logs.return_value = [
            "Starting sync...",
            "Discovered 100 tests",
            "Sync complete"
        ]
        mock_tracker.get_job_status.return_value = {
            "status": "completed",
            "success": True,
            "error": None
        }

        with patch('app.routers.admin.get_job_tracker', return_value=mock_tracker):
            with patch('app.routers.admin.EventSourceResponse') as mock_sse:
                response = client.get(
                    f"/api/v1/admin/metadata-sync/progress/{job_id}",
                    headers=admin_headers
                )

                # Verify SSE response was created
                mock_sse.assert_called_once()


class TestMetadataSyncBackgroundTasks:
    """Tests for background task functions."""

    @pytest.mark.asyncio
    async def test_run_metadata_sync_with_tracking_success(self, db_session, mock_releases):
        """Test successful metadata sync with job tracking."""
        from app.tasks.metadata_sync_background import run_metadata_sync_with_tracking

        release = mock_releases[0]
        job_id = "test-job-456"

        # Mock dependencies
        mock_tracker = Mock()
        mock_tracker.start_job = Mock()
        mock_tracker.log_message = Mock()
        mock_tracker.complete_job = Mock()

        mock_sync_result = {
            "status": "success",
            "added": 10,
            "updated": 5,
            "removed": 2,
            "failed_files": [],
            "failed_file_count": 0
        }

        with patch('app.tasks.metadata_sync_background.get_job_tracker', return_value=mock_tracker):
            with patch('app.tasks.metadata_sync_background.MetadataSyncService') as mock_service_class:
                # Mock service instance
                mock_service = Mock()
                mock_service.sync_metadata.return_value = mock_sync_result
                mock_service_class.return_value = mock_service

                # Mock config
                with patch('app.tasks.metadata_sync_background.get_settings') as mock_get_settings:
                    mock_settings = Mock()
                    mock_settings.GIT_REPO_URL = "git@github.com:test/repo.git"
                    mock_get_settings.return_value = mock_settings

                    # Run task
                    await run_metadata_sync_with_tracking(release.id, job_id, 'manual')

                    # Verify job tracking calls
                    mock_tracker.start_job.assert_called_once_with(job_id, f"Metadata sync for release {release.id}")
                    mock_tracker.complete_job.assert_called_once_with(job_id, success=True)

                    # Verify log messages
                    assert mock_tracker.log_message.call_count > 0
                    log_messages = [call[0][1] for call in mock_tracker.log_message.call_args_list]
                    assert any("Starting metadata sync" in msg for msg in log_messages)
                    assert any("Sync completed successfully" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_run_metadata_sync_with_tracking_failure(self, db_session, mock_releases):
        """Test failed metadata sync with error tracking."""
        from app.tasks.metadata_sync_background import run_metadata_sync_with_tracking

        release = mock_releases[0]
        job_id = "test-job-789"

        # Mock dependencies
        mock_tracker = Mock()
        mock_tracker.start_job = Mock()
        mock_tracker.log_message = Mock()
        mock_tracker.complete_job = Mock()

        with patch('app.tasks.metadata_sync_background.get_job_tracker', return_value=mock_tracker):
            with patch('app.tasks.metadata_sync_background.MetadataSyncService') as mock_service_class:
                # Mock service to raise exception
                mock_service = Mock()
                mock_service.sync_metadata.side_effect = Exception("Git clone failed")
                mock_service_class.return_value = mock_service

                # Mock config
                with patch('app.tasks.metadata_sync_background.get_settings') as mock_get_settings:
                    mock_settings = Mock()
                    mock_settings.GIT_REPO_URL = "git@github.com:test/repo.git"
                    mock_get_settings.return_value = mock_settings

                    # Run task
                    await run_metadata_sync_with_tracking(release.id, job_id, 'manual')

                    # Verify error handling
                    mock_tracker.complete_job.assert_called_once()
                    args, kwargs = mock_tracker.complete_job.call_args
                    assert args[0] == job_id
                    assert kwargs['success'] is False
                    assert kwargs['error'] == "Git clone failed"

                    # Verify error was logged
                    log_messages = [call[0][1] for call in mock_tracker.log_message.call_args_list]
                    assert any("ERROR" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_run_metadata_sync_all_releases_success(self, db_session, mock_releases):
        """Test syncing all active releases."""
        from app.tasks.metadata_sync_background import run_metadata_sync_all_releases

        job_id = "test-job-all"

        # Mock dependencies
        mock_tracker = Mock()
        mock_tracker.start_job = Mock()
        mock_tracker.log_message = Mock()
        mock_tracker.complete_job = Mock()

        mock_sync_result = {
            "status": "success",
            "added": 10,
            "updated": 5,
            "removed": 2,
            "failed_files": [],
            "failed_file_count": 0
        }

        with patch('app.tasks.metadata_sync_background.get_job_tracker', return_value=mock_tracker):
            with patch('app.tasks.metadata_sync_background.MetadataSyncService') as mock_service_class:
                # Mock service instance
                mock_service = Mock()
                mock_service.sync_metadata.return_value = mock_sync_result
                mock_service_class.return_value = mock_service

                # Mock config
                with patch('app.tasks.metadata_sync_background.get_settings') as mock_get_settings:
                    mock_settings = Mock()
                    mock_settings.GIT_REPO_URL = "git@github.com:test/repo.git"
                    mock_get_settings.return_value = mock_settings

                    # Run task
                    await run_metadata_sync_all_releases(job_id, 'scheduled')

                    # Verify job tracking
                    mock_tracker.start_job.assert_called_once()
                    mock_tracker.complete_job.assert_called_once_with(job_id, success=True)

                    # Verify summary was logged
                    log_messages = [call[0][1] for call in mock_tracker.log_message.call_args_list]
                    assert any("Sync Summary" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_run_metadata_sync_no_git_url_configured(self, db_session):
        """Test sync fails gracefully when Git URL not configured."""
        from app.tasks.metadata_sync_background import run_metadata_sync_with_tracking

        job_id = "test-job-no-url"

        # Mock dependencies
        mock_tracker = Mock()
        mock_tracker.start_job = Mock()
        mock_tracker.log_message = Mock()
        mock_tracker.complete_job = Mock()

        with patch('app.tasks.metadata_sync_background.get_job_tracker', return_value=mock_tracker):
            # Mock config with empty Git URL
            with patch('app.tasks.metadata_sync_background.get_settings') as mock_get_settings:
                mock_settings = Mock()
                mock_settings.GIT_REPO_URL = ""  # Not configured
                mock_get_settings.return_value = mock_settings

                # Run task
                await run_metadata_sync_with_tracking(1, job_id, 'manual')

                # Verify error was logged and job marked as failed
                mock_tracker.log_message.assert_called()
                mock_tracker.complete_job.assert_called_once()
                args, kwargs = mock_tracker.complete_job.call_args
                assert kwargs['success'] is False
                assert "not configured" in kwargs['error'].lower()


class TestJobTrackerIntegration:
    """Tests for JobTracker integration with metadata sync."""

    def test_job_tracker_stores_progress_messages(self):
        """Test that progress messages are stored in job tracker."""
        from app.tasks.metadata_sync_background import get_job_tracker

        tracker = get_job_tracker()
        job_id = "test-progress-123"

        # Start job
        tracker.start_job(job_id, "Test sync")

        # Log messages
        messages = [
            "Pulling Git repository",
            "Discovered 100 tests",
            "Added 10 tests",
            "Sync complete"
        ]

        for msg in messages:
            tracker.log_message(job_id, msg)

        # Retrieve logs
        logs = tracker.get_logs(job_id)

        assert len(logs) >= len(messages)
        for msg in messages:
            assert any(msg in log for log in logs)

    def test_job_tracker_marks_job_complete(self):
        """Test that job completion status is tracked."""
        from app.tasks.metadata_sync_background import get_job_tracker

        tracker = get_job_tracker()
        job_id = "test-complete-456"

        # Start and complete job
        tracker.start_job(job_id, "Test sync")
        tracker.complete_job(job_id, success=True)

        # Check status
        status = tracker.get_job_status(job_id)

        assert status is not None
        assert status['status'] == 'completed'
        assert status['success'] is True

    def test_job_tracker_records_errors(self):
        """Test that errors are recorded in job tracker."""
        from app.tasks.metadata_sync_background import get_job_tracker

        tracker = get_job_tracker()
        job_id = "test-error-789"

        # Start job and fail it
        tracker.start_job(job_id, "Test sync")
        tracker.complete_job(job_id, success=False, error="Connection timeout")

        # Check status
        status = tracker.get_job_status(job_id)

        assert status is not None
        assert status['status'] == 'failed'
        assert status['success'] is False
        assert status['error'] == "Connection timeout"
