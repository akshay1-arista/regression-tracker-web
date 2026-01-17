"""
Job tracking with Redis support for multi-worker environments.

Provides centralized job state storage that works across multiple Gunicorn workers.
Falls back to in-memory storage if Redis is not available.
"""
import json
import logging
import time
from typing import Dict, Optional, Any
from datetime import datetime
from queue import Queue, Empty

logger = logging.getLogger(__name__)


class RedisConnectionError(Exception):
    """Raised when Redis operations fail after retries."""
    pass


class JobTracker:
    """
    Manages download job state with Redis backend support.

    Uses Redis hashes for atomic field updates and automatic fallback to in-memory storage.
    """

    def __init__(self, redis_url: Optional[str] = None, max_retries: int = 3):
        """
        Initialize job tracker.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")
                      If None or connection fails, falls back to in-memory storage
            max_retries: Maximum number of retry attempts for Redis operations
        """
        self.redis_client = None
        self.use_redis = False
        self.max_retries = max_retries

        # In-memory fallback
        self._memory_jobs: Dict[str, Dict] = {}
        self._memory_queues: Dict[str, Queue] = {}

        # Try to connect to Redis if URL provided
        if redis_url:
            try:
                import redis
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    max_connections=50,  # Connection pool size
                    health_check_interval=30  # Verify connections periodically
                )
                # Test connection
                self.redis_client.ping()
                self.use_redis = True
                logger.info(f"JobTracker using Redis backend: {redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed, using in-memory fallback: {e}")
                self.redis_client = None
                self.use_redis = False
        else:
            logger.info("JobTracker using in-memory backend (single worker only)")

    def _job_key(self, job_id: str) -> str:
        """Generate Redis key for job."""
        return f"job:{job_id}"

    def _queue_key(self, job_id: str) -> str:
        """Generate Redis key for log queue."""
        return f"queue:{job_id}"

    def _retry_redis_operation(self, operation, *args, **kwargs):
        """
        Retry Redis operation with exponential backoff.

        Args:
            operation: Callable Redis operation
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Result of operation

        Raises:
            RedisConnectionError: If all retries fail
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"Redis operation failed (attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Redis operation failed after {self.max_retries} attempts: {e}")

        raise RedisConnectionError(f"Redis operation failed after {self.max_retries} retries: {last_error}")

    def set_job(self, job_id: str, job_data: Dict[str, Any]) -> None:
        """
        Store job data using Redis hash for atomic operations.

        Args:
            job_id: Unique job identifier
            job_data: Job metadata dictionary

        Raises:
            RedisConnectionError: If Redis operations fail after retries
        """
        serialized = self._serialize_job_data(job_data)

        if self.use_redis and self.redis_client:
            try:
                def _set_hash():
                    # Use Redis hash for atomic field updates
                    self.redis_client.hset(self._job_key(job_id), mapping=serialized)
                    self.redis_client.expire(self._job_key(job_id), 3600 * 24)  # 24 hour TTL

                self._retry_redis_operation(_set_hash)
            except RedisConnectionError as e:
                # Critical: Don't fall back silently in multi-worker environment
                logger.error(f"Job tracking unavailable for {job_id}: {e}")
                raise
        else:
            self._memory_jobs[job_id] = job_data

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve job data from Redis hash.

        Args:
            job_id: Unique job identifier

        Returns:
            Job data dictionary or None if not found

        Raises:
            RedisConnectionError: If Redis operations fail after retries
        """
        if self.use_redis and self.redis_client:
            try:
                data = self._retry_redis_operation(
                    self.redis_client.hgetall,
                    self._job_key(job_id)
                )
                if data:
                    return self._deserialize_job_data(data)
                return None
            except RedisConnectionError as e:
                logger.error(f"Failed to get job {job_id}: {e}")
                raise
        else:
            return self._memory_jobs.get(job_id)

    def update_job_field(self, job_id: str, field: str, value: Any) -> bool:
        """
        Atomically update a single field in job data.

        This method prevents race conditions by using Redis HSET for atomic updates.

        Args:
            job_id: Unique job identifier
            field: Field name to update
            value: New value for field

        Returns:
            True if update succeeded, False otherwise

        Raises:
            RedisConnectionError: If Redis operations fail after retries
        """
        serialized_value = self._serialize_value(value)

        if self.use_redis and self.redis_client:
            try:
                self._retry_redis_operation(
                    self.redis_client.hset,
                    self._job_key(job_id),
                    field,
                    serialized_value
                )
                return True
            except RedisConnectionError as e:
                logger.error(f"Failed to update field {field} for job {job_id}: {e}")
                raise
        else:
            # In-memory fallback
            if job_id in self._memory_jobs:
                self._memory_jobs[job_id][field] = value
                return True
            return False

    def update_job_fields(self, job_id: str, fields: Dict[str, Any]) -> bool:
        """
        Atomically update multiple fields in job data.

        Args:
            job_id: Unique job identifier
            fields: Dictionary of field names to values

        Returns:
            True if update succeeded, False otherwise

        Raises:
            RedisConnectionError: If Redis operations fail after retries
        """
        serialized = {k: self._serialize_value(v) for k, v in fields.items()}

        if self.use_redis and self.redis_client:
            try:
                self._retry_redis_operation(
                    self.redis_client.hset,
                    self._job_key(job_id),
                    mapping=serialized
                )
                return True
            except RedisConnectionError as e:
                logger.error(f"Failed to update fields for job {job_id}: {e}")
                raise
        else:
            # In-memory fallback
            if job_id in self._memory_jobs:
                self._memory_jobs[job_id].update(fields)
                return True
            return False

    def delete_job(self, job_id: str) -> None:
        """
        Delete job data and associated logs.

        Args:
            job_id: Unique job identifier
        """
        if self.use_redis and self.redis_client:
            try:
                self._retry_redis_operation(
                    self.redis_client.delete,
                    self._job_key(job_id),
                    self._queue_key(job_id)
                )
            except RedisConnectionError as e:
                logger.error(f"Failed to delete job {job_id}: {e}")
                # Don't raise - cleanup is best-effort

        # Also clean up memory
        self._memory_jobs.pop(job_id, None)
        self._memory_queues.pop(job_id, None)

    def push_log(self, job_id: str, message: str) -> None:
        """
        Add log message to job's queue.

        Args:
            job_id: Unique job identifier
            message: Log message to add

        Raises:
            RedisConnectionError: If Redis operations fail after retries
        """
        if self.use_redis and self.redis_client:
            try:
                def _push():
                    self.redis_client.rpush(self._queue_key(job_id), message)
                    self.redis_client.expire(self._queue_key(job_id), 3600)  # 1 hour TTL

                self._retry_redis_operation(_push)
            except RedisConnectionError as e:
                logger.error(f"Failed to push log for job {job_id}: {e}")
                raise
        else:
            if job_id not in self._memory_queues:
                self._memory_queues[job_id] = Queue()
            self._memory_queues[job_id].put(message)

    def pop_log(self, job_id: str, timeout: float = 0.5) -> Optional[str]:
        """
        Get next log message from job's queue (blocking with timeout).

        Args:
            job_id: Unique job identifier
            timeout: Maximum time to wait for message

        Returns:
            Log message or None if timeout
        """
        if self.use_redis and self.redis_client:
            try:
                # Redis BLPOP returns (key, value) tuple or None
                result = self.redis_client.blpop(self._queue_key(job_id), timeout=timeout)
                if result:
                    return result[1]  # Return the value
                return None
            except Exception as e:
                # Non-critical operation, log but don't raise
                logger.warning(f"Redis pop_log failed for {job_id}: {e}")
                return None
        else:
            if job_id in self._memory_queues:
                try:
                    return self._memory_queues[job_id].get(timeout=timeout)
                except Empty:
                    return None
            return None

    def _serialize_value(self, value: Any) -> str:
        """
        Serialize a single value for Redis storage.

        Args:
            value: Value to serialize

        Returns:
            Serialized string
        """
        if isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, (list, dict)):
            return json.dumps(value)
        else:
            return str(value)

    def _serialize_job_data(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        Serialize job data for Redis hash storage.

        Converts datetime objects and other non-string types to strings.

        Args:
            data: Job data dictionary

        Returns:
            Dictionary with all values as strings
        """
        serialized = {}
        for key, value in data.items():
            serialized[key] = self._serialize_value(value)
        return serialized

    def _deserialize_job_data(self, data: Dict[str, str]) -> Dict[str, Any]:
        """
        Deserialize job data from Redis hash.

        Attempts to parse JSON strings and convert ISO datetime strings.

        Args:
            data: Raw data from Redis hash

        Returns:
            Deserialized job data dictionary
        """
        deserialized = {}
        for key, value in data.items():
            # Try to parse as JSON first (for lists/dicts)
            if value and value[0] in ['{', '[']:
                try:
                    deserialized[key] = json.loads(value)
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass

            # Try to parse as datetime (ISO format)
            if isinstance(value, str) and 'T' in value:
                try:
                    deserialized[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    continue
                except (ValueError, AttributeError):
                    pass

            # Keep as string
            deserialized[key] = value

        return deserialized


# Global job tracker instance
_job_tracker: Optional[JobTracker] = None


def get_job_tracker() -> JobTracker:
    """
    Get or create global job tracker instance.

    Returns:
        JobTracker instance
    """
    global _job_tracker

    if _job_tracker is None:
        from app.config import get_settings
        settings = get_settings()
        _job_tracker = JobTracker(redis_url=settings.REDIS_URL if settings.REDIS_URL else None)

    return _job_tracker
