"""
Unit tests for testcase_helpers utility functions.

Tests the extract_module_from_path function which derives module names
from test file paths.
"""
import pytest
from app.utils.testcase_helpers import extract_module_from_path


class TestExtractModuleFromPath:
    """Tests for extract_module_from_path function."""

    def test_extract_business_policy_module(self):
        """Test extracting business_policy module from valid path."""
        path = "data_plane/tests/business_policy/pbnat/test.py"
        assert extract_module_from_path(path) == "business_policy"

    def test_extract_routing_module(self):
        """Test extracting routing module from valid path."""
        path = "data_plane/tests/routing/bgp/test.py"
        assert extract_module_from_path(path) == "routing"

    def test_extract_device_settings_module(self):
        """Test extracting device_settings module from valid path."""
        path = "data_plane/tests/device_settings/dhcp/dhcp_test.py"
        assert extract_module_from_path(path) == "device_settings"

    def test_extract_nvs_module(self):
        """Test extracting nvs module from valid path."""
        path = "data_plane/tests/nvs/direct_ipsec_from_edge/test.py"
        assert extract_module_from_path(path) == "nvs"

    def test_extract_with_deep_nesting(self):
        """Test extraction with deeply nested subdirectories."""
        path = "data_plane/tests/high_availability/active_standby/legacy_ha/test_case.py"
        assert extract_module_from_path(path) == "high_availability"

    def test_invalid_pattern_tests_only(self):
        """Test that paths without data_plane prefix return None."""
        path = "tests/unit/test.py"
        assert extract_module_from_path(path) is None

    def test_invalid_pattern_missing_tests_dir(self):
        """Test that paths missing the tests directory return None."""
        path = "data_plane/business_policy/test.py"
        assert extract_module_from_path(path) is None

    def test_invalid_pattern_too_short(self):
        """Test that paths too short to contain module return None."""
        path = "data_plane/tests"
        assert extract_module_from_path(path) is None

    def test_empty_string(self):
        """Test that empty string returns None."""
        path = ""
        assert extract_module_from_path(path) is None

    def test_none_input(self):
        """Test that None input returns None."""
        path = None
        assert extract_module_from_path(path) is None

    def test_whitespace_only(self):
        """Test that whitespace-only string returns None."""
        path = "   "
        assert extract_module_from_path(path) is None

    def test_wrong_prefix(self):
        """Test that paths with wrong prefix return None."""
        path = "control_plane/tests/routing/test.py"
        assert extract_module_from_path(path) is None

    def test_module_with_underscores(self):
        """Test extracting modules with underscores in name."""
        path = "data_plane/tests/partner_gateway/test.py"
        assert extract_module_from_path(path) == "partner_gateway"

    def test_module_with_numbers(self):
        """Test extracting modules with numbers in name."""
        # This is hypothetical - adjust if actual module names differ
        path = "data_plane/tests/module123/test.py"
        assert extract_module_from_path(path) == "module123"

    def test_windows_style_path(self):
        """Test handling of Windows-style paths (backslashes)."""
        # Should return None since we expect forward slashes
        path = "data_plane\\tests\\routing\\test.py"
        assert extract_module_from_path(path) is None

    def test_relative_path(self):
        """Test that relative paths work correctly."""
        path = "./data_plane/tests/firewall/test.py"
        # Current implementation expects exact "data_plane" at start
        assert extract_module_from_path(path) is None

    def test_absolute_path_unix(self):
        """Test Unix-style absolute path."""
        path = "/home/user/data_plane/tests/vcmp/test.py"
        # Current implementation expects exact "data_plane" at start
        assert extract_module_from_path(path) is None

    def test_trailing_slash(self):
        """Test path with trailing slash."""
        path = "data_plane/tests/qos/"
        # Path split will have empty string at end, should handle gracefully
        assert extract_module_from_path(path) == "qos"

    def test_file_extension_variations(self):
        """Test that file extensions don't affect module extraction."""
        paths = [
            "data_plane/tests/dpi/test.py",
            "data_plane/tests/dpi/test.pyc",
            "data_plane/tests/dpi/test.txt",
            "data_plane/tests/dpi/README.md",
        ]
        for path in paths:
            assert extract_module_from_path(path) == "dpi"

    def test_case_sensitivity(self):
        """Test that module names preserve case."""
        path = "data_plane/tests/MyModule/test.py"
        # Module name should preserve original case
        assert extract_module_from_path(path) == "MyModule"

    def test_special_characters_in_module(self):
        """Test handling of special characters in module name."""
        # Hyphens in module names
        path = "data_plane/tests/my-module/test.py"
        assert extract_module_from_path(path) == "my-module"

    @pytest.mark.parametrize("module_name,expected", [
        ("routing", "routing"),
        ("business_policy", "business_policy"),
        ("device_settings", "device_settings"),
        ("nvs", "nvs"),
        ("firewall", "firewall"),
        ("high_availability", "high_availability"),
        ("partner_gateway", "partner_gateway"),
        ("vcmp", "vcmp"),
        ("vpn", "vpn"),
        ("wan_overlay", "wan_overlay"),
        ("qos", "qos"),
        ("dpi", "dpi"),
        ("ipv6", "ipv6"),
    ])
    def test_all_known_modules(self, module_name, expected):
        """Test extraction for all known module names from cross-contamination report."""
        path = f"data_plane/tests/{module_name}/some/nested/test.py"
        assert extract_module_from_path(path) == expected


class TestEdgeCases:
    """Additional edge case tests for robustness."""

    def test_unicode_characters(self):
        """Test handling of unicode characters in path."""
        path = "data_plane/tests/模块/test.py"
        # Should extract the unicode module name
        assert extract_module_from_path(path) == "模块"

    def test_very_long_module_name(self):
        """Test handling of very long module names."""
        long_name = "a" * 200
        path = f"data_plane/tests/{long_name}/test.py"
        assert extract_module_from_path(path) == long_name

    def test_empty_module_name(self):
        """Test handling of empty module name (double slashes)."""
        path = "data_plane/tests//test.py"
        # Split will create empty strings, parts[2] will be empty
        # Function should handle this gracefully
        result = extract_module_from_path(path)
        # Empty string is falsy, so this might be treated as no module
        assert result == "" or result is None

    def test_only_data_plane(self):
        """Test path with only data_plane."""
        path = "data_plane"
        assert extract_module_from_path(path) is None

    def test_only_data_plane_tests(self):
        """Test path with only data_plane/tests."""
        path = "data_plane/tests"
        assert extract_module_from_path(path) is None

    def test_data_plane_tests_with_slash(self):
        """Test path ending with data_plane/tests/."""
        path = "data_plane/tests/"
        # After split, parts[2] would be empty string
        result = extract_module_from_path(path)
        assert result == "" or result is None
