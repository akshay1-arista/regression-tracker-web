"""
Job tracking with Redis support for multi-worker environments.

Provides centralized job state storage that works across multiple Gunicorn workers.
Falls back to in-memory storage if Redis is not available.
"""
import json
import logging
from typing import Dict, Optional, Any
from datetime import datetime
from queue import Queue

logger = logging.getLogger(__name__)


class JobTracker:
    """
    Manages download job state with Redis backend support.

    Automatically falls back to in-memory storage if Redis is unavailable.
    """

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize job tracker.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")
                      If None or connection fails, falls back to in-memory storage
        """
        self.redis_client = None
        self.use_redis = False

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
                    socket_timeout=2
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

    def set_job(self, job_id: str, job_data: Dict[str, Any]) -> None:
        """
        Store job data.

        Args:
            job_id: Unique job identifier
            job_data: Job metadata dictionary
        """
        if self.use_redis and self.redis_client:
            try:
                # Serialize datetimes and complex objects
                serialized = self._serialize_job_data(job_data)
                self.redis_client.setex(
                    self._job_key(job_id),
                    3600 * 24,  # 24 hour TTL
                    json.dumps(serialized)
                )
            except Exception as e:
                logger.error(f"Redis set_job failed for {job_id}: {e}")
                # Fallback to memory
                self._memory_jobs[job_id] = job_data
        else:
            self._memory_jobs[job_id] = job_data

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve job data.

        Args:
            job_id: Unique job identifier

        Returns:
            Job data dictionary or None if not found
        """
        if self.use_redis and self.redis_client:
            try:
                data = self.redis_client.get(self._job_key(job_id))
                if data:
                    return json.loads(data)
                return None
            except Exception as e:
                logger.error(f"Redis get_job failed for {job_id}: {e}")
                # Fallback to memory
                return self._memory_jobs.get(job_id)
        else:
            return self._memory_jobs.get(job_id)

    def delete_job(self, job_id: str) -> None:
        """
        Delete job data.

        Args:
            job_id: Unique job identifier
        """
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.delete(self._job_key(job_id))
                self.redis_client.delete(self._queue_key(job_id))
            except Exception as e:
                logger.error(f"Redis delete_job failed for {job_id}: {e}")

        # Also clean up memory
        self._memory_jobs.pop(job_id, None)
        self._memory_queues.pop(job_id, None)

    def push_log(self, job_id: str, message: str) -> None:
        """
        Add log message to job's queue.

        Args:
            job_id: Unique job identifier
            message: Log message to add
        """
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.rpush(self._queue_key(job_id), message)
                self.redis_client.expire(self._queue_key(job_id), 3600)  # 1 hour TTL
            except Exception as e:
                logger.error(f"Redis push_log failed for {job_id}: {e}")
                # Fallback to memory queue
                if job_id not in self._memory_queues:
                    self._memory_queues[job_id] = Queue()
                self._memory_queues[job_id].put(message)
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
                logger.error(f"Redis pop_log failed for {job_id}: {e}")
                # Fallback to memory queue
                if job_id in self._memory_queues:
                    try:
                        return self._memory_queues[job_id].get(timeout=timeout)
                    except:
                        return None
                return None
        else:
            if job_id in self._memory_queues:
                try:
                    from queue import Empty
                    return self._memory_queues[job_id].get(timeout=timeout)
                except Empty:
                    return None
            return None

    def _serialize_job_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serialize job data for JSON storage.

        Converts datetime objects and other non-JSON types to strings.
        """
        serialized = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif isinstance(value, (list, dict)):
                serialized[key] = value
            else:
                serialized[key] = value
        return serialized


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
