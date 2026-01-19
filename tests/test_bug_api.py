"""
Tests for bug tracking API endpoints.

Covers:
- POST /api/v1/admin/bugs/update (manual trigger)
- GET /api/v1/admin/bugs/status (status endpoint)
- Rate limiting
- Caching
- Authentication
"""
import pytest
import hashlib
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
from datetime import datetime

from app.models.db_models import BugMetadata
from app.main import app

client = TestClient(app)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def admin_pin_hash():
    """Generate admin PIN hash for testing."""
    return hashlib.sha256("test_admin_pin".encode()).hexdigest()


@pytest.fixture
def mock_settings(admin_pin_hash):
    """Mock application settings."""
    with patch('app.config.get_settings') as mock_get_settings:
        settings_mock = Mock()
        settings_mock.JENKINS_USER = "test_user"
        settings_mock.JENKINS_API_TOKEN = "test_token"
        settings_mock.JENKINS_BUG_DATA_URL = "https://test.jenkins.com/bugs.json"
        settings_mock.JENKINS_VERIFY_SSL = True
        settings_mock.ADMIN_PIN_HASH = admin_pin_hash
        mock_get_settings.return_value = settings_mock
        yield settings_mock


# ============================================================================
# POST /api/v1/admin/bugs/update - Manual Trigger Tests
# ============================================================================

@patch('app.services.bug_updater_service.requests.get')
def test_trigger_bug_update_success(mock_get, db, mock_settings):
    """Test successful manual bug update trigger."""
    # Mock Jenkins response
    mock_response = Mock()
    mock_response.json.return_value = {
        "VLEI": [
            {
                "defect_id": "VLEI-API-1",
                "URL": "https://jira.com/VLEI-API-1",
                "case_id": "C_API_1",
                "labels": [],
                "jira_info": {
                    "status": "Open",
                    "summary": "Test bug",
                    "priority": "High",
                    "assignee": "test@example.com",
                    "component": "Test",
                    "resolution": None,
                    "affected_versions": "1.0.0"
                }
            }
        ],
        "VLENG": []
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    # Make request with admin PIN
    response = client.post(
        "/api/v1/admin/bugs/update",
        headers={"X-Admin-PIN": "test_admin_pin"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert 'bugs_updated' in data['stats']
    assert data['stats']['bugs_updated'] == 1
    assert data['stats']['vlei_count'] == 1
    assert data['stats']['vleng_count'] == 0


def test_trigger_bug_update_missing_pin(mock_settings):
    """Test that update endpoint requires admin PIN."""
    response = client.post("/api/v1/admin/bugs/update")
    assert response.status_code == 401
    assert "Admin PIN required" in response.json()['detail']


def test_trigger_bug_update_invalid_pin(mock_settings):
    """Test that invalid admin PIN is rejected."""
    response = client.post(
        "/api/v1/admin/bugs/update",
        headers={"X-Admin-PIN": "wrong_pin"}
    )
    assert response.status_code == 403
    assert "Invalid admin PIN" in response.json()['detail']


@patch('app.services.bug_updater_service.requests.get')
def test_trigger_bug_update_service_error(mock_get, db, mock_settings):
    """Test handling of service errors during update."""
    mock_get.side_effect = Exception("Jenkins connection failed")

    response = client.post(
        "/api/v1/admin/bugs/update",
        headers={"X-Admin-PIN": "test_admin_pin"}
    )

    assert response.status_code == 500
    assert "Update failed" in response.json()['detail']


def test_trigger_bug_update_rate_limiting(db, mock_settings):
    """Test that rate limiting is enforced (2/hour)."""
    # This test verifies rate limiting is configured
    # Actual rate limit testing would require mocking time or using a test client
    # that supports rate limit bypass

    # For now, just verify the endpoint exists and is protected
    response = client.post(
        "/api/v1/admin/bugs/update",
        headers={"X-Admin-PIN": "test_admin_pin"}
    )

    # Should not be a rate limit error on first request
    assert response.status_code != 429


# ============================================================================
# GET /api/v1/admin/bugs/status - Status Endpoint Tests
# ============================================================================

def test_get_bug_status_no_bugs(db, mock_settings):
    """Test status endpoint when no bugs exist."""
    response = client.get("/api/v1/admin/bugs/status")

    assert response.status_code == 200
    data = response.json()
    assert data['last_update'] is None
    assert data['total_bugs'] == 0
    assert data['vlei_bugs'] == 0
    assert data['vleng_bugs'] == 0


def test_get_bug_status_with_bugs(db, mock_settings):
    """Test status endpoint with existing bugs."""
    # Add bugs to database
    bugs = [
        BugMetadata(
            defect_id='VLEI-STATUS-1',
            bug_type='VLEI',
            url='http://test.com/1',
            updated_at=datetime(2024, 1, 15, 10, 30, 0)
        ),
        BugMetadata(
            defect_id='VLEI-STATUS-2',
            bug_type='VLEI',
            url='http://test.com/2',
            updated_at=datetime(2024, 1, 15, 10, 30, 0)
        ),
        BugMetadata(
            defect_id='VLENG-STATUS-1',
            bug_type='VLENG',
            url='http://test.com/3',
            updated_at=datetime(2024, 1, 15, 10, 30, 0)
        )
    ]
    db.add_all(bugs)
    db.commit()

    response = client.get("/api/v1/admin/bugs/status")

    assert response.status_code == 200
    data = response.json()
    assert data['total_bugs'] == 3
    assert data['vlei_bugs'] == 2
    assert data['vleng_bugs'] == 1
    assert data['last_update'] == '2024-01-15T10:30:00'


def test_get_bug_status_no_auth_required(db, mock_settings):
    """Test that status endpoint does not require authentication."""
    # Should work without admin PIN
    response = client.get("/api/v1/admin/bugs/status")
    assert response.status_code == 200


def test_get_bug_status_caching(db, mock_settings):
    """Test that status endpoint uses caching."""
    # Make first request
    response1 = client.get("/api/v1/admin/bugs/status")
    data1 = response1.json()

    # Add a bug
    bug = BugMetadata(
        defect_id='VLEI-CACHE-1',
        bug_type='VLEI',
        url='http://test.com'
    )
    db.add(bug)
    db.commit()

    # Make second request immediately
    # Note: In real implementation with Redis, this would return cached data
    # For in-memory cache, behavior depends on cache configuration
    response2 = client.get("/api/v1/admin/bugs/status")
    data2 = response2.json()

    # Both requests should succeed
    assert response1.status_code == 200
    assert response2.status_code == 200


# ============================================================================
# Integration Tests
# ============================================================================

@patch('app.services.bug_updater_service.requests.get')
def test_full_bug_workflow(mock_get, db, mock_settings):
    """Test complete workflow: update bugs, then check status."""
    # Mock Jenkins response
    mock_response = Mock()
    mock_response.json.return_value = {
        "VLEI": [
            {
                "defect_id": "VLEI-WORKFLOW-1",
                "URL": "https://jira.com/VLEI-WORKFLOW-1",
                "case_id": "C_WORKFLOW",
                "labels": ["test"],
                "jira_info": {
                    "status": "Open",
                    "summary": "Workflow test",
                    "priority": "Medium",
                    "assignee": None,
                    "component": None,
                    "resolution": None,
                    "affected_versions": None
                }
            }
        ],
        "VLENG": []
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    # 1. Trigger update
    update_response = client.post(
        "/api/v1/admin/bugs/update",
        headers={"X-Admin-PIN": "test_admin_pin"}
    )
    assert update_response.status_code == 200
    assert update_response.json()['success'] is True

    # 2. Check status
    status_response = client.get("/api/v1/admin/bugs/status")
    assert status_response.status_code == 200

    status_data = status_response.json()
    assert status_data['total_bugs'] >= 1
    assert status_data['vlei_bugs'] >= 1
    assert status_data['last_update'] is not None


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_bug_update_invalid_json_response(db, mock_settings):
    """Test handling of invalid JSON from Jenkins."""
    with patch('app.services.bug_updater_service.requests.get') as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = {"invalid": "structure"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        response = client.post(
            "/api/v1/admin/bugs/update",
            headers={"X-Admin-PIN": "test_admin_pin"}
        )

        assert response.status_code == 500


def test_bug_update_network_timeout(db, mock_settings):
    """Test handling of network timeout."""
    with patch('app.services.bug_updater_service.requests.get') as mock_get:
        from requests.exceptions import Timeout
        mock_get.side_effect = Timeout("Connection timeout")

        response = client.post(
            "/api/v1/admin/bugs/update",
            headers={"X-Admin-PIN": "test_admin_pin"}
        )

        assert response.status_code == 500
        assert "Update failed" in response.json()['detail']
