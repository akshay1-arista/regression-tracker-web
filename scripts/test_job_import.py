#!/usr/bin/env python3
"""
Test script to diagnose job import issues with detailed logging and memory tracking.
Usage: python scripts/test_job_import.py <release> <module> <build_number>
Example: python scripts/test_job_import.py 7.0 vpn 14
"""

import sys
import os
import time
import tracemalloc
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.parser.junit_parser import parse_junit_xml
from app.services.import_service import import_jenkins_job

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_import_debug.log')
    ]
)
logger = logging.getLogger(__name__)


def format_bytes(bytes_val):
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"


def test_artifact_parsing(artifact_path):
    """Test parsing XML artifact with memory tracking."""
    logger.info(f"Testing XML parsing: {artifact_path}")

    if not os.path.exists(artifact_path):
        logger.error(f"Artifact not found: {artifact_path}")
        return None

    # Get file stats
    file_size = os.path.getsize(artifact_path)
    logger.info(f"File size: {format_bytes(file_size)}")

    with open(artifact_path, 'r') as f:
        line_count = sum(1 for _ in f)
    logger.info(f"File lines: {line_count:,}")

    # Start memory tracking
    tracemalloc.start()
    start_time = time.time()

    try:
        logger.info("Starting XML parse...")
        results = parse_junit_xml(artifact_path)
        parse_time = time.time() - start_time

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        logger.info(f"✓ Parse successful!")
        logger.info(f"  Duration: {parse_time:.2f}s")
        logger.info(f"  Test results: {len(results):,}")
        logger.info(f"  Memory (current): {format_bytes(current)}")
        logger.info(f"  Memory (peak): {format_bytes(peak)}")
        logger.info(f"  Parse rate: {len(results) / parse_time:.0f} tests/sec")

        # Show sample results
        if results:
            sample = results[0]
            logger.info(f"  Sample result keys: {list(sample.keys())}")

        return results

    except Exception as e:
        parse_time = time.time() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        logger.error(f"✗ Parse failed after {parse_time:.2f}s")
        logger.error(f"  Memory at failure (current): {format_bytes(current)}")
        logger.error(f"  Memory at failure (peak): {format_bytes(peak)}")
        logger.exception(f"Error: {e}")
        return None


def test_job_import(release, module, build_number):
    """Test full job import with database operations."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing Import: {release}/{module}/{build_number}")
    logger.info(f"{'='*60}\n")

    # Find artifact path
    artifact_path = f"logs/{release}/{module}/{build_number}/test-results.xml"

    if not os.path.exists(artifact_path):
        logger.warning(f"Artifact not found at expected path: {artifact_path}")
        logger.info("Searching for artifact...")

        # Search for it
        possible_paths = list(Path('logs').rglob(f"*/{build_number}/test-results.xml"))
        if possible_paths:
            artifact_path = str(possible_paths[0])
            logger.info(f"Found artifact: {artifact_path}")
        else:
            logger.error("Could not find artifact anywhere in logs/")
            return False

    # Step 1: Test parsing only
    logger.info("\n--- Step 1: XML Parsing Test ---")
    results = test_artifact_parsing(artifact_path)
    if results is None:
        logger.error("Parsing failed, aborting import test")
        return False

    # Step 2: Test database import
    logger.info("\n--- Step 2: Database Import Test ---")

    db = SessionLocal()
    tracemalloc.start()
    start_time = time.time()

    try:
        logger.info(f"Starting import to database...")

        # Import the job
        result = import_jenkins_job(
            db=db,
            release_version=release,
            module_name=module,
            build_number=int(build_number),
            parent_job_id=None,
            force=True  # Force reimport for testing
        )

        import_time = time.time() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        logger.info(f"✓ Import successful!")
        logger.info(f"  Duration: {import_time:.2f}s")
        logger.info(f"  Result: {result}")
        logger.info(f"  Memory (current): {format_bytes(current)}")
        logger.info(f"  Memory (peak): {format_bytes(peak)}")

        db.commit()
        return True

    except Exception as e:
        import_time = time.time() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        logger.error(f"✗ Import failed after {import_time:.2f}s")
        logger.error(f"  Memory at failure (current): {format_bytes(current)}")
        logger.error(f"  Memory at failure (peak): {format_bytes(peak)}")
        logger.exception(f"Error: {e}")

        db.rollback()
        return False

    finally:
        db.close()


def main():
    if len(sys.argv) != 4:
        print("Usage: python scripts/test_job_import.py <release> <module> <build_number>")
        print("Example: python scripts/test_job_import.py 7.0 vpn 14")
        sys.exit(1)

    release = sys.argv[1]
    module = sys.argv[2]
    build_number = sys.argv[3]

    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Project root: {project_root}")

    success = test_job_import(release, module, build_number)

    logger.info(f"\n{'='*60}")
    if success:
        logger.info("✓ All tests PASSED")
        logger.info("The job can be imported successfully.")
        logger.info("\nNext steps:")
        logger.info("1. Check peak memory usage above")
        logger.info("2. Ensure gunicorn worker timeout > import duration")
        logger.info("3. Ensure server has sufficient RAM for peak memory usage")
    else:
        logger.error("✗ Tests FAILED")
        logger.error("Review errors above and check:")
        logger.error("1. Artifact file exists and is valid XML")
        logger.error("2. Database is accessible and not locked")
        logger.error("3. Sufficient memory available")
    logger.info(f"{'='*60}\n")

    logger.info(f"Full debug log saved to: test_import_debug.log")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
