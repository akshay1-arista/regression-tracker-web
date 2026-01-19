#!/usr/bin/env python3
"""
One-time migration script to import all historical data from logs directory into database.

Usage:
    python scripts/import_existing_data.py [--logs-path PATH] [--skip-existing]

Examples:
    # Import all logs from default path (../logs)
    python scripts/import_existing_data.py

    # Import from custom path
    python scripts/import_existing_data.py --logs-path /path/to/logs

    # Force re-import (don't skip existing jobs)
    python scripts/import_existing_data.py --no-skip-existing
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from app.database import get_db_context
from app.config import get_settings
from app.services.import_service import import_all_logs


def main():
    parser = argparse.ArgumentParser(
        description="Import historical test data from logs directory into database"
    )
    parser.add_argument(
        '--logs-path',
        type=str,
        default=None,
        help='Path to logs directory (default: from config or ../logs)'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=True,
        help='Skip jobs that already exist in database (default: True)'
    )
    parser.add_argument(
        '--no-skip-existing',
        dest='skip_existing',
        action='store_false',
        help='Re-import all jobs even if they exist'
    )

    args = parser.parse_args()

    # Determine logs path
    settings = get_settings()
    if args.logs_path:
        logs_path = Path(args.logs_path).resolve()
    elif settings.LOGS_BASE_PATH:
        logs_path = Path(settings.LOGS_BASE_PATH).resolve()
    else:
        # Default to ../logs relative to project root
        logs_path = (SCRIPT_DIR.parent / 'logs').resolve()

    # Path traversal protection: ensure logs path is within allowed directories
    # Allow paths within project directory or sibling directories (common for development)
    project_parent = SCRIPT_DIR.parent.resolve()
    try:
        # Check if logs_path is relative to project parent or its siblings
        # This allows ../regression_tracker/logs but prevents /etc/passwd or C:\Windows
        logs_path.relative_to(project_parent.parent)
    except ValueError:
        print(f"ERROR: Logs path must be within the project directory tree")
        print(f"       Logs path: {logs_path}")
        print(f"       Project parent: {project_parent.parent}")
        sys.exit(1)

    if not logs_path.exists():
        print(f"ERROR: Logs directory not found: {logs_path}")
        print("Please specify a valid path with --logs-path")
        sys.exit(1)

    if not logs_path.is_dir():
        print(f"ERROR: Logs path is not a directory: {logs_path}")
        sys.exit(1)

    print(f"=== Regression Tracker - Historical Data Import ===")
    print(f"Logs directory: {logs_path}")
    print(f"Database: {settings.DATABASE_URL}")
    print(f"Skip existing jobs: {args.skip_existing}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Import all logs
    with get_db_context() as db:
        results = import_all_logs(
            db=db,
            logs_base_path=str(logs_path),
            skip_existing_jobs=args.skip_existing
        )

    # Update last_processed_build for all releases after import
    print("\n=== Syncing last_processed_build ===")
    with get_db_context() as db:
        from app.models.db_models import Release, Module, Job
        from sqlalchemy import func, cast, Integer

        releases = db.query(Release).all()
        updates_made = 0

        for release in releases:
            # Query max parent_job_id for this release
            max_parent_job = db.query(
                func.max(cast(Job.parent_job_id, Integer))
            ).join(
                Module
            ).filter(
                Module.release_id == release.id
            ).scalar()

            if max_parent_job:
                old_value = release.last_processed_build or 0
                if max_parent_job != old_value:
                    release.last_processed_build = max_parent_job
                    updates_made += 1
                    print(f"{release.name:15s} {old_value:>6} → {max_parent_job:<6} (updated)")
                else:
                    print(f"{release.name:15s} {old_value:>6}   (no change)")

        db.commit()
        print(f"Synced {updates_made} release(s)")

    # Print summary
    print("\n" + "=" * 60)
    print("=== Import Summary ===")
    print("=" * 60)

    total_releases = len(results)
    total_modules = sum(r[0] for r in results.values())
    total_jobs = sum(r[1] for r in results.values())
    total_tests = sum(r[2] for r in results.values())

    for release, (modules, jobs, tests) in results.items():
        print(f"{release:15s} | Modules: {modules:3d} | Jobs: {jobs:4d} | Tests: {tests:7d}")

    print("=" * 60)
    print(f"Total Releases: {total_releases}")
    print(f"Total Modules:  {total_modules}")
    print(f"Total Jobs:     {total_jobs}")
    print(f"Total Tests:    {total_tests}")
    print(f"Completed at:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Verify database
    print("\n=== Database Verification ===")
    with get_db_context() as db:
        from app.models.db_models import Release, Module, Job, TestResult

        release_count = db.query(Release).count()
        module_count = db.query(Module).count()
        job_count = db.query(Job).count()
        test_count = db.query(TestResult).count()

        print(f"Releases in database: {release_count}")
        print(f"Modules in database:  {module_count}")
        print(f"Jobs in database:     {job_count}")
        print(f"Tests in database:    {test_count}")

    print("\n✓ Import completed successfully!")


if __name__ == "__main__":
    main()
