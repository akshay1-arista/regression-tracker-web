"""
JUnit XML Parser for Regression Tracker.
Parses pytest-generated junit XML files to extract failure messages.
"""
import os
import xml.etree.ElementTree as ET
from typing import Dict, Optional
from pathlib import Path


def parse_junit_xml(xml_path: str) -> Dict[str, str]:
    """
    Parse a junit XML file and extract failure/error messages.

    Args:
        xml_path: Path to the junit XML file

    Returns:
        Dict mapping test_key -> failure_message
        Test key format: file_path::class_name::test_name
    """
    failures = {}

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        for testcase in root.findall('testcase'):
            file_path = testcase.get('file', '')
            class_name_full = testcase.get('classname', '')
            test_name = testcase.get('name', '')

            # Extract just the class name (last part after the last dot)
            # e.g., "data_plane.tests.business_policy.app_steering.app_steering_de2e_test.TestAppSteeringDE2E"
            # becomes "TestAppSteeringDE2E"
            class_name = class_name_full.split('.')[-1] if class_name_full else ''

            # Create test key matching the format in parser.py
            # Format: file_path::ClassName::test_name
            test_key = f"{file_path}::{class_name}::{test_name}"

            # Check for failure
            failure = testcase.find('failure')
            if failure is not None:
                message = failure.get('message', '')
                # Also get the failure content if available
                failure_text = failure.text or ''

                # Combine message and text, cleaning up
                full_message = message
                if failure_text.strip():
                    full_message += f"\n\n{failure_text.strip()}"

                failures[test_key] = full_message.strip()
                continue

            # Check for error
            error = testcase.find('error')
            if error is not None:
                message = error.get('message', '')
                error_text = error.text or ''

                full_message = message
                if error_text.strip():
                    full_message += f"\n\n{error_text.strip()}"

                failures[test_key] = full_message.strip()

    except ET.ParseError as e:
        print(f"Warning: Failed to parse junit XML {xml_path}: {e}")
    except Exception as e:
        print(f"Warning: Error reading junit XML {xml_path}: {e}")

    return failures


def parse_junit_directory(junit_dir: str) -> Dict[str, str]:
    """
    Parse all junit XML files in a directory and extract failure messages.

    Args:
        junit_dir: Path to the junit directory

    Returns:
        Dict mapping test_key -> failure_message
    """
    all_failures = {}
    junit_path = Path(junit_dir)

    if not junit_path.exists():
        return all_failures

    # Find all XML files recursively
    for xml_file in junit_path.rglob('*.xml'):
        failures = parse_junit_xml(str(xml_file))
        all_failures.update(failures)

    return all_failures
