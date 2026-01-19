"""
Integration tests for All Modules aggregation API endpoints.

Note: These tests verify the API contract and response structure.
Unit tests in test_services.py provide comprehensive coverage of the
aggregation functions themselves.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.constants import ALL_MODULES_IDENTIFIER


@pytest.fixture(scope="module")
def client():
    """Create test client."""
    return TestClient(app)


class TestAllModulesEndpoints:
    """Integration tests for All Modules API endpoints."""

    def test_all_modules_identifier_constant(self):
        """Test that ALL_MODULES_IDENTIFIER constant is defined correctly."""
        assert ALL_MODULES_IDENTIFIER == "__all__"
        assert isinstance(ALL_MODULES_IDENTIFIER, str)
        assert len(ALL_MODULES_IDENTIFIER) > 0

    def test_get_modules_includes_all_modules_option(
        self, client, sample_module
    ):
        """Test that /modules endpoint includes ALL_MODULES_IDENTIFIER."""
        response = client.get("/api/v1/dashboard/modules/7.0.0.0")
        assert response.status_code == 200

        modules = response.json()
        assert len(modules) >= 1  # At least the sample module

        # First option should be All Modules
        assert modules[0]['name'] == ALL_MODULES_IDENTIFIER

    def test_get_summary_response_structure(
        self, client, sample_job
    ):
        """Test /summary endpoint response structure."""
        response = client.get("/api/v1/dashboard/summary/7.0.0.0/business_policy")
        assert response.status_code == 200

        data = response.json()

        # Verify response structure
        assert 'release' in data
        assert 'module' in data
        assert 'summary' in data
        assert 'recent_jobs' in data
        assert 'pass_rate_history' in data
        assert 'module_breakdown' in data  # Should be None or empty for single module

    def test_constants_imported_correctly(self):
        """Test that constants module is properly structured."""
        from app.constants import PRIORITY_ORDER, ALL_MODULES_IDENTIFIER

        assert isinstance(PRIORITY_ORDER, dict)
        assert 'P0' in PRIORITY_ORDER
        assert 'P1' in PRIORITY_ORDER
        assert 'UNKNOWN' in PRIORITY_ORDER

        assert isinstance(ALL_MODULES_IDENTIFIER, str)
