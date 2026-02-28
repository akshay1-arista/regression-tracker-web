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
        # Use iterparse for memory-efficient parsing of large XML files
        context = ET.iterparse(xml_path, events=('end',))
        
        for event, elem in context:
            if elem.tag == 'testcase':
                file_path = elem.get('file', '')
                class_name_full = elem.get('classname', '')
                test_name = elem.get('name', '')

                # Extract just the class name (last part after the last dot)
                class_name = class_name_full.split('.')[-1] if class_name_full else ''

                # Create test key matching the format in parser.py
                test_key = f"{file_path}::{class_name}::{test_name}"

                # Check for failure
                failure = elem.find('failure')
                if failure is not None:
                    message = failure.get('message', '')
                    failure_text = failure.text or ''

                    full_message = message
                    if failure_text.strip():
                        full_message += f"\n\n{failure_text.strip()}"

                    failures[test_key] = full_message.strip()
                else:
                    # Check for error
                    error = elem.find('error')
                    if error is not None:
                        message = error.get('message', '')
                        error_text = error.text or ''

                        full_message = message
                        if error_text.strip():
                            full_message += f"\n\n{error_text.strip()}"

                        failures[test_key] = full_message.strip()
                
                # Clear the element from memory to prevent OOM on large files
                elem.clear()

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
