"""
Log file parser for Regression Tracker.
Handles parsing of .order.txt files and merging main runs with reruns.
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from .models import TestResult, TestStatus
from .junit_parser import parse_junit_directory


# Regex pattern for parsing log lines
# Format: [<setup_ip>] <STATUS> <test_path>::<class_name>::<test_name>
LOG_LINE_PATTERN = re.compile(
    r'\[([^\]]+)\]\s+(PASSED|FAILED|SKIPPED|ERROR)\s+(.+?)::(.+?)::(.+?)\s*$'
)


def parse_log_line(line: str, topology: str) -> Optional[TestResult]:
    """
    Parse a single log line into a TestResult.

    Args:
        line: Raw log line
        topology: Topology name extracted from filename

    Returns:
        TestResult if parsing succeeds, None otherwise
    """
    # Clean the line (remove line numbers if present)
    line = line.strip()
    if not line:
        return None

    # Try to match the pattern
    match = LOG_LINE_PATTERN.search(line)
    if not match:
        return None

    setup_ip, status_str, file_path, class_name, test_name = match.groups()

    return TestResult(
        setup_ip=setup_ip.strip(),
        status=TestStatus.from_string(status_str),
        file_path=file_path.strip(),
        class_name=class_name.strip(),
        test_name=test_name.strip(),
        topology=topology
    )


def extract_topology_from_filename(filename: str) -> str:
    """
    Extract topology name from filename.

    Examples:
        1767888104_bp_5s.order.txt -> 5s
        re_run_bp_others_routing.order.txt -> others_routing
    """
    # Remove .order.txt extension
    base = filename.replace('.order.txt', '')

    # Handle rerun files: re_run_bp_<topology>
    if base.startswith('re_run_'):
        parts = base.split('_', 3)  # ['re', 'run', 'bp', 'topology']
        if len(parts) >= 4:
            return parts[3]
        return 'unknown'

    # Handle main run files: <timestamp>_bp_<topology>
    parts = base.split('_', 2)  # ['timestamp', 'bp', 'topology']
    if len(parts) >= 3:
        return parts[2]

    return 'unknown'


def is_rerun_file(filename: str) -> bool:
    """Check if a file is a rerun file."""
    return filename.startswith('re_run_')


def parse_log_file(file_path: str, start_order_index: int = 0) -> List[TestResult]:
    """
    Parse a single .order.txt file.

    Args:
        file_path: Path to the log file
        start_order_index: Starting order index for tests

    Returns:
        List of TestResult objects
    """
    results = []
    filename = os.path.basename(file_path)
    topology = extract_topology_from_filename(filename)
    order_index = start_order_index

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                result = parse_log_line(line, topology)
                if result:
                    result.order_index = order_index
                    order_index += 1
                    results.append(result)
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")

    return results


def merge_with_rerun(
    main_results: List[TestResult],
    rerun_results: List[TestResult]
) -> List[TestResult]:
    """
    Merge main run results with rerun results.
    Rerun status overwrites main run status for the same test.
    Tracks whether tests were rerun and if they still failed after rerun.

    Args:
        main_results: Results from main test run
        rerun_results: Results from rerun

    Returns:
        Merged list of TestResults with final statuses
    """
    # Create dict keyed by test_key for main results
    merged = {r.test_key: r for r in main_results}

    # Track which tests were rerun
    rerun_keys = set()

    # Overwrite with rerun results and set flags
    for rerun_test in rerun_results:
        key = rerun_test.test_key
        rerun_keys.add(key)

        # Mark as rerun
        rerun_test.was_rerun = True

        # Check if rerun still failed
        if rerun_test.status in (TestStatus.FAILED, TestStatus.ERROR):
            rerun_test.rerun_still_failed = True

        # Preserve original order_index from main run if exists
        if key in merged:
            rerun_test.order_index = merged[key].order_index

        merged[key] = rerun_test

    return list(merged.values())


def group_files_by_topology(
    files: List[str]
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """
    Group files by topology, pairing main runs with reruns.

    Args:
        files: List of file paths

    Returns:
        Dict mapping topology -> (main_file, rerun_file)
    """
    topology_files: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    for file_path in files:
        filename = os.path.basename(file_path)
        topology = extract_topology_from_filename(filename)

        if topology not in topology_files:
            topology_files[topology] = (None, None)

        main_file, rerun_file = topology_files[topology]

        if is_rerun_file(filename):
            topology_files[topology] = (main_file, file_path)
        else:
            topology_files[topology] = (file_path, rerun_file)

    return topology_files


def parse_job_directory(job_path: str) -> List[TestResult]:
    """
    Parse all log files in a job directory.
    Handles merging main runs with reruns per topology.

    Args:
        job_path: Path to the job directory

    Returns:
        List of all TestResults with final statuses
    """
    all_results = []

    # Get all .order.txt files
    files = [
        os.path.join(job_path, f)
        for f in os.listdir(job_path)
        if f.endswith('.order.txt')
    ]

    # Group files by topology
    topology_files = group_files_by_topology(files)

    # Parse and merge each topology
    for topology, (main_file, rerun_file) in topology_files.items():
        main_results = []
        rerun_results = []

        if main_file:
            main_results = parse_log_file(main_file)

        if rerun_file:
            rerun_results = parse_log_file(rerun_file)

        # Merge results (rerun overwrites main)
        if main_results or rerun_results:
            merged = merge_with_rerun(main_results, rerun_results)
            all_results.extend(merged)

    # Parse junit XML files to extract failure messages
    junit_dir = os.path.join(job_path, 'junit')
    if os.path.exists(junit_dir):
        failure_messages = parse_junit_directory(junit_dir)

        # Attach failure messages to test results
        for result in all_results:
            test_key = result.test_key
            if test_key in failure_messages:
                result.failure_message = failure_messages[test_key]

    return all_results


def scan_logs_directory(logs_path: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    Scan the logs directory to discover all releases, modules, and jobs.

    Args:
        logs_path: Path to the logs directory

    Returns:
        Nested dict: {release: {module: {job_id: job_path}}}
    """
    structure: Dict[str, Dict[str, Dict[str, str]]] = {}
    logs_path = Path(logs_path)

    if not logs_path.exists():
        print(f"Logs directory not found: {logs_path}")
        return structure

    # Iterate through releases
    for release_dir in logs_path.iterdir():
        if not release_dir.is_dir() or release_dir.name.startswith('.'):
            continue

        release = release_dir.name
        structure[release] = {}

        # Iterate through modules
        for module_dir in release_dir.iterdir():
            if not module_dir.is_dir() or module_dir.name.startswith('.'):
                continue

            module = module_dir.name
            structure[release][module] = {}

            # Iterate through jobs
            for job_dir in module_dir.iterdir():
                if not job_dir.is_dir() or job_dir.name.startswith('.'):
                    continue

                # Verify it's a valid job directory (numeric name)
                if not job_dir.name.isdigit():
                    continue

                job_id = job_dir.name
                structure[release][module][job_id] = str(job_dir)

    return structure


def get_module_short_name(module: str) -> str:
    """
    Get the short name for a module used in filenames.

    Examples:
        business_policy -> bp
    """
    # Common mappings
    mappings = {
        'business_policy': 'bp',
        'routing': 'rt',
        'firewall': 'fw',
        'vpn': 'vpn',
        'ha': 'ha',
        'qos': 'qos',
    }
    return mappings.get(module, module[:2])
