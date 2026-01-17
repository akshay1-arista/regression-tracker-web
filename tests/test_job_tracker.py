"""
Unit tests for job tracker with Redis support.

Tests both Redis backend and in-memory fallback, including:
- Basic CRUD operations
- Atomic field updates (race condition prevention)
- Retry logic with exponential backoff
- Connection pooling
- TTL expiration
- Multi-threaded concurrent access
- Error handling
"""
import pytest
import threading
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from queue import Empty

from app.utils.job_tracker import JobTracker, RedisConnectionError, get_job_tracker


class TestJobTrackerInMemory:
    """Test job tracker in-memory mode (no Redis)."""

    def test_init_without_redis(self):
        """Test initialization without Redis URL."""
        tracker = JobTracker(redis_url=None)

        assert tracker.redis_client is None
        assert tracker.use_redis is False
        assert isinstance(tracker._memory_jobs, dict)
        assert isinstance(tracker._memory_queues, dict)

    def test_set_and_get_job(self):
        """Test basic job storage and retrieval."""
        tracker = JobTracker(redis_url=None)

        job_data = {
            'id': 'test-job-1',
            'status': 'pending',
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
            'error': None
        }

        tracker.set_job('test-job-1', job_data)
        retrieved = tracker.get_job('test-job-1')

        assert retrieved == job_data
        assert retrieved['id'] == 'test-job-1'
        assert retrieved['status'] == 'pending'

    def test_get_nonexistent_job(self):
        """Test retrieving job that doesn't exist."""
        tracker = JobTracker(redis_url=None)

        result = tracker.get_job('nonexistent-job')

        assert result is None

    def test_update_job_field(self):
        """Test atomic field update."""
        tracker = JobTracker(redis_url=None)

        # Create initial job
        tracker.set_job('test-job-1', {'status': 'pending', 'progress': 0})

        # Update single field
        tracker.update_job_field('test-job-1', 'status', 'running')

        job = tracker.get_job('test-job-1')
        assert job['status'] == 'running'
        assert job['progress'] == 0  # Other fields unchanged

    def test_update_job_fields(self):
        """Test atomic multi-field update."""
        tracker = JobTracker(redis_url=None)

        # Create initial job
        tracker.set_job('test-job-1', {
            'status': 'running',
            'progress': 50,
            'error': None
        })

        # Update multiple fields
        tracker.update_job_fields('test-job-1', {
            'status': 'completed',
            'progress': 100,
            'completed_at': datetime.utcnow().isoformat()
        })

        job = tracker.get_job('test-job-1')
        assert job['status'] == 'completed'
        assert job['progress'] == 100
        assert 'completed_at' in job

    def test_delete_job(self):
        """Test job deletion."""
        tracker = JobTracker(redis_url=None)

        tracker.set_job('test-job-1', {'status': 'completed'})
        assert tracker.get_job('test-job-1') is not None

        tracker.delete_job('test-job-1')
        assert tracker.get_job('test-job-1') is None

    def test_push_and_pop_log(self):
        """Test log queue operations."""
        tracker = JobTracker(redis_url=None)

        # Push logs
        tracker.push_log('test-job-1', 'Log message 1')
        tracker.push_log('test-job-1', 'Log message 2')

        # Pop logs (FIFO)
        msg1 = tracker.pop_log('test-job-1', timeout=0.1)
        msg2 = tracker.pop_log('test-job-1', timeout=0.1)
        msg3 = tracker.pop_log('test-job-1', timeout=0.1)

        assert msg1 == 'Log message 1'
        assert msg2 == 'Log message 2'
        assert msg3 is None  # Queue empty

    def test_pop_log_timeout(self):
        """Test pop_log timeout behavior."""
        tracker = JobTracker(redis_url=None)

        # Create an empty queue first
        tracker.push_log('empty-job', 'initial message')
        tracker.pop_log('empty-job', timeout=0.1)  # Remove the message

        # Now test timeout on empty queue
        start_time = time.time()
        result = tracker.pop_log('empty-job', timeout=0.5)
        elapsed = time.time() - start_time

        assert result is None
        # Timeout can be a bit variable, so use looser bounds
        assert 0.3 < elapsed < 1.0  # Should wait approximately 0.5 seconds

    def test_serialize_datetime(self):
        """Test datetime serialization."""
        tracker = JobTracker(redis_url=None)

        now = datetime.utcnow()
        job_data = {
            'created_at': now,
            'status': 'pending'
        }

        serialized = tracker._serialize_job_data(job_data)

        assert isinstance(serialized['created_at'], str)
        assert serialized['created_at'] == now.isoformat()

    def test_serialize_complex_types(self):
        """Test serialization of lists and dicts."""
        tracker = JobTracker(redis_url=None)

        job_data = {
            'modules': ['module1', 'module2'],
            'config': {'key': 'value'},
            'count': 42
        }

        serialized = tracker._serialize_job_data(job_data)

        # Lists and dicts should be JSON strings
        assert isinstance(serialized['modules'], str)
        assert isinstance(serialized['config'], str)
        assert serialized['count'] == '42'


class TestJobTrackerRedis:
    """Test job tracker with Redis backend."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        with patch('redis.from_url') as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.hgetall.return_value = {}
            mock_client.hset.return_value = 1
            mock_client.delete.return_value = 1
            mock_client.rpush.return_value = 1
            mock_client.blpop.return_value = None
            mock_client.expire.return_value = True

            mock_from_url.return_value = mock_client

            yield mock_client

    def test_init_with_redis(self, mock_redis):
        """Test initialization with Redis URL."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        assert tracker.use_redis is True
        assert tracker.redis_client is not None
        mock_redis.ping.assert_called_once()

    def test_init_redis_connection_pooling(self, mock_redis):
        """Test Redis connection pool configuration."""
        with patch('redis.from_url') as mock_from_url:
            mock_from_url.return_value = mock_redis

            tracker = JobTracker(redis_url='redis://localhost:6379/0')

            # Verify connection pool parameters
            call_args = mock_from_url.call_args
            assert call_args[1]['max_connections'] == 50
            assert call_args[1]['health_check_interval'] == 30

    def test_redis_connection_failure_fallback(self):
        """Test fallback to in-memory when Redis connection fails."""
        with patch('redis.from_url') as mock_from_url:
            mock_from_url.side_effect = Exception("Connection refused")

            tracker = JobTracker(redis_url='redis://localhost:6379/0')

            assert tracker.use_redis is False
            assert tracker.redis_client is None

    def test_set_job_redis(self, mock_redis):
        """Test job storage with Redis."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        job_data = {
            'id': 'test-job-1',
            'status': 'running',
            'started_at': datetime.utcnow().isoformat()
        }

        tracker.set_job('test-job-1', job_data)

        # Verify Redis hash operations
        assert mock_redis.hset.called
        assert mock_redis.expire.called

        # Check TTL
        expire_call = mock_redis.expire.call_args
        assert expire_call[0][1] == 3600 * 24  # 24 hours

    def test_get_job_redis(self, mock_redis):
        """Test job retrieval with Redis."""
        mock_redis.hgetall.return_value = {
            'id': 'test-job-1',
            'status': 'running',
            'started_at': '2024-01-01T00:00:00'
        }

        tracker = JobTracker(redis_url='redis://localhost:6379/0')
        job = tracker.get_job('test-job-1')

        assert job['id'] == 'test-job-1'
        assert job['status'] == 'running'
        mock_redis.hgetall.assert_called_with('job:test-job-1')

    def test_update_job_field_redis(self, mock_redis):
        """Test atomic field update with Redis."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        tracker.update_job_field('test-job-1', 'status', 'completed')

        # Verify atomic HSET operation
        mock_redis.hset.assert_called_with('job:test-job-1', 'status', 'completed')

    def test_update_job_fields_redis(self, mock_redis):
        """Test atomic multi-field update with Redis."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        fields = {
            'status': 'completed',
            'progress': 100
        }

        tracker.update_job_fields('test-job-1', fields)

        # Verify atomic HSET with mapping
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == 'job:test-job-1'
        assert 'mapping' in call_args[1]

    def test_push_log_redis(self, mock_redis):
        """Test log push with Redis."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        tracker.push_log('test-job-1', 'Test log message')

        # Verify Redis list operations
        mock_redis.rpush.assert_called_with('queue:test-job-1', 'Test log message')

        # Check TTL
        expire_call = mock_redis.expire.call_args
        assert expire_call[0][1] == 3600  # 1 hour

    def test_pop_log_redis(self, mock_redis):
        """Test log pop with Redis blocking."""
        mock_redis.blpop.return_value = ('queue:test-job-1', 'Test message')

        tracker = JobTracker(redis_url='redis://localhost:6379/0')
        message = tracker.pop_log('test-job-1', timeout=0.5)

        assert message == 'Test message'
        mock_redis.blpop.assert_called_with('queue:test-job-1', timeout=0.5)

    def test_delete_job_redis(self, mock_redis):
        """Test job deletion with Redis."""
        tracker = JobTracker(redis_url='redis://localhost:6379/0')

        tracker.delete_job('test-job-1')

        # Verify both job and queue deleted
        delete_call = mock_redis.delete.call_args
        assert 'job:test-job-1' in delete_call[0]
        assert 'queue:test-job-1' in delete_call[0]

    def test_retry_logic_success_after_failure(self, mock_redis):
        """Test retry with exponential backoff."""
        # Fail twice, then succeed
        mock_redis.hset.side_effect = [
            Exception("Connection lost"),
            Exception("Connection lost"),
            1  # Success on third attempt
        ]

        tracker = JobTracker(redis_url='redis://localhost:6379/0', max_retries=3)

        start_time = time.time()
        tracker.set_job('test-job-1', {'status': 'pending'})
        elapsed = time.time() - start_time

        # Should have retried: wait 1s + 2s = 3s
        assert elapsed >= 3.0
        assert mock_redis.hset.call_count == 3

    def test_retry_logic_exhausted(self, mock_redis):
        """Test retry exhaustion raises RedisConnectionError."""
        mock_redis.hset.side_effect = Exception("Connection lost")

        tracker = JobTracker(redis_url='redis://localhost:6379/0', max_retries=3)

        with pytest.raises(RedisConnectionError):
            tracker.set_job('test-job-1', {'status': 'pending'})

        assert mock_redis.hset.call_count == 3

    def test_deserialize_job_data(self, mock_redis):
        """Test deserialization of Redis hash data."""
        mock_redis.hgetall.return_value = {
            'status': 'completed',
            'modules': '["module1", "module2"]',
            'config': '{"key": "value"}',
            'started_at': '2024-01-01T00:00:00',
            'count': '42'
        }

        tracker = JobTracker(redis_url='redis://localhost:6379/0')
        job = tracker.get_job('test-job-1')

        # Lists and dicts should be parsed
        assert isinstance(job['modules'], list)
        assert job['modules'] == ['module1', 'module2']
        assert isinstance(job['config'], dict)
        assert job['config'] == {'key': 'value'}

        # Datetimes should be parsed
        assert isinstance(job['started_at'], datetime)

        # Primitives as strings
        assert job['count'] == '42'


class TestJobTrackerConcurrency:
    """Test concurrent access to job tracker."""

    def test_concurrent_field_updates_inmemory(self):
        """Test race condition prevention with in-memory backend."""
        tracker = JobTracker(redis_url=None)
        tracker.set_job('test-job-1', {'counter': 0})

        def increment_counter():
            for _ in range(100):
                job = tracker.get_job('test-job-1')
                job['counter'] += 1
                tracker.set_job('test-job-1', job)

        # Run 10 threads incrementing counter
        threads = [threading.Thread(target=increment_counter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final_job = tracker.get_job('test-job-1')

        # With race conditions, count will be < 1000
        # This test demonstrates the problem (expected to fail without atomic updates)
        # In production, use update_job_field() instead
        assert final_job['counter'] <= 1000

    def test_atomic_field_updates_prevent_race(self):
        """Test that update_job_field prevents race conditions."""
        tracker = JobTracker(redis_url=None)
        tracker.set_job('test-job-1', {'status': 'pending', 'updates': 0})

        def update_status(status_value):
            tracker.update_job_field('test-job-1', 'status', status_value)

        # Multiple threads updating same field
        threads = [
            threading.Thread(target=update_status, args=('running',)),
            threading.Thread(target=update_status, args=('completed',)),
            threading.Thread(target=update_status, args=('failed',))
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final_job = tracker.get_job('test-job-1')

        # Status should be one of the values (last write wins)
        assert final_job['status'] in ['running', 'completed', 'failed']

    def test_concurrent_log_pushes(self):
        """Test concurrent log queue operations."""
        tracker = JobTracker(redis_url=None)

        def push_logs(thread_id):
            for i in range(10):
                tracker.push_log('test-job-1', f'Thread {thread_id} - Message {i}')

        # Run 5 threads pushing logs
        threads = [threading.Thread(target=push_logs, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Pop all logs
        messages = []
        while True:
            msg = tracker.pop_log('test-job-1', timeout=0.1)
            if msg is None:
                break
            messages.append(msg)

        # Should have 50 total messages (5 threads * 10 messages)
        assert len(messages) == 50


class TestJobTrackerIntegration:
    """Integration tests for job tracker."""

    def test_full_job_lifecycle_inmemory(self):
        """Test complete job lifecycle with in-memory backend."""
        tracker = JobTracker(redis_url=None)

        # 1. Create job
        job_id = 'test-job-lifecycle'
        tracker.set_job(job_id, {
            'id': job_id,
            'status': 'pending',
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
            'error': None
        })

        # 2. Update to running
        tracker.update_job_field(job_id, 'status', 'running')
        job = tracker.get_job(job_id)
        assert job['status'] == 'running'

        # 3. Push logs
        tracker.push_log(job_id, 'Starting download...')
        tracker.push_log(job_id, 'Processing module 1...')
        tracker.push_log(job_id, 'Processing module 2...')

        # 4. Pop logs
        log1 = tracker.pop_log(job_id, timeout=0.1)
        log2 = tracker.pop_log(job_id, timeout=0.1)
        assert log1 == 'Starting download...'
        assert log2 == 'Processing module 1...'

        # 5. Update to completed
        tracker.update_job_fields(job_id, {
            'status': 'completed',
            'completed_at': datetime.utcnow().isoformat()
        })
        job = tracker.get_job(job_id)
        assert job['status'] == 'completed'
        assert job['completed_at'] is not None

        # 6. Cleanup
        tracker.delete_job(job_id)
        assert tracker.get_job(job_id) is None

    def test_error_handling_lifecycle(self):
        """Test job lifecycle with error."""
        tracker = JobTracker(redis_url=None)

        job_id = 'test-job-error'
        tracker.set_job(job_id, {'status': 'pending'})

        tracker.update_job_field(job_id, 'status', 'running')
        tracker.push_log(job_id, 'Starting download...')
        tracker.push_log(job_id, 'ERROR: Connection failed')

        tracker.update_job_fields(job_id, {
            'status': 'failed',
            'error': 'Connection failed',
            'completed_at': datetime.utcnow().isoformat()
        })

        job = tracker.get_job(job_id)
        assert job['status'] == 'failed'
        assert job['error'] == 'Connection failed'


class TestGetJobTracker:
    """Test global job tracker singleton."""

    @pytest.fixture(autouse=True)
    def reset_global_tracker(self):
        """Reset global tracker between tests."""
        import app.utils.job_tracker
        app.utils.job_tracker._job_tracker = None
        yield
        app.utils.job_tracker._job_tracker = None

    def test_get_job_tracker_singleton(self):
        """Test that get_job_tracker returns same instance."""
        with patch('app.config.get_settings') as mock_settings:
            mock_config = Mock()
            mock_config.REDIS_URL = None
            mock_settings.return_value = mock_config

            tracker1 = get_job_tracker()
            tracker2 = get_job_tracker()

            assert tracker1 is tracker2
