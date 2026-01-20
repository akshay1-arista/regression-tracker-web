#!/usr/bin/env python3
"""
Backfill testcase_module field for all existing test results.

This script extracts module names from file_path and updates the
testcase_module field in the test_results table.

Usage:
    python scripts/backfill_testcase_modules.py [--dry-run] [--show-unparseable]

Options:
    --dry-run           Preview changes without committing to database
    --show-unparseable  Show sample of file paths that couldn't be parsed
"""
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.db_models import TestResult
from app.utils.testcase_helpers import extract_module_from_path


def verify_backfill(session):
    """
    Verify backfill results and print statistics.

    Returns:
        dict: Statistics about the backfill
    """
    total = session.query(func.count(TestResult.id)).scalar()
    with_module = session.query(func.count(TestResult.id))\
        .filter(TestResult.testcase_module.isnot(None))\
        .scalar()
    without_module = total - with_module

    # Get module distribution
    module_counts = session.query(
        TestResult.testcase_module,
        func.count(TestResult.id).label('count')
    ).filter(
        TestResult.testcase_module.isnot(None)
    ).group_by(
        TestResult.testcase_module
    ).order_by(
        func.count(TestResult.id).desc()
    ).all()

    return {
        'total': total,
        'with_module': with_module,
        'without_module': without_module,
        'coverage_percent': (with_module / total * 100) if total > 0 else 0,
        'module_counts': module_counts
    }


def main():
    """Backfill testcase_module for all existing test results."""
    parser = argparse.ArgumentParser(description='Backfill testcase_module field')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without committing')
    parser.add_argument('--show-unparseable', action='store_true',
                        help='Show sample of unparseable file paths')
    args = parser.parse_args()

    db_path = Path(__file__).parent.parent / "data" / "regression_tracker.db"

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    mode = "🔍 DRY RUN MODE" if args.dry_run else "🔄 Backfilling"
    print(f"{mode} - Processing testcase_module field...\n")

    # Get total count
    total = session.query(func.count(TestResult.id)).scalar()
    print(f"📊 Total test results to process: {total:,}\n")

    # Process in batches of 1000 for memory efficiency
    batch_size = 1000
    updated_count = 0
    skipped_count = 0
    unparseable_paths = []
    module_distribution = defaultdict(int)

    for offset in range(0, total, batch_size):
        # Fetch batch
        test_results = session.query(TestResult).limit(batch_size).offset(offset).all()

        for test_result in test_results:
            # Extract module from file path
            derived_module = extract_module_from_path(test_result.file_path)

            if derived_module:
                if not args.dry_run:
                    test_result.testcase_module = derived_module
                updated_count += 1
                module_distribution[derived_module] += 1
            else:
                skipped_count += 1
                if args.show_unparseable and len(unparseable_paths) < 20:
                    unparseable_paths.append(test_result.file_path)

        # Commit batch (unless dry run)
        if not args.dry_run:
            session.commit()

        # Progress update
        progress = min(offset + batch_size, total)
        print(f"Progress: {progress:,}/{total:,} ({progress/total*100:.1f}%)", end='\r')

    print(f"\n\n{'✅ Dry run complete!' if args.dry_run else '✅ Backfill complete!'}")
    print(f"   Would update: {updated_count:,} test results" if args.dry_run
          else f"   Updated: {updated_count:,} test results")
    print(f"   Skipped: {skipped_count:,} test results (no matching pattern)")
    print(f"   Coverage: {updated_count/total*100:.1f}%\n")

    # Show unparseable paths if requested
    if args.show_unparseable and unparseable_paths:
        print(f"🔍 Sample of unparseable file paths ({len(unparseable_paths)} shown):")
        for path in unparseable_paths[:10]:
            print(f"   - {path}")
        if len(unparseable_paths) > 10:
            print(f"   ... and {len(unparseable_paths) - 10} more")
        print()

    # Show module distribution
    print(f"📁 {len(module_distribution)} unique modules found:")
    sorted_modules = sorted(module_distribution.items(), key=lambda x: x[1], reverse=True)
    for module, count in sorted_modules:
        print(f"   - {module}: {count:,} test results ({count/updated_count*100:.1f}%)")

    # Verification step (only if not dry run)
    if not args.dry_run:
        print("\n🔍 Verifying backfill results...")
        stats = verify_backfill(session)

        print(f"\n📈 Verification Statistics:")
        print(f"   Total records: {stats['total']:,}")
        print(f"   With testcase_module: {stats['with_module']:,}")
        print(f"   Without testcase_module: {stats['without_module']:,}")
        print(f"   Coverage: {stats['coverage_percent']:.2f}%")

        if stats['without_module'] > 0:
            print(f"\n⚠️  Warning: {stats['without_module']:,} records still missing testcase_module")
            print(f"   This may be expected for test files outside the data_plane/tests/* pattern")

    session.close()

    if args.dry_run:
        print("\n💡 To apply changes, run without --dry-run flag")


if __name__ == "__main__":
    main()
