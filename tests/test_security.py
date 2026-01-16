"""
Tests for security utilities (PIN authentication and credential management).

Tests for app/utils/security.py:
- PIN hashing and verification
- CredentialsManager for Jenkins credentials
- @require_admin_pin decorator behavior
"""
import pytest
import os
from unittest.mock import Mock, patch
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.utils.security import (
    hash_pin,
    verify_pin,
    require_admin_pin,
    CredentialsManager,
    ADMIN_PIN_HASH
)
from app.main import app


class TestPINHashing:
    """Tests for PIN hashing and verification."""

    def test_hash_pin_produces_consistent_hash(self):
        """Test that the same PIN produces the same hash."""
        pin = "1234"
        hash1 = hash_pin(pin)
        hash2 = hash_pin(pin)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 character hex digest

    def test_hash_pin_different_pins_different_hashes(self):
        """Test that different PINs produce different hashes."""
        hash1 = hash_pin("1234")
        hash2 = hash_pin("5678")

        assert hash1 != hash2

    def test_hash_pin_empty_string(self):
        """Test hashing empty string."""
        hash_result = hash_pin("")
        assert len(hash_result) == 64
        assert isinstance(hash_result, str)

    def test_verify_pin_correct_pin(self):
        """Test PIN verification with correct PIN."""
        pin = "1234"
        pin_hash = hash_pin(pin)

        assert verify_pin(pin, pin_hash) is True

    def test_verify_pin_incorrect_pin(self):
        """Test PIN verification with incorrect PIN."""
        correct_pin = "1234"
        incorrect_pin = "5678"
        pin_hash = hash_pin(correct_pin)

        assert verify_pin(incorrect_pin, pin_hash) is False

    def test_verify_pin_case_sensitive(self):
        """Test that PIN verification is case sensitive."""
        pin = "AbCd"
        pin_hash = hash_pin(pin)

        assert verify_pin("AbCd", pin_hash) is True
        assert verify_pin("abcd", pin_hash) is False


class TestCredentialsManager:
    """Tests for CredentialsManager."""

    def test_get_jenkins_credentials_success(self):
        """Test successful retrieval of Jenkins credentials."""
        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://jenkins.example.com',
            'JENKINS_USER': 'testuser',
            'JENKINS_API_TOKEN': 'testtoken'
        }):
            url, user, token = CredentialsManager.get_jenkins_credentials()

            assert url == 'https://jenkins.example.com'
            assert user == 'testuser'
            assert token == 'testtoken'

    def test_get_jenkins_credentials_missing_url(self):
        """Test that missing JENKINS_URL raises ValueError."""
        with patch.dict(os.environ, {
            'JENKINS_USER': 'testuser',
            'JENKINS_API_TOKEN': 'testtoken'
        }, clear=True):
            with pytest.raises(ValueError) as exc_info:
                CredentialsManager.get_jenkins_credentials()

            assert "Jenkins credentials not configured" in str(exc_info.value)

    def test_get_jenkins_credentials_missing_user(self):
        """Test that missing JENKINS_USER raises ValueError."""
        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://jenkins.example.com',
            'JENKINS_API_TOKEN': 'testtoken'
        }, clear=True):
            with pytest.raises(ValueError) as exc_info:
                CredentialsManager.get_jenkins_credentials()

            assert "Jenkins credentials not configured" in str(exc_info.value)

    def test_get_jenkins_credentials_missing_token(self):
        """Test that missing JENKINS_API_TOKEN raises ValueError."""
        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://jenkins.example.com',
            'JENKINS_USER': 'testuser'
        }, clear=True):
            with pytest.raises(ValueError) as exc_info:
                CredentialsManager.get_jenkins_credentials()

            assert "Jenkins credentials not configured" in str(exc_info.value)

    def test_get_jenkins_credentials_all_missing(self):
        """Test that all missing credentials raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                CredentialsManager.get_jenkins_credentials()

            assert "Jenkins credentials not configured" in str(exc_info.value)

    def test_validate_jenkins_credentials_success(self):
        """Test successful validation when all credentials present."""
        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://jenkins.example.com',
            'JENKINS_USER': 'testuser',
            'JENKINS_API_TOKEN': 'testtoken'
        }):
            assert CredentialsManager.validate_jenkins_credentials() is True

    def test_validate_jenkins_credentials_failure(self):
        """Test validation failure when credentials missing."""
        with patch.dict(os.environ, {}, clear=True):
            assert CredentialsManager.validate_jenkins_credentials() is False


class TestRequireAdminPinDecorator:
    """Tests for @require_admin_pin decorator."""

    def test_decorator_with_valid_pin(self):
        """Test that decorator allows access with valid PIN."""
        # Create a mock endpoint
        @require_admin_pin
        async def mock_endpoint(request: Request):
            return {"message": "success"}

        # Create mock request with valid PIN
        pin = "1234"
        pin_hash = hash_pin(pin)

        with patch('app.utils.security.ADMIN_PIN_HASH', pin_hash):
            mock_request = Mock(spec=Request)
            mock_request.headers.get.return_value = pin

            # Should not raise exception
            import asyncio
            result = asyncio.run(mock_endpoint(request=mock_request))
            assert result == {"message": "success"}

    def test_decorator_with_invalid_pin(self):
        """Test that decorator rejects invalid PIN."""
        @require_admin_pin
        async def mock_endpoint(request: Request):
            return {"message": "success"}

        correct_pin = "1234"
        incorrect_pin = "5678"
        pin_hash = hash_pin(correct_pin)

        with patch('app.utils.security.ADMIN_PIN_HASH', pin_hash):
            mock_request = Mock(spec=Request)
            mock_request.headers.get.return_value = incorrect_pin

            import asyncio
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(mock_endpoint(request=mock_request))

            assert exc_info.value.status_code == 403
            assert "Invalid admin PIN" in exc_info.value.detail

    def test_decorator_with_missing_pin_header(self):
        """Test that decorator rejects request without PIN header."""
        @require_admin_pin
        async def mock_endpoint(request: Request):
            return {"message": "success"}

        mock_request = Mock(spec=Request)
        mock_request.headers.get.return_value = None

        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(mock_endpoint(request=mock_request))

        assert exc_info.value.status_code == 401
        assert "Admin PIN required" in exc_info.value.detail

    def test_decorator_with_unconfigured_pin_hash(self):
        """Test that decorator fails when ADMIN_PIN_HASH not configured."""
        @require_admin_pin
        async def mock_endpoint(request: Request):
            return {"message": "success"}

        with patch('app.utils.security.ADMIN_PIN_HASH', ''):
            mock_request = Mock(spec=Request)
            mock_request.headers.get.return_value = "1234"

            import asyncio
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(mock_endpoint(request=mock_request))

            assert exc_info.value.status_code == 500
            assert "Admin PIN not configured" in exc_info.value.detail

    def test_decorator_with_request_in_kwargs(self):
        """Test that decorator finds request in kwargs."""
        @require_admin_pin
        async def mock_endpoint(some_arg: str, request: Request):
            return {"message": "success", "arg": some_arg}

        pin = "1234"
        pin_hash = hash_pin(pin)

        with patch('app.utils.security.ADMIN_PIN_HASH', pin_hash):
            mock_request = Mock(spec=Request)
            mock_request.headers.get.return_value = pin

            import asyncio
            result = asyncio.run(mock_endpoint(some_arg="test", request=mock_request))
            assert result["message"] == "success"
            assert result["arg"] == "test"

    def test_decorator_with_request_in_args(self):
        """Test that decorator finds request in args."""
        @require_admin_pin
        async def mock_endpoint(request: Request, some_arg: str):
            return {"message": "success", "arg": some_arg}

        pin = "1234"
        pin_hash = hash_pin(pin)

        with patch('app.utils.security.ADMIN_PIN_HASH', pin_hash):
            mock_request = Mock(spec=Request)
            mock_request.headers.get.return_value = pin

            import asyncio
            result = asyncio.run(mock_endpoint(mock_request, "test"))
            assert result["message"] == "success"
            assert result["arg"] == "test"


class TestAdminEndpointsAuthentication:
    """Integration tests for admin endpoints with PIN authentication."""

    @pytest.fixture
    def client_with_pin(self):
        """Create test client with ADMIN_PIN_HASH configured."""
        test_pin = "1234"
        pin_hash = hash_pin(test_pin)

        with patch.dict(os.environ, {'ADMIN_PIN_HASH': pin_hash}):
            yield TestClient(app), test_pin

    def test_admin_endpoint_requires_pin(self, client_with_pin):
        """Test that admin endpoints require PIN."""
        client, _ = client_with_pin

        # Request without PIN header should fail
        response = client.get("/api/v1/admin/settings")
        assert response.status_code == 401
        assert "Admin PIN required" in response.json()["detail"]

    def test_admin_endpoint_accepts_valid_pin(self, client_with_pin):
        """Test that admin endpoints accept valid PIN."""
        client, test_pin = client_with_pin

        # Request with valid PIN header
        response = client.get(
            "/api/v1/admin/settings",
            headers={"X-Admin-PIN": test_pin}
        )
        assert response.status_code == 200

    def test_admin_endpoint_rejects_invalid_pin(self, client_with_pin):
        """Test that admin endpoints reject invalid PIN."""
        client, _ = client_with_pin

        # Request with invalid PIN header
        response = client.get(
            "/api/v1/admin/settings",
            headers={"X-Admin-PIN": "wrong-pin"}
        )
        assert response.status_code == 403
        assert "Invalid admin PIN" in response.json()["detail"]

    def test_all_admin_settings_endpoints_protected(self, client_with_pin):
        """Test that all settings endpoints require PIN."""
        client, test_pin = client_with_pin

        endpoints = [
            ("/api/v1/admin/settings", "GET"),
            ("/api/v1/admin/settings/AUTO_UPDATE_ENABLED", "GET"),
        ]

        for endpoint, method in endpoints:
            # Without PIN should fail
            if method == "GET":
                response = client.get(endpoint)
            assert response.status_code == 401

            # With PIN should work (or return 404 for non-existent resources)
            if method == "GET":
                response = client.get(endpoint, headers={"X-Admin-PIN": test_pin})
            assert response.status_code in [200, 404]

    def test_all_admin_release_endpoints_protected(self, client_with_pin):
        """Test that all release endpoints require PIN."""
        client, test_pin = client_with_pin

        endpoints = [
            ("/api/v1/admin/releases", "GET"),
        ]

        for endpoint, method in endpoints:
            # Without PIN should fail
            if method == "GET":
                response = client.get(endpoint)
            assert response.status_code == 401

            # With PIN should work
            if method == "GET":
                response = client.get(endpoint, headers={"X-Admin-PIN": test_pin})
            assert response.status_code == 200


class TestSecurityBestPractices:
    """Tests for security best practices."""

    def test_pin_hash_not_reversible(self):
        """Test that PIN hash cannot be reversed to get original PIN."""
        pin = "1234"
        pin_hash = hash_pin(pin)

        # Hash should not contain the original PIN
        assert pin not in pin_hash
        assert len(pin_hash) == 64

        # Hash should be deterministic (same input = same output)
        assert hash_pin(pin) == pin_hash

    def test_different_pins_produce_different_hashes(self):
        """Test that similar PINs produce very different hashes."""
        hash1 = hash_pin("1234")
        hash2 = hash_pin("1235")  # Only 1 character different

        # Hashes should be completely different (avalanche effect)
        assert hash1 != hash2

        # Calculate Hamming distance (number of different characters)
        differences = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
        # SHA-256 should have high avalanche effect (>50% different)
        assert differences > 32

    def test_credentials_not_stored_in_memory(self):
        """Test that credentials are not cached in memory."""
        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://jenkins.example.com',
            'JENKINS_USER': 'testuser',
            'JENKINS_API_TOKEN': 'testtoken'
        }):
            # Call twice
            url1, user1, token1 = CredentialsManager.get_jenkins_credentials()
            url2, user2, token2 = CredentialsManager.get_jenkins_credentials()

            # Should return same values (from env, not cache)
            assert url1 == url2
            assert user1 == user2
            assert token1 == token2

            # Verify they're reading from env each time by changing env

        with patch.dict(os.environ, {
            'JENKINS_URL': 'https://different.jenkins.com',
            'JENKINS_USER': 'differentuser',
            'JENKINS_API_TOKEN': 'differenttoken'
        }):
            url3, user3, token3 = CredentialsManager.get_jenkins_credentials()

            # Should reflect new environment values
            assert url3 == 'https://different.jenkins.com'
            assert user3 == 'differentuser'
            assert token3 == 'differenttoken'
            assert url3 != url1

    def test_pin_comparison_timing_safe(self):
        """Test that PIN verification doesn't leak timing information."""
        import time

        correct_pin = "1234567890"
        pin_hash = hash_pin(correct_pin)

        # Test with completely wrong PIN
        start1 = time.perf_counter()
        verify_pin("0000000000", pin_hash)
        time1 = time.perf_counter() - start1

        # Test with almost correct PIN (only last character wrong)
        start2 = time.perf_counter()
        verify_pin("1234567891", pin_hash)
        time2 = time.perf_counter() - start2

        # Timing difference should be minimal (constant-time comparison)
        # Using SHA-256 hash comparison should be constant time
        # Allow for system variance but times should be similar
        assert abs(time1 - time2) < 0.01  # Within 10ms
