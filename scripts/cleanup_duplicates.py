#!/usr/bin/env python3
"""
Cleanup duplicate test results in the database.

This script identifies and removes duplicate test results, keeping only the
last instance (highest ID) of each test within a job.

Usage:
    python scripts/cleanup_duplicates.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add app to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.db_models import TestResult
from sqlalchemy import func


def find_duplicates(db):
    """Find all duplicate test results."""
    duplicates = db.query(
        TestResult.job_id,
        TestResult.file_path,
        TestResult.class_name,
        TestResult.test_name,
        func.count(TestResult.id).label('count')
    ).group_by(
        TestResult.job_id,
        TestResult.file_path,
        TestResult.class_name,
        TestResult.test_name
    ).having(func.count(TestResult.id) > 1).all()

    return duplicates


def cleanup_duplicates(db, dry_run=False):
    """
    Remove duplicate test results, keeping the latest instance.

    Args:
        db: Database session
        dry_run: If True, only report what would be deleted

    Returns:
        Number of duplicates removed
    """
    duplicates = find_duplicates(db)

    if not duplicates:
        print("✓ No duplicates found!")
        return 0

    print(f"\nFound {len(duplicates)} duplicate test cases")
    print("=" * 80)

    total_removed = 0

    for dup in duplicates:
        job_id, file_path, class_name, test_name, count = dup

        # Get all instances of this duplicate, ordered by ID
        records = db.query(TestResult).filter(
            TestResult.job_id == job_id,
            TestResult.file_path == file_path,
            TestResult.class_name == class_name,
            TestResult.test_name == test_name
        ).order_by(TestResult.id).all()

        # Keep the last one (highest ID), delete the rest
        to_keep = records[-1]
        to_delete = records[:-1]

        print(f"\nJob {job_id}: {test_name}")
        print(f"  Total instances: {count}")
        print(f"  Keeping: ID={to_keep.id}, Status={to_keep.status.value}")

        for i, record in enumerate(to_delete, 1):
            print(f"  Deleting {i}: ID={record.id}, Status={record.status.value}")

            if not dry_run:
                db.delete(record)
                total_removed += 1

    if not dry_run:
        db.commit()
        print(f"\n✓ Removed {total_removed} duplicate test results")
    else:
        print(f"\n[DRY RUN] Would remove {len(duplicates) * (count - 1)} duplicate test results")
        print("Run without --dry-run to actually delete duplicates")

    return total_removed


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Cleanup duplicate test results in the database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  Regression Tracker - Duplicate Cleanup")
    print("=" * 80)

    db = SessionLocal()

    try:
        removed = cleanup_duplicates(db, dry_run=args.dry_run)

        if not args.dry_run and removed > 0:
            # Verify no duplicates remain
            remaining = find_duplicates(db)
            if remaining:
                print(f"\n⚠ WARNING: {len(remaining)} duplicates still remain!")
                sys.exit(1)
            else:
                print("\n✓ All duplicates successfully removed!")

        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
