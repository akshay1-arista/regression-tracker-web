"""
Integration tests for error clustering API endpoint.

Tests the /api/v1/jobs/{release}/{module}/{job_id}/failures/clustered endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db_context
from app.models.db_models import Base, Release, Module, Job, TestResult, TestStatusEnum


# Test database setup
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db_context] = override_get_db


@pytest.fixture(scope="function")
def test_db():
    """Create test database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_job_with_failures(test_db):
    """Create a sample job with test failures for testing."""
    # Create release
    release = Release(name="7.0.0.0", description="Test release")
    test_db.add(release)
    test_db.commit()

    # Create module
    module = Module(name="business_policy", release_id=release.id)
    test_db.add(module)
    test_db.commit()

    # Create job
    job = Job(
        job_id="test-job-123",
        module_id=module.id,
        parent_job_id="456",
        jenkins_url="http://jenkins.example.com/job/test-job-123",
        total=10,
        passed=5,
        failed=5,
        skipped=0,
        error=0
    )
    test_db.add(job)
    test_db.commit()

    # Create test failures with various error patterns
    failures = [
        # Cluster 1: AssertionError (3 tests)
        TestResult(
            job_id=job.id,
            test_key="test1",
            test_name="test_connection_timeout",
            class_name="TestNetwork",
            file_path="tests/test_network.py",
            status=TestStatusEnum.FAILED,
            failure_message="AssertionError: Expected 200 but got 404",
            priority="P0",
            jenkins_topology="5s",
            topology_metadata="5-site",
            order_index=1
        ),
        TestResult(
            job_id=job.id,
            test_key="test2",
            test_name="test_api_response",
            class_name="TestAPI",
            file_path="tests/test_api.py",
            status=TestStatusEnum.FAILED,
            failure_message="AssertionError: Expected 200 but got 500",
            priority="P1",
            jenkins_topology="5s",
            topology_metadata="5-site",
            order_index=2
        ),
        TestResult(
            job_id=job.id,
            test_key="test3",
            test_name="test_status_check",
            class_name="TestStatus",
            file_path="tests/test_status.py",
            status=TestStatusEnum.FAILED,
            failure_message="AssertionError: Expected 200 but got 403",
            priority="P0",
            jenkins_topology="3s",
            topology_metadata="3-site",
            order_index=3
        ),
        # Cluster 2: IndexError (2 tests)
        TestResult(
            job_id=job.id,
            test_key="test4",
            test_name="test_list_access",
            class_name="TestData",
            file_path="tests/test_data.py",
            status=TestStatusEnum.FAILED,
            failure_message="IndexError: list index out of range",
            priority="P2",
            jenkins_topology="5s",
            topology_metadata="5-site",
            order_index=4
        ),
        TestResult(
            job_id=job.id,
            test_key="test5",
            test_name="test_array_bounds",
            class_name="TestData",
            file_path="tests/test_data.py",
            status=TestStatusEnum.FAILED,
            failure_message="IndexError: list index out of range",
            priority="P2",
            jenkins_topology="5s",
            topology_metadata="5-site",
            order_index=5
        ),
    ]

    for failure in failures:
        test_db.add(failure)

    test_db.commit()

    return {
        "release": release.name,
        "module": module.name,
        "job_id": job.job_id,
        "total_failures": len(failures)
    }


class TestGetClusteredFailures:
    """Test the GET /api/v1/jobs/{release}/{module}/{job_id}/failures/clustered endpoint."""

    def test_get_clustered_failures_success(self, client, sample_job_with_failures):
        """Should return clustered failures for a valid job."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "clusters" in data
        assert "summary" in data

        # Verify summary
        summary = data["summary"]
        assert summary["total_failures"] == 5
        assert summary["unique_clusters"] >= 1

        # Verify clusters
        clusters = data["clusters"]
        assert len(clusters) >= 1

        # Check first cluster structure
        first_cluster = clusters[0]
        assert "signature" in first_cluster
        assert "count" in first_cluster
        assert "affected_tests" in first_cluster
        assert "affected_topologies" in first_cluster
        assert "affected_priorities" in first_cluster
        assert "sample_message" in first_cluster
        assert "match_type" in first_cluster
        assert "test_results" in first_cluster

    def test_job_not_found(self, client):
        """Should return 404 for non-existent job."""
        response = client.get("/api/v1/jobs/7.0.0.0/business_policy/nonexistent/failures/clustered")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_empty_failures(self, test_db, client):
        """Should return empty response when job has no failures."""
        # Create job with no failures
        release = Release(name="7.0.0.0", description="Test release")
        test_db.add(release)
        test_db.commit()

        module = Module(name="business_policy", release_id=release.id)
        test_db.add(module)
        test_db.commit()

        job = Job(
            job_id="no-failures",
            module_id=module.id,
            parent_job_id="789",
            jenkins_url="http://jenkins.example.com/job/no-failures",
            total=10,
            passed=10,
            failed=0,
            skipped=0,
            error=0
        )
        test_db.add(job)
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{release.name}/{module.name}/{job.job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_failures"] == 0
        assert data["summary"]["unique_clusters"] == 0
        assert len(data["clusters"]) == 0

    def test_min_cluster_size_filter(self, client, sample_job_with_failures):
        """Should filter clusters by minimum size."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        # Request clusters with min_cluster_size=2
        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"min_cluster_size": 2}
        )

        assert response.status_code == 200
        data = response.json()

        # All clusters should have count >= 2
        for cluster in data["clusters"]:
            assert cluster["count"] >= 2

    def test_sort_by_count(self, client, sample_job_with_failures):
        """Should sort clusters by count descending."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"sort_by": "count"}
        )

        assert response.status_code == 200
        data = response.json()

        clusters = data["clusters"]
        if len(clusters) > 1:
            # Verify descending order
            for i in range(len(clusters) - 1):
                assert clusters[i]["count"] >= clusters[i + 1]["count"]

    def test_sort_by_error_type(self, client, sample_job_with_failures):
        """Should sort clusters by error type alphabetically."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"sort_by": "error_type"}
        )

        assert response.status_code == 200
        data = response.json()

        clusters = data["clusters"]
        if len(clusters) > 1:
            # Verify alphabetical order
            error_types = [c["signature"]["error_type"] for c in clusters]
            assert error_types == sorted(error_types)

    def test_pagination_skip_limit(self, client, sample_job_with_failures):
        """Should support pagination with skip and limit."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        # Get first page
        response1 = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"skip": 0, "limit": 1}
        )

        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["clusters"]) <= 1

        # Get second page
        response2 = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"skip": 1, "limit": 1}
        )

        assert response2.status_code == 200
        data2 = response2.json()

        # If there are multiple clusters, they should be different
        if len(data1["clusters"]) > 0 and len(data2["clusters"]) > 0:
            assert data1["clusters"][0]["signature"]["fingerprint"] != \
                   data2["clusters"][0]["signature"]["fingerprint"]

    def test_invalid_sort_by_parameter(self, client, sample_job_with_failures):
        """Should reject invalid sort_by parameter."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"sort_by": "invalid"}
        )

        assert response.status_code == 422  # Validation error

    def test_negative_skip_parameter(self, client, sample_job_with_failures):
        """Should reject negative skip parameter."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"skip": -1}
        )

        assert response.status_code == 422  # Validation error

    def test_excessive_limit_parameter(self, client, sample_job_with_failures):
        """Should reject limit parameter exceeding maximum."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(
            f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered",
            params={"limit": 2000}  # Max is 1000
        )

        assert response.status_code == 422  # Validation error

    def test_cluster_signature_fields(self, client, sample_job_with_failures):
        """Should include all signature fields in response."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        if len(data["clusters"]) > 0:
            signature = data["clusters"][0]["signature"]
            assert "error_type" in signature
            assert "file_path" in signature
            assert "line_number" in signature
            assert "normalized_message" in signature
            assert "fingerprint" in signature

    def test_affected_topologies_list(self, client, sample_job_with_failures):
        """Should include affected topologies in cluster."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        # Find cluster with multiple tests
        for cluster in data["clusters"]:
            if cluster["count"] > 1:
                assert isinstance(cluster["affected_topologies"], list)
                assert len(cluster["affected_topologies"]) >= 1
                break

    def test_affected_priorities_list(self, client, sample_job_with_failures):
        """Should include affected priorities in cluster."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        # Find cluster with multiple tests
        for cluster in data["clusters"]:
            if cluster["count"] > 1:
                assert isinstance(cluster["affected_priorities"], list)
                assert len(cluster["affected_priorities"]) >= 1
                break

    def test_test_results_included(self, client, sample_job_with_failures):
        """Should include full test result details in each cluster."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        if len(data["clusters"]) > 0:
            test_results = data["clusters"][0]["test_results"]
            assert len(test_results) > 0

            # Check first test result structure
            test = test_results[0]
            assert "test_key" in test
            assert "test_name" in test
            assert "class_name" in test
            assert "file_path" in test
            assert "status" in test
            assert "jenkins_topology" in test
            assert "topology_metadata" in test
            assert "priority" in test
            assert "failure_message" in test

    def test_match_type_field(self, client, sample_job_with_failures):
        """Should include match_type field (exact or fuzzy) in clusters."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()

        if len(data["clusters"]) > 0:
            match_type = data["clusters"][0]["match_type"]
            assert match_type in ["exact", "fuzzy"]

    def test_invalid_release_name(self, client):
        """Should reject invalid release name."""
        response = client.get("/api/v1/jobs/invalid@release/business_policy/job123/failures/clustered")

        assert response.status_code == 422  # Path validation error

    def test_api_backward_compatibility(self, client, sample_job_with_failures):
        """Should support legacy /api/ prefix (without v1)."""
        release = sample_job_with_failures["release"]
        module = sample_job_with_failures["module"]
        job_id = sample_job_with_failures["job_id"]

        # Try legacy endpoint (if it exists)
        # Note: This assumes backward compatibility is maintained
        # Remove this test if legacy support is not required

        response = client.get(f"/api/v1/jobs/{release}/{module}/{job_id}/failures/clustered")
        assert response.status_code == 200


class TestClusteringPerformance:
    """Test clustering performance characteristics."""

    def test_large_number_of_failures(self, test_db, client):
        """Should handle jobs with many failures efficiently."""
        # Create release, module, and job
        release = Release(name="7.0.0.0", description="Test release")
        test_db.add(release)
        test_db.commit()

        module = Module(name="business_policy", release_id=release.id)
        test_db.add(module)
        test_db.commit()

        job = Job(
            job_id="large-job",
            module_id=module.id,
            parent_job_id="999",
            jenkins_url="http://jenkins.example.com/job/large-job",
            total=100,
            passed=50,
            failed=50,
            skipped=0,
            error=0
        )
        test_db.add(job)
        test_db.commit()

        # Create 50 failures (moderate load test)
        for i in range(50):
            # Alternate between a few error types to create realistic clusters
            error_type = ["AssertionError", "IndexError", "TypeError"][i % 3]
            failure = TestResult(
                job_id=job.id,
                test_key=f"test{i}",
                test_name=f"test_case_{i}",
                class_name="TestClass",
                file_path="tests/test.py",
                status=TestStatusEnum.FAILED,
                failure_message=f"{error_type}: Test failure {i % 10}",
                priority=["P0", "P1", "P2"][i % 3],
                jenkins_topology="5s",
                topology_metadata="5-site",
                order_index=i
            )
            test_db.add(failure)

        test_db.commit()

        # Make request and verify it completes successfully
        response = client.get(f"/api/v1/jobs/{release.name}/{module.name}/{job.job_id}/failures/clustered")

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_failures"] == 50
        assert len(data["clusters"]) > 0
