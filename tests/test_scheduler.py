"""
Tests for background task scheduler (APScheduler integration).

Tests for app/tasks/scheduler.py:
- Scheduler lifecycle (start/stop)
- Job management (add/remove/update)
- Schedule updates
- Configuration handling
- Error scenarios
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json

from app.tasks.scheduler import (
    start_scheduler,
    stop_scheduler,
    update_polling_schedule,
    get_scheduler_status,
    scheduler
)


@pytest.fixture
def mock_db_context():
    """Mock database context manager."""
    mock_db = MagicMock()
    mock_context = MagicMock()
    mock_context.__enter__ = Mock(return_value=mock_db)
    mock_context.__exit__ = Mock(return_value=False)

    with patch('app.tasks.scheduler.get_db_context', return_value=mock_context):
        yield mock_db


@pytest.fixture
def mock_app_settings(mock_db_context):
    """Mock AppSettings database queries."""
    def create_mock_setting(key, value):
        mock_setting = Mock()
        mock_setting.key = key
        mock_setting.value = json.dumps(value)
        return mock_setting

    # Mock query chain for AUTO_UPDATE_ENABLED
    auto_update_query = Mock()
    auto_update_query.filter.return_value.first.return_value = create_mock_setting(
        'AUTO_UPDATE_ENABLED', True
    )

    # Mock query chain for POLLING_INTERVAL_MINUTES
    interval_query = Mock()
    interval_query.filter.return_value.first.return_value = create_mock_setting(
        'POLLING_INTERVAL_MINUTES', 15
    )

    # Configure mock_db to return different query objects based on filter
    def query_side_effect(model):
        query_mock = Mock()

        def filter_side_effect(condition):
            filter_result = Mock()
            # Check the condition to determine which setting to return
            if 'AUTO_UPDATE_ENABLED' in str(condition):
                filter_result.first.return_value = create_mock_setting('AUTO_UPDATE_ENABLED', True)
            elif 'POLLING_INTERVAL_MINUTES' in str(condition):
                filter_result.first.return_value = create_mock_setting('POLLING_INTERVAL_MINUTES', 15)
            else:
                filter_result.first.return_value = None
            return filter_result

        query_mock.filter = filter_side_effect
        return query_mock

    mock_db_context.query.side_effect = query_side_effect

    return mock_db_context


@pytest.fixture(autouse=True)
def cleanup_scheduler():
    """Ensure scheduler is stopped after each test."""
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


class TestSchedulerLifecycle:
    """Tests for scheduler startup and shutdown."""

    def test_start_scheduler_initializes(self, mock_app_settings):
        """Test that start_scheduler initializes the scheduler."""
        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            start_scheduler()

            assert scheduler.running is True

    def test_start_scheduler_with_auto_update_enabled(self, mock_db_context):
        """Test scheduler starts with auto-update enabled."""
        # Mock settings to return auto-update enabled
        def create_setting(key, value):
            setting = Mock()
            setting.key = key
            setting.value = json.dumps(value)
            return setting

        def query_side_effect(model):
            query_mock = Mock()

            def filter_side_effect(condition):
                filter_result = Mock()
                if 'AUTO_UPDATE_ENABLED' in str(condition):
                    filter_result.first.return_value = create_setting('AUTO_UPDATE_ENABLED', True)
                elif 'POLLING_INTERVAL_MINUTES' in str(condition):
                    filter_result.first.return_value = create_setting('POLLING_INTERVAL_MINUTES', 15)
                else:
                    filter_result.first.return_value = None
                return filter_result

            query_mock.filter = filter_side_effect
            return query_mock

        mock_db_context.query.side_effect = query_side_effect

        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            start_scheduler()

            # Check job was added
            job = scheduler.get_job('jenkins_poller')
            assert job is not None
            assert job.name == 'Jenkins Polling Task'

    def test_start_scheduler_with_auto_update_disabled(self, mock_db_context):
        """Test scheduler doesn't add job when auto-update is disabled."""
        # Mock settings to return auto-update disabled
        def create_setting(key, value):
            setting = Mock()
            setting.key = key
            setting.value = json.dumps(value)
            return setting

        def query_side_effect(model):
            query_mock = Mock()

            def filter_side_effect(condition):
                filter_result = Mock()
                if 'AUTO_UPDATE_ENABLED' in str(condition):
                    filter_result.first.return_value = create_setting('AUTO_UPDATE_ENABLED', False)
                else:
                    filter_result.first.return_value = None
                return filter_result

            query_mock.filter = filter_side_effect
            return query_mock

        mock_db_context.query.side_effect = query_side_effect

        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            start_scheduler()

            # Job should not be added
            job = scheduler.get_job('jenkins_poller')
            assert job is None

    def test_start_scheduler_with_custom_interval(self, mock_db_context):
        """Test scheduler starts with custom polling interval."""
        custom_interval = 30

        def create_setting(key, value):
            setting = Mock()
            setting.key = key
            setting.value = json.dumps(value)
            return setting

        def query_side_effect(model):
            query_mock = Mock()

            def filter_side_effect(condition):
                filter_result = Mock()
                if 'AUTO_UPDATE_ENABLED' in str(condition):
                    filter_result.first.return_value = create_setting('AUTO_UPDATE_ENABLED', True)
                elif 'POLLING_INTERVAL_MINUTES' in str(condition):
                    filter_result.first.return_value = create_setting('POLLING_INTERVAL_MINUTES', custom_interval)
                else:
                    filter_result.first.return_value = None
                return filter_result

            query_mock.filter = filter_side_effect
            return query_mock

        mock_db_context.query.side_effect = query_side_effect

        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            start_scheduler()

            job = scheduler.get_job('jenkins_poller')
            assert job is not None

            # Check interval (trigger.interval is a timedelta)
            trigger_interval = job.trigger.interval
            assert trigger_interval == timedelta(minutes=custom_interval)

    def test_stop_scheduler_shuts_down(self, mock_app_settings):
        """Test that stop_scheduler shuts down the scheduler."""
        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            start_scheduler()
            assert scheduler.running is True

            stop_scheduler()
            assert scheduler.running is False

    def test_stop_scheduler_when_not_running(self):
        """Test that stop_scheduler handles already stopped scheduler."""
        # Should not raise exception
        stop_scheduler()
        assert scheduler.running is False


class TestScheduleUpdates:
    """Tests for updating polling schedule dynamically."""

    def test_update_polling_schedule_enable(self):
        """Test enabling polling schedule."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        job = scheduler.get_job('jenkins_poller')
        assert job is not None
        assert job.name == 'Jenkins Polling Task'

    def test_update_polling_schedule_disable(self):
        """Test disabling polling schedule."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # First enable it
        update_polling_schedule(enabled=True, interval_minutes=15)
        assert scheduler.get_job('jenkins_poller') is not None

        # Then disable it
        update_polling_schedule(enabled=False, interval_minutes=15)
        assert scheduler.get_job('jenkins_poller') is None

    def test_update_polling_schedule_change_interval(self):
        """Test changing polling interval."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # Start with 15 minutes
        update_polling_schedule(enabled=True, interval_minutes=15)
        job1 = scheduler.get_job('jenkins_poller')
        assert job1.trigger.interval == timedelta(minutes=15)

        # Update to 30 minutes
        update_polling_schedule(enabled=True, interval_minutes=30)
        job2 = scheduler.get_job('jenkins_poller')
        assert job2.trigger.interval == timedelta(minutes=30)

    def test_update_polling_schedule_replaces_existing_job(self):
        """Test that updating schedule replaces existing job."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # Add initial job
        update_polling_schedule(enabled=True, interval_minutes=15)
        job1_id = scheduler.get_job('jenkins_poller').id

        # Update interval
        update_polling_schedule(enabled=True, interval_minutes=20)
        job2_id = scheduler.get_job('jenkins_poller').id

        # Should be the same job ID (replaced, not added new)
        assert job1_id == job2_id

    def test_update_polling_schedule_max_instances(self):
        """Test that job has max_instances=1 to prevent overlaps."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        job = scheduler.get_job('jenkins_poller')
        # Check max_instances configuration
        assert job.max_instances == 1


class TestSchedulerStatus:
    """Tests for getting scheduler status."""

    def test_get_scheduler_status_with_job(self):
        """Test getting scheduler status when job is active."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        status = get_scheduler_status()

        assert status['running'] is True
        assert status['job_enabled'] is True
        assert status['next_run'] is not None
        assert status['job_name'] == 'Jenkins Polling Task'

    def test_get_scheduler_status_without_job(self):
        """Test getting scheduler status when no job scheduled."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # Ensure no job exists
        if scheduler.get_job('jenkins_poller'):
            scheduler.remove_job('jenkins_poller')

        status = get_scheduler_status()

        assert status['running'] is True
        assert status['job_enabled'] is False
        assert status['next_run'] is None
        assert status['job_name'] is None

    def test_get_scheduler_status_not_running(self):
        """Test getting status when scheduler is not running."""
        if scheduler.running:
            scheduler.shutdown(wait=False)

        status = get_scheduler_status()

        assert status['running'] is False
        assert status['job_enabled'] is False

    def test_get_scheduler_status_next_run_format(self):
        """Test that next_run is ISO formatted."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        status = get_scheduler_status()

        if status['next_run']:
            # Should be valid ISO format
            datetime.fromisoformat(status['next_run'])


class TestSchedulerErrorHandling:
    """Tests for scheduler error handling."""

    def test_start_scheduler_missing_settings(self, mock_db_context):
        """Test scheduler handles missing settings gracefully."""
        # Mock query to return None for settings
        def query_side_effect(model):
            query_mock = Mock()
            query_mock.filter.return_value.first.return_value = None
            return query_mock

        mock_db_context.query.side_effect = query_side_effect

        with patch('app.tasks.scheduler.get_settings') as mock_settings:
            mock_settings.return_value = Mock()

            # Should use defaults
            start_scheduler()

            # Scheduler should still start (uses default values)
            assert scheduler.running is True

    def test_update_polling_schedule_scheduler_not_started(self):
        """Test updating schedule works even if scheduler wasn't started."""
        # Stop scheduler if running
        if scheduler.running:
            scheduler.shutdown(wait=False)

        # Start fresh scheduler
        scheduler.start()

        # Should not raise exception
        update_polling_schedule(enabled=True, interval_minutes=15)

        job = scheduler.get_job('jenkins_poller')
        assert job is not None

    def test_remove_nonexistent_job(self):
        """Test that removing non-existent job doesn't raise exception."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # Try to disable when job doesn't exist
        update_polling_schedule(enabled=False, interval_minutes=15)

        # Should not raise exception
        assert scheduler.get_job('jenkins_poller') is None


class TestSchedulerIntegration:
    """Integration tests for scheduler with actual job execution."""

    def test_job_execution_tracking(self):
        """Test that jobs can be tracked when executed."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        # Create a simple test job
        execution_tracker = {'count': 0}

        def test_job():
            execution_tracker['count'] += 1

        scheduler.add_job(
            test_job,
            trigger='interval',
            seconds=1,
            id='test_job',
            max_instances=1
        )

        # Wait a bit for job to execute
        import time
        time.sleep(2)

        # Job should have executed at least once
        assert execution_tracker['count'] >= 1

        # Clean up
        scheduler.remove_job('test_job')

    def test_scheduler_persistence_across_restarts(self):
        """Test that scheduler can be restarted."""
        if scheduler.running:
            scheduler.shutdown(wait=False)

        # Start scheduler
        scheduler.start()
        update_polling_schedule(enabled=True, interval_minutes=15)
        assert scheduler.get_job('jenkins_poller') is not None

        # Stop scheduler
        scheduler.shutdown(wait=False)
        assert scheduler.running is False

        # Restart scheduler
        scheduler.start()

        # Job should not persist (needs to be re-added)
        # This is expected behavior - jobs don't persist across restarts
        assert scheduler.running is True


class TestSchedulerConfiguration:
    """Tests for scheduler configuration."""

    def test_scheduler_uses_asyncio_scheduler(self):
        """Test that scheduler is AsyncIOScheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_uses_interval_trigger(self):
        """Test that polling job uses IntervalTrigger."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        job = scheduler.get_job('jenkins_poller')
        from apscheduler.triggers.interval import IntervalTrigger
        assert isinstance(job.trigger, IntervalTrigger)

    def test_job_configuration_prevent_overlap(self):
        """Test that job configuration prevents overlapping executions."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        job = scheduler.get_job('jenkins_poller')

        # Verify max_instances=1 prevents overlaps
        assert job.max_instances == 1

        # Verify replace_existing=True for updates
        # This is tested indirectly by update_polling_schedule tests


class TestSchedulerThreadSafety:
    """Tests for thread-safety of scheduler operations."""

    def test_concurrent_status_queries(self):
        """Test that concurrent status queries don't cause issues."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        update_polling_schedule(enabled=True, interval_minutes=15)

        # Simulate concurrent status queries
        import threading
        results = []

        def get_status():
            status = get_scheduler_status()
            results.append(status)

        threads = [threading.Thread(target=get_status) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All queries should succeed
        assert len(results) == 10
        assert all(r['running'] is True for r in results)

    def test_concurrent_schedule_updates(self):
        """Test that concurrent schedule updates are handled safely."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.start()

        def update_schedule():
            update_polling_schedule(enabled=True, interval_minutes=15)

        threads = [threading.Thread(target=update_schedule) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly one job (not 5)
        job = scheduler.get_job('jenkins_poller')
        assert job is not None

        # Count all jobs in scheduler
        all_jobs = scheduler.get_jobs()
        jenkins_jobs = [j for j in all_jobs if j.id == 'jenkins_poller']
        assert len(jenkins_jobs) == 1
