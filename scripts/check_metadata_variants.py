#!/usr/bin/env python3
"""
Diagnostic script to check metadata variants for a specific test case.

Usage:
    python scripts/check_metadata_variants.py <testcase_name>

Example:
    python scripts/check_metadata_variants.py test_bgp_routing
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.db_models import TestcaseMetadata, Release


def check_metadata_variants(testcase_name: str):
    """Check all metadata variants for a given test case."""
    db = SessionLocal()

    try:
        print(f"\n{'='*80}")
        print(f"Checking metadata variants for: {testcase_name}")
        print(f"{'='*80}\n")

        # Query all metadata records for this test
        results = db.query(
            TestcaseMetadata,
            Release.name.label('release_name')
        ).outerjoin(
            Release, TestcaseMetadata.release_id == Release.id
        ).filter(
            TestcaseMetadata.testcase_name == testcase_name
        ).all()

        if not results:
            print(f"❌ No metadata found for test case: {testcase_name}")
            print("\nPossible reasons:")
            print("  1. Test name is misspelled")
            print("  2. No metadata has been imported for this test")
            print("  3. Test only exists in execution history (no metadata)")
            return

        print(f"Found {len(results)} metadata variant(s):\n")

        for idx, row in enumerate(results, 1):
            metadata = row.TestcaseMetadata
            release_name = row.release_name or "Global"

            print(f"Variant #{idx}: {release_name}")
            print(f"  Release ID: {metadata.release_id or 'NULL (Global)'}")
            print(f"  Test Case ID: {metadata.test_case_id or 'N/A'}")
            print(f"  TestRail ID: {metadata.testrail_id or 'N/A'}")
            print(f"  Priority: {metadata.priority or 'N/A'}")
            print(f"  Topology: {metadata.topology or 'N/A'}")
            print(f"  Module: {metadata.module or 'N/A'}")
            print(f"  Test State: {metadata.test_state or 'N/A'}")
            print(f"  Component: {metadata.component or 'N/A'}")
            print(f"  Automation Status: {metadata.automation_status or 'N/A'}")
            print(f"  Is Removed: {metadata.is_removed}")
            print(f"  Test Path: {metadata.test_path or 'N/A'}")
            print()

        # Check available releases
        print(f"\n{'='*80}")
        print("Available releases in database:")
        print(f"{'='*80}\n")

        releases = db.query(Release).filter(Release.is_active == True).all()
        for release in releases:
            print(f"  - {release.name} (ID: {release.id}, Branch: {release.git_branch or 'N/A'})")

        print(f"\n{'='*80}")
        print("Summary:")
        print(f"{'='*80}\n")

        if len(results) == 1 and results[0].release_name is None:
            print("⚠️  This test ONLY has Global metadata (no release-specific metadata)")
            print("\nTo add release-specific metadata:")
            print("  1. Ensure the test exists in the Git repository for the desired release")
            print("  2. Run metadata sync from Admin page for the specific release")
            print("  3. Check sync logs for any errors or warnings")
        else:
            print(f"✅ This test has {len(results)} metadata variant(s)")
            if any(r.release_name is None for r in results):
                print("   - Includes Global metadata")
            release_specific = [r.release_name for r in results if r.release_name]
            if release_specific:
                print(f"   - Release-specific: {', '.join(release_specific)}")

    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_metadata_variants.py <testcase_name>")
        print("\nExample:")
        print("  python scripts/check_metadata_variants.py test_bgp_routing")
        sys.exit(1)

    testcase_name = sys.argv[1]
    check_metadata_variants(testcase_name)
