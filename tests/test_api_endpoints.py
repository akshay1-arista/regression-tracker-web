"""
Tests for API endpoints.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db_models import TestStatusEnum


@pytest.fixture(scope="module")
def client():
    """Create test client."""
    return TestClient(app)


class TestSystemEndpoints:
    """Tests for system endpoints."""

    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Regression Tracker Web API"
        assert "docs" in data
        assert "health" in data

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "database" in data


class TestDashboardEndpoints:
    """Tests for dashboard API endpoints."""

    def test_get_releases(self, client, sample_release):
        """Test getting all releases."""
        response = client.get("/api/dashboard/releases")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["name"] == "7.0.0.0"

    def test_get_releases_active_only(self, client, sample_release):
        """Test getting active releases only."""
        response = client.get("/api/dashboard/releases?active_only=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned releases should be active
        assert all(r["is_active"] for r in data)

    def test_get_modules(self, client, sample_module):
        """Test getting modules for a release."""
        response = client.get("/api/dashboard/modules/7.0.0.0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["name"] == "business_policy"

    def test_get_modules_not_found(self, client):
        """Test getting modules for non-existent release."""
        response = client.get("/api/dashboard/modules/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_summary(self, client, sample_job, sample_test_results):
        """Test getting dashboard summary."""
        response = client.get("/api/dashboard/summary/7.0.0.0/business_policy")
        assert response.status_code == 200
        data = response.json()
        assert data["release"] == "7.0.0.0"
        assert data["module"] == "business_policy"
        assert "summary" in data
        assert "recent_jobs" in data
        assert "pass_rate_history" in data

    def test_get_summary_not_found(self, client):
        """Test getting summary for non-existent module."""
        response = client.get("/api/dashboard/summary/7.0.0.0/nonexistent")
        assert response.status_code == 404


class TestTrendsEndpoints:
    """Tests for trends API endpoints."""

    def test_get_trends(self, client, sample_job, sample_test_results):
        """Test getting test trends."""
        response = client.get("/api/trends/7.0.0.0/business_policy")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have trends for unique tests
        assert len(data) >= 1

    def test_get_trends_with_filters(self, client, sample_job, sample_test_results):
        """Test getting trends with filters."""
        # Test flaky_only filter
        response = client.get("/api/trends/7.0.0.0/business_policy?flaky_only=true")
        assert response.status_code == 200

        # Test always_failing_only filter
        response = client.get("/api/trends/7.0.0.0/business_policy?always_failing_only=true")
        assert response.status_code == 200

        # Test new_failures_only filter
        response = client.get("/api/trends/7.0.0.0/business_policy?new_failures_only=true")
        assert response.status_code == 200

    def test_get_trends_not_found(self, client):
        """Test getting trends for non-existent module."""
        response = client.get("/api/trends/7.0.0.0/nonexistent")
        assert response.status_code == 404

    def test_get_trends_by_class(self, client, sample_job, sample_test_results):
        """Test getting trends grouped by class."""
        response = client.get("/api/trends/7.0.0.0/business_policy/classes")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have TestBusinessPolicy class
        if "TestBusinessPolicy" in data:
            assert isinstance(data["TestBusinessPolicy"], list)


class TestJobsEndpoints:
    """Tests for jobs API endpoints."""

    def test_get_jobs(self, client, sample_job):
        """Test getting all jobs for a module."""
        response = client.get("/api/jobs/7.0.0.0/business_policy")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["job_id"] == "8"

    def test_get_jobs_with_limit(self, client, sample_job):
        """Test getting jobs with limit."""
        response = client.get("/api/jobs/7.0.0.0/business_policy?limit=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 1

    def test_get_jobs_not_found(self, client):
        """Test getting jobs for non-existent module."""
        response = client.get("/api/jobs/7.0.0.0/nonexistent")
        assert response.status_code == 404

    def test_get_job(self, client, sample_job):
        """Test getting a specific job."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/8")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "8"
        assert "total" in data
        assert "pass_rate" in data

    def test_get_job_not_found(self, client, sample_job):
        """Test getting non-existent job."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/999")
        assert response.status_code == 404

    def test_get_test_results(self, client, sample_job, sample_test_results):
        """Test getting test results for a job."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/8/tests")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3  # Sample data has 3 tests

    def test_get_test_results_with_status_filter(self, client, sample_job, sample_test_results):
        """Test getting test results filtered by status."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/8/tests?status=PASSED")
        assert response.status_code == 200
        data = response.json()
        assert all(test["status"] == "PASSED" for test in data)

    def test_get_test_results_with_search(self, client, sample_job, sample_test_results):
        """Test getting test results with search."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/8/tests?search=create")
        assert response.status_code == 200
        data = response.json()
        # Should find test_create_policy
        assert any("create" in test["test_name"].lower() for test in data)

    def test_get_test_results_grouped(self, client, sample_job, sample_test_results):
        """Test getting test results grouped by topology."""
        response = client.get("/api/jobs/7.0.0.0/business_policy/8/grouped")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have topology groups
        assert len(data) >= 1


class TestAPIDocumentation:
    """Tests for API documentation."""

    def test_openapi_schema(self, client):
        """Test that OpenAPI schema is available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert "components" in schema

    def test_docs_page(self, client):
        """Test that Swagger UI docs are available."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert b"swagger" in response.content.lower()
