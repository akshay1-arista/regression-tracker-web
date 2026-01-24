"""
Utility functions for handling test names, including parameterized test normalization.

This module provides functions to normalize test names that include pytest parameters
(e.g., test_foo[param] -> test_foo) to enable proper metadata matching.
"""
import re
from typing import Tuple, Optional


def normalize_test_name(test_name: str) -> str:
    """
    Normalize a test name by removing parameterized test suffixes.

    Pytest parameterized tests include parameters in square brackets:
    - test_create_policy[5-site] -> test_create_policy
    - test_login[user1-password1] -> test_login
    - test_basic -> test_basic (no change)

    Args:
        test_name: Full test name from JUnit XML (may include parameters)

    Returns:
        Base test name without parameters

    Examples:
        >>> normalize_test_name("test_foo[param]")
        'test_foo'
        >>> normalize_test_name("test_bar[5-site]")
        'test_bar'
        >>> normalize_test_name("test_baz")
        'test_baz'
    """
    if not test_name:
        return test_name

    # Strip parameter suffix: anything from '[' to end of string
    # Pattern: match everything up to (but not including) the first '['
    match = re.match(r'^([^\[]+)', test_name)

    if match:
        return match.group(1)

    return test_name


def extract_test_parameter(test_name: str) -> Tuple[str, Optional[str]]:
    """
    Extract the base test name and parameter from a parameterized test name.

    Args:
        test_name: Full test name from JUnit XML

    Returns:
        Tuple of (base_name, parameter or None)

    Examples:
        >>> extract_test_parameter("test_foo[5-site]")
        ('test_foo', '5-site')
        >>> extract_test_parameter("test_bar")
        ('test_bar', None)
    """
    if not test_name:
        return test_name, None

    # Match pattern: base_name[parameter]
    match = re.match(r'^([^\[]+)\[([^\]]+)\]$', test_name)

    if match:
        base_name = match.group(1)
        parameter = match.group(2)
        return base_name, parameter

    # No parameter found
    return test_name, None


def is_parameterized_test(test_name: str) -> bool:
    """
    Check if a test name includes pytest parameters.

    Args:
        test_name: Test name to check

    Returns:
        True if test name includes parameters (contains '[' and ']')

    Examples:
        >>> is_parameterized_test("test_foo[param]")
        True
        >>> is_parameterized_test("test_bar")
        False
    """
    if not test_name:
        return False

    return '[' in test_name and ']' in test_name
