"""
Performance tests for the Regression Tracker Web Application.

These tests validate that the application meets performance requirements
for response times, throughput, and concurrency handling.

Run with: pytest tests/test_performance.py -v
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict

import pytest
from httpx import AsyncClient, Client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import get_settings
from app.models.db import Base, Release, Module, Job, Build


# Performance thresholds
MAX_RESPONSE_TIME_MS = 500  # Maximum acceptable response time
MAX_LIST_RESPONSE_TIME_MS = 1000  # For list endpoints
CONCURRENT_REQUESTS = 10  # Number of concurrent requests for load tests
TARGET_THROUGHPUT = 20  # Requests per second


class PerformanceMetrics:
    """Collect and analyze performance metrics."""

    def __init__(self):
        self.response_times: List[float] = []

    def record(self, duration_ms: float):
        """Record a response time."""
        self.response_times.append(duration_ms)

    @property
    def min(self) -> float:
        """Minimum response time."""
        return min(self.response_times) if self.response_times else 0

    @property
    def max(self) -> float:
        """Maximum response time."""
        return max(self.response_times) if self.response_times else 0

    @property
    def avg(self) -> float:
        """Average response time."""
        return sum(self.response_times) / len(self.response_times) if self.response_times else 0

    @property
    def p95(self) -> float:
        """95th percentile response time."""
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.95)
        return sorted_times[index]

    @property
    def p99(self) -> float:
        """99th percentile response time."""
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.99)
        return sorted_times[index]

    def print_summary(self, test_name: str):
        """Print performance summary."""
        print(f"\n{test_name} Performance Metrics:")
        print(f"  Min:  {self.min:.2f}ms")
        print(f"  Avg:  {self.avg:.2f}ms")
        print(f"  P95:  {self.p95:.2f}ms")
        print(f"  P99:  {self.p99:.2f}ms")
        print(f"  Max:  {self.max:.2f}ms")


@pytest.mark.asyncio
async def test_homepage_response_time():
    """Test that homepage responds within acceptable time."""
    metrics = PerformanceMetrics()

    async with AsyncClient(app=app, base_url="http://test") as client:
        for _ in range(10):
            start = time.time()
            response = await client.get("/")
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)

            assert response.status_code == 200

    metrics.print_summary("Homepage")
    assert metrics.avg < MAX_RESPONSE_TIME_MS, f"Average response time {metrics.avg:.2f}ms exceeds {MAX_RESPONSE_TIME_MS}ms"
    assert metrics.p95 < MAX_RESPONSE_TIME_MS * 1.5, f"P95 response time {metrics.p95:.2f}ms too high"


@pytest.mark.asyncio
async def test_api_releases_response_time(sample_data):
    """Test that releases API responds within acceptable time."""
    metrics = PerformanceMetrics()

    async with AsyncClient(app=app, base_url="http://test") as client:
        for _ in range(10):
            start = time.time()
            response = await client.get("/api/releases")
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)

            assert response.status_code == 200

    metrics.print_summary("Releases API")
    assert metrics.avg < MAX_LIST_RESPONSE_TIME_MS, f"Average response time {metrics.avg:.2f}ms exceeds {MAX_LIST_RESPONSE_TIME_MS}ms"


@pytest.mark.asyncio
async def test_api_job_details_response_time(sample_data):
    """Test that job details API responds within acceptable time."""
    metrics = PerformanceMetrics()

    async with AsyncClient(app=app, base_url="http://test") as client:
        # Get a sample job first
        releases_response = await client.get("/api/releases")
        releases = releases_response.json()
        if not releases:
            pytest.skip("No test data available")

        release = releases[0]
        modules_response = await client.get(f"/api/releases/{release['id']}/modules")
        modules = modules_response.json()
        if not modules:
            pytest.skip("No modules available")

        module = modules[0]
        jobs_response = await client.get(f"/api/modules/{module['id']}/jobs")
        jobs = jobs_response.json()
        if not jobs:
            pytest.skip("No jobs available")

        job_id = jobs[0]['id']

        # Test job details endpoint
        for _ in range(10):
            start = time.time()
            response = await client.get(f"/api/jobs/{job_id}")
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)

            assert response.status_code == 200

    metrics.print_summary("Job Details API")
    assert metrics.avg < MAX_RESPONSE_TIME_MS, f"Average response time {metrics.avg:.2f}ms exceeds {MAX_RESPONSE_TIME_MS}ms"


@pytest.mark.asyncio
async def test_concurrent_requests():
    """Test application under concurrent load."""
    metrics = PerformanceMetrics()
    num_requests = CONCURRENT_REQUESTS

    async def make_request(client: AsyncClient):
        """Make a single request and record timing."""
        start = time.time()
        response = await client.get("/api/releases")
        duration_ms = (time.time() - start) * 1000
        metrics.record(duration_ms)
        return response.status_code

    async with AsyncClient(app=app, base_url="http://test") as client:
        # Fire concurrent requests
        tasks = [make_request(client) for _ in range(num_requests)]
        status_codes = await asyncio.gather(*tasks)

        # All requests should succeed
        assert all(code == 200 for code in status_codes)

    metrics.print_summary(f"Concurrent Load ({num_requests} requests)")
    assert metrics.avg < MAX_LIST_RESPONSE_TIME_MS * 2, "Average response time too high under load"
    assert metrics.p95 < MAX_LIST_RESPONSE_TIME_MS * 3, "P95 response time too high under load"


@pytest.mark.asyncio
async def test_throughput():
    """Test application throughput (requests per second)."""
    num_requests = 100
    start_time = time.time()

    async with AsyncClient(app=app, base_url="http://test") as client:
        tasks = [client.get("/api/releases") for _ in range(num_requests)]
        responses = await asyncio.gather(*tasks)

        # All requests should succeed
        assert all(r.status_code == 200 for r in responses)

    duration = time.time() - start_time
    throughput = num_requests / duration

    print(f"\nThroughput: {throughput:.2f} req/s ({num_requests} requests in {duration:.2f}s)")
    assert throughput >= TARGET_THROUGHPUT, f"Throughput {throughput:.2f} req/s below target {TARGET_THROUGHPUT} req/s"


def test_database_query_performance(sample_data):
    """Test database query performance."""
    from app.database import SessionLocal

    db = SessionLocal()
    metrics = PerformanceMetrics()

    try:
        # Test 1: Count all releases
        start = time.time()
        release_count = db.query(Release).count()
        duration_ms = (time.time() - start) * 1000
        metrics.record(duration_ms)
        print(f"  Release count query: {duration_ms:.2f}ms ({release_count} releases)")

        # Test 2: Get all modules for first release
        release = db.query(Release).first()
        if release:
            start = time.time()
            modules = db.query(Module).filter(Module.release_id == release.id).all()
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)
            print(f"  Module query: {duration_ms:.2f}ms ({len(modules)} modules)")

        # Test 3: Get all jobs for first module
        module = db.query(Module).first()
        if module:
            start = time.time()
            jobs = db.query(Job).filter(Job.module_id == module.id).all()
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)
            print(f"  Job query: {duration_ms:.2f}ms ({len(jobs)} jobs)")

        # Test 4: Get all builds for first job
        job = db.query(Job).first()
        if job:
            start = time.time()
            builds = db.query(Build).filter(Build.job_id == job.id).all()
            duration_ms = (time.time() - start) * 1000
            metrics.record(duration_ms)
            print(f"  Build query: {duration_ms:.2f}ms ({len(builds)} builds)")

    finally:
        db.close()

    # Database queries should be fast
    assert metrics.avg < 100, f"Average database query time {metrics.avg:.2f}ms too high"


@pytest.mark.asyncio
async def test_large_payload_handling():
    """Test handling of large API responses."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Request all releases with their modules (potentially large)
        start = time.time()
        response = await client.get("/api/releases")
        duration_ms = (time.time() - start) * 1000

        assert response.status_code == 200
        data = response.json()

        print(f"\nLarge payload test: {duration_ms:.2f}ms ({len(data)} releases)")
        assert duration_ms < MAX_LIST_RESPONSE_TIME_MS * 2, "Large payload response time too high"


def test_memory_leak_detection():
    """Test for potential memory leaks during repeated operations."""
    import gc
    import tracemalloc

    tracemalloc.start()

    # Take initial snapshot
    gc.collect()
    snapshot1 = tracemalloc.take_snapshot()

    # Perform many operations
    with Client(app=app, base_url="http://test") as client:
        for _ in range(100):
            response = client.get("/api/releases")
            assert response.status_code == 200

    # Take final snapshot
    gc.collect()
    snapshot2 = tracemalloc.take_snapshot()

    # Compare snapshots
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')

    # Get top 3 memory increases
    print("\nTop 3 memory increases:")
    for stat in top_stats[:3]:
        print(f"  {stat}")

    # Check that memory didn't grow excessively (allow 10MB growth)
    total_diff = sum(stat.size_diff for stat in top_stats)
    max_allowed_bytes = 10 * 1024 * 1024  # 10MB

    tracemalloc.stop()

    assert total_diff < max_allowed_bytes, f"Memory grew by {total_diff / 1024 / 1024:.2f}MB (max allowed: 10MB)"


@pytest.fixture
def sample_data():
    """Create sample data for performance tests."""
    from app.database import SessionLocal, engine
    from app.models.db import Base

    # Create tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Create sample release if not exists
        if db.query(Release).count() == 0:
            release = Release(name="1.0.0", description="Test release")
            db.add(release)
            db.commit()
            db.refresh(release)

            # Add sample module
            module = Module(
                name="test-module",
                release_id=release.id,
                description="Test module"
            )
            db.add(module)
            db.commit()
            db.refresh(module)

            # Add sample job
            job = Job(
                name="test-job",
                module_id=module.id,
                jenkins_url="http://test.com/job/test"
            )
            db.add(job)
            db.commit()

        yield

    finally:
        db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
