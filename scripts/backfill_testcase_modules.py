#!/usr/bin/env python3
"""
Backfill testcase_module field for all existing test results.

This script extracts module names from file_path and updates the
testcase_module field in the test_results table.

Usage:
    python scripts/backfill_testcase_modules.py
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.db_models import TestResult
from app.utils.testcase_helpers import extract_module_from_path


def main():
    """Backfill testcase_module for all existing test results."""
    db_path = Path(__file__).parent.parent / "data" / "regression_tracker.db"

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    print("🔄 Backfilling testcase_module field...\n")

    # Get total count
    total = session.query(func.count(TestResult.id)).scalar()
    print(f"📊 Total test results to process: {total:,}\n")

    # Process in batches of 1000 for memory efficiency
    batch_size = 1000
    updated_count = 0
    skipped_count = 0

    for offset in range(0, total, batch_size):
        # Fetch batch
        test_results = session.query(TestResult).limit(batch_size).offset(offset).all()

        for test_result in test_results:
            # Extract module from file path
            derived_module = extract_module_from_path(test_result.file_path)

            if derived_module:
                test_result.testcase_module = derived_module
                updated_count += 1
            else:
                skipped_count += 1

        # Commit batch
        session.commit()

        # Progress update
        progress = min(offset + batch_size, total)
        print(f"Progress: {progress:,}/{total:,} ({progress/total*100:.1f}%)", end='\r')

    print(f"\n\n✅ Backfill complete!")
    print(f"   Updated: {updated_count:,} test results")
    print(f"   Skipped: {skipped_count:,} test results (no matching pattern)")
    print(f"   Percentage updated: {updated_count/total*100:.1f}%\n")

    # Show sample of modules found
    modules = session.query(TestResult.testcase_module).distinct()\
        .filter(TestResult.testcase_module.isnot(None))\
        .order_by(TestResult.testcase_module)\
        .all()

    module_names = [m[0] for m in modules]
    print(f"📁 {len(module_names)} unique modules found:")
    for module in module_names:
        print(f"   - {module}")

    session.close()


if __name__ == "__main__":
    main()
