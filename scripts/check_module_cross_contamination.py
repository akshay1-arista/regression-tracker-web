#!/usr/bin/env python3
"""
Check for module cross-contamination in test results.

This script identifies test cases that are running in modules different from
their expected module based on file path conventions.

Expected path patterns:
- data_plane/tests/business_policy -> business_policy module
- data_plane/tests/routing -> routing module
- etc.

Usage:
    python check_module_cross_contamination.py [release_name]

Examples:
    python check_module_cross_contamination.py           # Analyzes most recent release
    python check_module_cross_contamination.py 7.0       # Analyzes release 7.0
    python check_module_cross_contamination.py 6.4       # Analyzes release 6.4
"""
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, joinedload

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.db_models import TestResult, Job, Module, Release


def extract_expected_module_from_path(file_path: str) -> str:
    """
    Extract the expected module name from a test file path.

    Assumes pattern: data_plane/tests/{module_name}/...
    """
    if not file_path:
        return None

    parts = file_path.split('/')
    if len(parts) >= 3 and parts[0] == 'data_plane' and parts[1] == 'tests':
        return parts[2]

    return None


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Check for module cross-contamination in test results',
        epilog='If no release is specified, analyzes the most recent release.'
    )
    parser.add_argument('release', nargs='?', help='Release name to analyze (e.g., 7.0, 6.4)')
    args = parser.parse_args()

    # Connect to database
    db_path = Path(__file__).parent.parent / "data" / "regression_tracker.db"
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    # Get available releases
    releases = session.query(Release.name).distinct().order_by(Release.name.desc()).all()
    releases = [r[0] for r in releases]

    print("🔍 Checking for module cross-contamination...\n")
    print(f"Available releases: {', '.join(releases)}")

    # Determine target release
    if args.release:
        if args.release in releases:
            target_release = args.release
        else:
            print(f"\n❌ Release '{args.release}' not found in database")
            print(f"Available releases: {', '.join(releases)}")
            session.close()
            sys.exit(1)
    else:
        # Use the most recent release by default (first in descending order)
        target_release = releases[0] if releases else None

    if not target_release:
        print("❌ No releases found in database")
        session.close()
        sys.exit(1)

    print(f"\n🎯 Analyzing release: {target_release}\n")

    # Query all test results for the target release
    # Use DISTINCT on file_path + test_name to count unique test cases, not all executions
    test_results = (
        session.query(TestResult.file_path, TestResult.test_name, Module.name, Release.name)
        .join(Job, TestResult.job_id == Job.id)
        .join(Module, Job.module_id == Module.id)
        .join(Release, Module.release_id == Release.id)
        .filter(
            TestResult.file_path.like('data_plane/tests/%'),
            Release.name == target_release
        )
        .distinct()
        .all()
    )

    print(f"📊 Total unique test cases with data_plane/tests paths in {target_release}: {len(test_results)}\n")

    # Track mismatches by expected module and actual module
    mismatches = defaultdict(lambda: defaultdict(int))
    mismatch_details = defaultdict(lambda: defaultdict(list))

    for file_path, test_name, actual_module, release in test_results:
        expected_module = extract_expected_module_from_path(file_path)

        if expected_module and expected_module != actual_module:
            mismatches[expected_module][actual_module] += 1
            # Store some sample test cases
            if len(mismatch_details[expected_module][actual_module]) < 5:
                mismatch_details[expected_module][actual_module].append({
                    'test_name': test_name,
                    'file_path': file_path,
                    'release': release
                })

    if not mismatches:
        print("✅ No cross-contamination detected! All test cases are running in their expected modules.")
        session.close()
        return

    # Report findings
    print("⚠️  CROSS-CONTAMINATION DETECTED!\n")
    print("=" * 80)

    for expected_module in sorted(mismatches.keys()):
        print(f"\n📁 Test cases with path 'data_plane/tests/{expected_module}/*':")
        print(f"   Expected to run in: {expected_module}")
        print(f"   Actually running in:")

        for actual_module, count in sorted(mismatches[expected_module].items(), key=lambda x: x[1], reverse=True):
            print(f"      - {actual_module}: {count} test cases")

            # Show sample test cases
            samples = mismatch_details[expected_module][actual_module]
            for sample in samples[:3]:
                print(f"          • {sample['test_name']}")
                print(f"            Path: {sample['file_path']}")
                print(f"            Release: {sample['release']}")

    print("\n" + "=" * 80)
    print(f"\n📈 Summary Statistics for {target_release}:")

    total_mismatches = sum(sum(modules.values()) for modules in mismatches.values())
    total_unique_tests = len(test_results)
    print(f"   Total unique test cases analyzed: {total_unique_tests}")
    print(f"   Unique test cases running in wrong modules: {total_mismatches}")
    print(f"   Percentage misplaced: {(total_mismatches/total_unique_tests*100):.1f}%")
    print(f"   Affected modules (expected to own these tests): {len(mismatches)}")

    all_actual_modules = set()
    for modules in mismatches.values():
        all_actual_modules.update(modules.keys())
    print(f"   Modules executing misplaced tests: {len(all_actual_modules)}")

    print("\n💡 Recommendation:")
    print("   Review Jenkins job configurations to ensure test selection")
    print("   matches the module's intended test suite.")
    print(f"\n   To analyze a different release, run:")
    print(f"   python {Path(__file__).name} [release_name]")
    print(f"\n   Available releases: {', '.join(releases)}")

    session.close()


if __name__ == "__main__":
    main()
