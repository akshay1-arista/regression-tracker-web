"""
Bundled parser module for regression test log parsing.

This module is bundled from the regression_tracker CLI tool to eliminate
external dependencies during deployment.
"""
from app.parser.parser import parse_job_directory, scan_logs_directory
from app.parser.models import TestResult, TestStatus

__all__ = [
    'parse_job_directory',
    'scan_logs_directory',
    'TestResult',
    'TestStatus',
]
