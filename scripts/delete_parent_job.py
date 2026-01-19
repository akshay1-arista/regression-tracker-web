#!/usr/bin/env python3
"""
Script to safely delete all data for a specific parent_job_id in a release.

Usage:
    python scripts/delete_parent_job.py --release 7.0.0.0 --parent-job-id 13
    python scripts/delete_parent_job.py --release 7.0.0.0 --parent-job-id 13 --confirm

This will delete:
- All jobs with the specified parent_job_id in the release
- All test results for those jobs (via cascade)
"""
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services import data_service
from app.models.db_models import Job, TestResult, Module


def preview_deletion(db: Session, release_name: str, parent_job_id: str):
    """
    Preview what will be deleted without actually deleting.

    Args:
        db: Database session
        release_name: Release name (e.g., "7.0.0.0")
        parent_job_id: Parent job ID to delete

    Returns:
        Tuple of (jobs_to_delete, test_results_count, modules_affected)
    """
    # Get all jobs for this parent_job_id in the release
    jobs = data_service.get_jobs_by_parent_job_id(db, release_name, parent_job_id)

    if not jobs:
        return [], 0, set()

    # Count test results that will be deleted
    job_ids = [job.id for job in jobs]
    test_results_count = db.query(func.count(TestResult.id))\
        .filter(TestResult.job_id.in_(job_ids))\
        .scalar()

    # Get affected modules
    modules_affected = set()
    for job in jobs:
        module = db.query(Module).filter(Module.id == job.module_id).first()
        if module:
            modules_affected.add(module.name)

    return jobs, test_results_count, modules_affected


def delete_parent_job_data(db: Session, release_name: str, parent_job_id: str):
    """
    Delete all data for a parent_job_id in a release.

    Args:
        db: Database session
        release_name: Release name
        parent_job_id: Parent job ID to delete

    Returns:
        Tuple of (jobs_deleted, test_results_deleted)
    """
    # Get all jobs for this parent_job_id
    jobs = data_service.get_jobs_by_parent_job_id(db, release_name, parent_job_id)

    if not jobs:
        return 0, 0

    # Count before deletion
    job_ids = [job.id for job in jobs]
    test_results_count = db.query(func.count(TestResult.id))\
        .filter(TestResult.job_id.in_(job_ids))\
        .scalar()

    jobs_count = len(jobs)

    # Delete jobs (test_results will be cascade deleted)
    for job in jobs:
        db.delete(job)

    db.commit()

    return jobs_count, test_results_count


def main():
    parser = argparse.ArgumentParser(
        description='Delete all data for a specific parent_job_id in a release'
    )
    parser.add_argument(
        '--release',
        required=True,
        help='Release name (e.g., "7.0.0.0")'
    )
    parser.add_argument(
        '--parent-job-id',
        required=True,
        help='Parent job ID to delete (e.g., "13")'
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Skip confirmation prompt and delete immediately'
    )

    args = parser.parse_args()

    release_name = args.release
    parent_job_id = args.parent_job_id

    print(f"\n{'='*70}")
    print(f"Delete Parent Job Data")
    print(f"{'='*70}")
    print(f"Release: {release_name}")
    print(f"Parent Job ID: {parent_job_id}")
    print(f"{'='*70}\n")

    # Create database session
    db = SessionLocal()

    try:
        # Verify release exists
        release = data_service.get_release_by_name(db, release_name)
        if not release:
            print(f"❌ Error: Release '{release_name}' not found")
            sys.exit(1)

        # Preview what will be deleted
        print("🔍 Previewing deletion...")
        jobs, test_results_count, modules_affected = preview_deletion(
            db, release_name, parent_job_id
        )

        if not jobs:
            print(f"\n✅ No data found for parent_job_id '{parent_job_id}' in release '{release_name}'")
            print("Nothing to delete.")
            sys.exit(0)

        # Show preview
        print(f"\n📊 Preview of data to be deleted:\n")
        print(f"  Jobs:         {len(jobs)}")
        print(f"  Test Results: {test_results_count:,}")
        print(f"  Modules:      {len(modules_affected)}")
        print(f"\n  Affected Modules:")
        for module in sorted(modules_affected):
            module_jobs = [j for j in jobs if db.query(Module).filter(Module.id == j.module_id).first().name == module]
            print(f"    - {module}: {len(module_jobs)} job(s)")

        print(f"\n  Job IDs to be deleted:")
        job_ids_grouped = {}
        for job in jobs:
            module = db.query(Module).filter(Module.id == job.module_id).first()
            if module.name not in job_ids_grouped:
                job_ids_grouped[module.name] = []
            job_ids_grouped[module.name].append(job.job_id)

        for module, job_ids in sorted(job_ids_grouped.items()):
            print(f"    {module}: {', '.join(sorted(job_ids, key=lambda x: int(x)))}")

        # Confirm deletion
        if not args.confirm:
            print(f"\n{'='*70}")
            print("⚠️  WARNING: This action cannot be undone!")
            print(f"{'='*70}\n")
            response = input("Type 'DELETE' to confirm deletion: ")

            if response != 'DELETE':
                print("\n❌ Deletion cancelled.")
                sys.exit(0)

        # Perform deletion
        print(f"\n🗑️  Deleting data...")
        jobs_deleted, test_results_deleted = delete_parent_job_data(
            db, release_name, parent_job_id
        )

        print(f"\n✅ Deletion complete!\n")
        print(f"  Deleted:")
        print(f"    - {jobs_deleted} job(s)")
        print(f"    - {test_results_deleted:,} test result(s)")
        print(f"\n{'='*70}\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
