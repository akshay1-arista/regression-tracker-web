"""
Utility functions for test case processing.

This module provides helper functions for extracting metadata from test cases,
such as deriving module names from file paths.
"""
from typing import Optional


def extract_module_from_path(file_path: str) -> Optional[str]:
    """
    Extract module name from test file path.

    Extracts the module name from test file paths following the pattern:
    data_plane/tests/{module_name}/...

    This is used to correctly categorize test cases by their actual module
    (based on file location) rather than which Jenkins job executed them.

    Examples:
        >>> extract_module_from_path("data_plane/tests/business_policy/pbnat/test.py")
        'business_policy'

        >>> extract_module_from_path("data_plane/tests/routing/bgp/test.py")
        'routing'

        >>> extract_module_from_path("tests/unit/test.py")
        None

        >>> extract_module_from_path(None)
        None

        >>> extract_module_from_path("")
        None

    Args:
        file_path: The test file path string

    Returns:
        Module name extracted from path, or None if pattern doesn't match
    """
    if not file_path:
        return None

    parts = file_path.split('/')
    if len(parts) >= 3 and parts[0] == 'data_plane' and parts[1] == 'tests':
        return parts[2]

    return None
