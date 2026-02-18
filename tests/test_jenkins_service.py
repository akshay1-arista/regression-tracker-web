"""
Unit tests for Jenkins service functions.

Tests the version-to-release mapping logic used in unified parent job architecture.
"""
import pytest
from app.services.jenkins_service import map_version_to_release


class TestMapVersionToRelease:
    """Test suite for map_version_to_release() function."""

    def test_standard_version_mapping(self):
        """Test standard semantic version mapping (X.X.X.X -> X.X)."""
        assert map_version_to_release("7.0.0.0") == "7.0"
        assert map_version_to_release("6.4.0.0") == "6.4"
        assert map_version_to_release("6.1.4.0") == "6.1"
        assert map_version_to_release("10.2.3.4") == "10.2"

    def test_already_shortened_version(self):
        """Test version already in major.minor format."""
        assert map_version_to_release("7.0") == "7.0"
        assert map_version_to_release("6.4") == "6.4"
        assert map_version_to_release("10.2") == "10.2"

    def test_single_component_version(self):
        """Test version with single component."""
        assert map_version_to_release("7") == "7"
        assert map_version_to_release("10") == "10"

    def test_none_input(self):
        """Test None input returns None."""
        assert map_version_to_release(None) is None

    def test_empty_string(self):
        """Test empty string returns None."""
        assert map_version_to_release("") is None

    def test_whitespace_string(self):
        """Test whitespace-only string returns None."""
        assert map_version_to_release("   ") is None

    def test_three_component_version(self):
        """Test three-component version (X.X.X -> X.X)."""
        assert map_version_to_release("7.0.1") == "7.0"
        assert map_version_to_release("6.4.2") == "6.4"

    def test_five_component_version(self):
        """Test five-component version (takes first two)."""
        assert map_version_to_release("7.0.0.0.1") == "7.0"
        assert map_version_to_release("6.4.1.2.3") == "6.4"

    def test_version_with_leading_zeros(self):
        """Test version with leading zeros."""
        assert map_version_to_release("07.04.00.00") == "07.04"

    def test_version_with_text(self):
        """Test version with non-numeric text (should still work)."""
        # The function splits by '.' and takes first two parts
        assert map_version_to_release("7.0.alpha.beta") == "7.0"
