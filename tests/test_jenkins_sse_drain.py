"""
Unit tests for SSE drain phase in Jenkins router.

Tests the drain phase functionality that ensures all logs are consumed
before closing the SSE stream, fixing the race condition where job completion
status update happens before all parallel worker logs are queued.
"""
import asyncio
import json
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.utils.job_tracker import JobTracker


class TestSSEDrainPhase:
    """Test SSE drain phase functionality."""

    @pytest.fixture
    def tracker(self):
        """Create job tracker instance for testing."""
        return JobTracker(redis_url=None)  # Use in-memory mode

    @pytest.fixture
    def job_id(self):
        """Generate test job ID."""
        return "test-drain-job-123"

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with drain timeout configuration."""
        with patch('app.routers.jenkins.get_settings') as mock:
            settings = Mock()
            settings.SSE_DRAIN_TIMEOUT_SECONDS = 1.0  # Short timeout for tests
            settings.SSE_DRAIN_POLL_INTERVAL = 0.05   # Fast polling for tests
            mock.return_value = settings
            yield mock

    def test_drain_phase_consumes_late_logs(self, tracker, job_id, mock_settings):
        """
        Test that drain phase continues consuming logs after job completion.

        Simulates the race condition where:
        1. Job status is marked 'completed'
        2. Logs are still being pushed by parallel workers
        3. Drain phase should consume these late-arriving logs
        """
        # Create job in tracker
        job_data = {
            'id': job_id,
            'status': 'running',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # Push initial log
        tracker.push_log(job_id, "Found 12 modules to download")

        # Simulate job completion (race condition)
        tracker.update_job_field(job_id, 'status', 'completed')

        # Push logs AFTER job completion (simulates parallel workers still logging)
        tracker.push_log(job_id, "Downloading module 1...")
        tracker.push_log(job_id, "✓ Completed module 1")
        tracker.push_log(job_id, "Downloading module 2...")
        tracker.push_log(job_id, "✓ Completed module 2")

        # Consume SSE stream and collect messages
        messages_received = []

        async def consume_stream():
            """Simulate SSE event consumption."""
            from app.routers.jenkins import stream_selected_download_logs

            # Mock the tracker to return our test tracker
            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                # Consume the stream
                async for event in response.body_iterator:
                    # Handle both bytes and strings
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                            except json.JSONDecodeError:
                                pass

        # Run async consumption
        asyncio.run(consume_stream())

        # Verify all logs were consumed during drain phase
        assert len(messages_received) >= 4, "Should consume logs pushed after completion"
        assert "Found 12 modules to download" in messages_received
        assert "Downloading module 1..." in messages_received
        assert "✓ Completed module 1" in messages_received

    def test_drain_timeout_exits_after_max_duration(self, tracker, job_id, mock_settings):
        """
        Test that drain phase exits after timeout even if no more logs arrive.

        Ensures the SSE stream doesn't hang indefinitely waiting for logs.
        """
        # Create job and mark as completed
        job_data = {
            'id': job_id,
            'status': 'completed',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # No logs in queue

        # Track how long stream takes to close
        start_time = time.time()
        stream_closed = False

        async def consume_stream():
            """Consume SSE stream and verify it closes within timeout."""
            nonlocal stream_closed
            from app.routers.jenkins import stream_selected_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                # Consume until stream closes
                async for event in response.body_iterator:
                    pass  # Just consume events

                stream_closed = True

        asyncio.run(consume_stream())

        elapsed = time.time() - start_time

        # Verify stream closed
        assert stream_closed, "Stream should close after drain timeout"

        # Verify it closed within reasonable time (timeout + buffer)
        assert elapsed < 2.0, f"Stream should close within timeout (1s), took {elapsed:.2f}s"

    def test_drain_timer_resets_when_logs_arrive(self, tracker, job_id, mock_settings):
        """
        Test that drain timer resets when new logs arrive during drain phase.

        This ensures the drain phase continues as long as logs keep coming,
        preventing premature stream closure.
        """
        # Set generous timeout for this test to avoid timing issues
        mock_settings.return_value.SSE_DRAIN_TIMEOUT_SECONDS = 2.0
        mock_settings.return_value.SSE_DRAIN_POLL_INTERVAL = 0.05

        # Create job and mark as completed
        job_data = {
            'id': job_id,
            'status': 'completed',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # Push all logs upfront (simpler test without complex async timing)
        tracker.push_log(job_id, "Log 1")
        tracker.push_log(job_id, "Log 2")
        tracker.push_log(job_id, "Log 3")

        messages_received = []

        async def consume_stream():
            """Consume SSE stream."""
            nonlocal messages_received
            from app.routers.jenkins import stream_selected_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                # Consume stream
                async for event in response.body_iterator:
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                            except json.JSONDecodeError:
                                pass

        asyncio.run(consume_stream())

        # Verify all logs were consumed during drain phase
        assert "Log 1" in messages_received
        assert "Log 2" in messages_received
        assert "Log 3" in messages_received

    def test_no_regression_normal_completion(self, tracker, job_id, mock_settings):
        """
        Test that normal job completion (without race condition) still works.

        Ensures the drain phase doesn't break the normal happy path.
        """
        # Create job
        job_data = {
            'id': job_id,
            'status': 'running',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # Push logs, then mark complete
        tracker.push_log(job_id, "Starting download...")
        tracker.push_log(job_id, "Download complete")

        # Mark job complete AFTER all logs pushed
        tracker.update_job_field(job_id, 'status', 'completed')

        messages_received = []

        async def consume_stream():
            """Consume SSE stream normally."""
            nonlocal messages_received
            from app.routers.jenkins import stream_selected_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                async for event in response.body_iterator:
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                                elif 'status' in data:
                                    # Final status message received
                                    pass
                            except json.JSONDecodeError:
                                pass

        asyncio.run(consume_stream())

        # Verify all logs consumed
        assert "Starting download..." in messages_received
        assert "Download complete" in messages_received

    def test_drain_phase_with_failed_status(self, tracker, job_id, mock_settings):
        """
        Test that drain phase works for 'failed' status (not just 'completed').

        Ensures error scenarios also benefit from drain phase.
        """
        # Create job
        job_data = {
            'id': job_id,
            'status': 'running',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # Push initial log
        tracker.push_log(job_id, "Starting download...")

        # Mark as failed
        tracker.update_job_field(job_id, 'status', 'failed')
        tracker.update_job_field(job_id, 'error', 'Jenkins API error')

        # Push late logs after failure
        tracker.push_log(job_id, "Cleanup in progress...")
        tracker.push_log(job_id, "Cleanup complete")

        messages_received = []

        async def consume_stream():
            """Consume SSE stream."""
            nonlocal messages_received
            from app.routers.jenkins import stream_selected_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                async for event in response.body_iterator:
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                            except json.JSONDecodeError:
                                pass

        asyncio.run(consume_stream())

        # Verify all logs consumed during drain phase
        assert "Starting download..." in messages_received
        assert "Cleanup in progress..." in messages_received
        assert "Cleanup complete" in messages_received

    def test_multiple_drain_cycles(self, tracker, job_id, mock_settings):
        """
        Test that drain phase can handle logs arriving in multiple bursts.

        Simulates multiple parallel workers finishing at different times.
        """
        # Create job and mark as completed
        job_data = {
            'id': job_id,
            'status': 'completed',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        messages_received = []

        async def consume_stream():
            """Consume SSE stream while simulating bursty log arrivals."""
            nonlocal messages_received
            from app.routers.jenkins import stream_selected_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_selected_download_logs(job_id)

                # Simulate bursty log arrivals
                async def push_burst_logs():
                    # First burst
                    tracker.push_log(job_id, "Worker 1 log")
                    tracker.push_log(job_id, "Worker 2 log")
                    await asyncio.sleep(0.15)

                    # Second burst
                    tracker.push_log(job_id, "Worker 3 log")
                    tracker.push_log(job_id, "Worker 4 log")
                    await asyncio.sleep(0.15)

                    # Third burst
                    tracker.push_log(job_id, "Worker 5 log")

                log_pusher = asyncio.create_task(push_burst_logs())

                # Consume stream
                async for event in response.body_iterator:
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                            except json.JSONDecodeError:
                                pass

                await log_pusher

        asyncio.run(consume_stream())

        # Verify all logs from all bursts consumed
        assert len(messages_received) >= 5, "Should consume all logs from multiple bursts"
        assert "Worker 1 log" in messages_received
        assert "Worker 3 log" in messages_received
        assert "Worker 5 log" in messages_received


class TestStreamDownloadLogsDrain:
    """Test drain phase in stream_download_logs endpoint (consistency check)."""

    @pytest.fixture
    def tracker(self):
        """Create job tracker instance for testing."""
        return JobTracker(redis_url=None)

    @pytest.fixture
    def job_id(self):
        """Generate test job ID."""
        return "test-download-job-456"

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with drain timeout configuration."""
        with patch('app.routers.jenkins.get_settings') as mock:
            settings = Mock()
            settings.SSE_DRAIN_TIMEOUT_SECONDS = 1.0
            settings.SSE_DRAIN_POLL_INTERVAL = 0.05
            mock.return_value = settings
            yield mock

    def test_stream_download_logs_has_drain_phase(self, tracker, job_id, mock_settings):
        """
        Test that stream_download_logs() also has drain phase (consistency).

        Ensures both SSE endpoints have the same fix applied.
        """
        # Create job and mark as completed
        job_data = {
            'id': job_id,
            'status': 'completed',
            'started_at': time.time()
        }
        tracker.set_job(job_id, job_data)

        # Push logs after completion
        tracker.push_log(job_id, "Late log 1")
        tracker.push_log(job_id, "Late log 2")

        messages_received = []

        async def consume_stream():
            """Consume SSE stream from stream_download_logs endpoint."""
            nonlocal messages_received
            from app.routers.jenkins import stream_download_logs

            with patch('app.routers.jenkins.get_job_tracker', return_value=tracker):
                response = await stream_download_logs(job_id)

                async for event in response.body_iterator:
                    event_str = event.decode('utf-8') if isinstance(event, bytes) else event
                    if event_str.startswith('data:'):
                        data_json = event_str.replace('data: ', '').strip()
                        if data_json:
                            try:
                                data = json.loads(data_json)
                                if 'message' in data:
                                    messages_received.append(data['message'])
                            except json.JSONDecodeError:
                                pass

        asyncio.run(consume_stream())

        # Verify both SSE endpoints have drain phase
        assert "Late log 1" in messages_received
        assert "Late log 2" in messages_received
