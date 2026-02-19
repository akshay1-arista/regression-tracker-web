#!/usr/bin/env python3
"""
Verify metadata distribution across releases.
Shows how many tests have Global vs release-specific metadata.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.db_models import TestcaseMetadata, Release
from sqlalchemy import func
from collections import defaultdict


def verify_metadata_distribution():
    """Check distribution of metadata across releases."""
    db = SessionLocal()

    try:
        print(f"\n{'='*80}")
        print("METADATA DISTRIBUTION ANALYSIS")
        print(f"{'='*80}\n")

        # Get all releases
        releases = db.query(Release).all()
        release_map = {r.id: r.name for r in releases}
        release_map[None] = "Global"

        print("Available Releases:")
        for release in releases:
            active = "✓" if release.is_active else "✗"
            branch = release.git_branch or "N/A"
            print(f"  [{active}] {release.name} (ID: {release.id}, Branch: {branch})")
        print()

        # Count metadata records by release
        print(f"{'='*80}")
        print("METADATA COUNTS BY RELEASE")
        print(f"{'='*80}\n")

        counts = db.query(
            TestcaseMetadata.release_id,
            func.count(TestcaseMetadata.id).label('count')
        ).group_by(TestcaseMetadata.release_id).all()

        total_records = 0
        for release_id, count in sorted(counts, key=lambda x: (x[0] is not None, x[0])):
            release_name = release_map.get(release_id, f"Unknown ({release_id})")
            print(f"  {release_name}: {count:,} records")
            total_records += count

        print(f"\n  TOTAL: {total_records:,} metadata records\n")

        # Find tests with multiple variants
        print(f"{'='*80}")
        print("TESTS WITH MULTIPLE METADATA VARIANTS")
        print(f"{'='*80}\n")

        # Query for tests that have more than one metadata record
        from sqlalchemy import select

        multi_variant_tests = db.query(
            TestcaseMetadata.testcase_name,
            func.count(TestcaseMetadata.id).label('variant_count')
        ).group_by(
            TestcaseMetadata.testcase_name
        ).having(
            func.count(TestcaseMetadata.id) > 1
        ).order_by(
            func.count(TestcaseMetadata.id).desc()
        ).limit(10).all()

        if multi_variant_tests:
            print(f"Top 10 tests with most variants:\n")
            for testcase_name, variant_count in multi_variant_tests:
                print(f"  {testcase_name}: {variant_count} variants")

                # Get details for this test
                variants = db.query(
                    TestcaseMetadata,
                    Release.name.label('release_name')
                ).outerjoin(
                    Release, TestcaseMetadata.release_id == Release.id
                ).filter(
                    TestcaseMetadata.testcase_name == testcase_name
                ).all()

                for v in variants:
                    release = v.release_name or "Global"
                    priority = v.TestcaseMetadata.priority or "N/A"
                    topology = v.TestcaseMetadata.topology or "N/A"
                    print(f"    → {release}: Priority={priority}, Topology={topology}")
                print()
        else:
            print("  No tests with multiple variants found.\n")

        # Check recent metadata sync status
        print(f"{'='*80}")
        print("RECENT METADATA SYNC LOGS")
        print(f"{'='*80}\n")

        from app.models.db_models import MetadataSyncLog
        from datetime import datetime

        recent_syncs = db.query(
            MetadataSyncLog,
            Release.name.label('release_name')
        ).join(
            Release, MetadataSyncLog.release_id == Release.id
        ).order_by(
            MetadataSyncLog.started_at.desc()
        ).limit(10).all()

        if recent_syncs:
            for sync, release_name in recent_syncs:
                status_symbol = "✓" if sync.status == "success" else "✗"
                started = sync.started_at.strftime('%Y-%m-%d %H:%M:%S') if sync.started_at else 'N/A'
                print(f"  [{status_symbol}] {release_name} - {sync.sync_type}")
                print(f"      Started: {started}")
                print(f"      Status: {sync.status}")
                print(f"      Tests: {sync.tests_discovered or 0} discovered, "
                      f"{sync.tests_added or 0} added, {sync.tests_updated or 0} updated, "
                      f"{sync.tests_removed or 0} removed")
                if sync.error_message:
                    print(f"      Error: {sync.error_message}")
                print()
        else:
            print("  No sync logs found.\n")

        # Summary
        print(f"{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}\n")

        global_count = next((count for release_id, count in counts if release_id is None), 0)
        release_specific_count = total_records - global_count

        print(f"  Total metadata records: {total_records:,}")
        print(f"  Global metadata: {global_count:,} ({global_count/total_records*100:.1f}%)")
        print(f"  Release-specific metadata: {release_specific_count:,} ({release_specific_count/total_records*100:.1f}%)")
        print()

        if release_specific_count == 0:
            print("⚠️  WARNING: No release-specific metadata found!")
            print("\nThis means:")
            print("  • All tests will only show 'Global' tab in the UI")
            print("  • Git metadata sync may not have run for any releases")
            print("\nTo fix:")
            print("  1. Go to Admin page → Metadata Sync section")
            print("  2. Select a release and click 'Sync Now'")
            print("  3. Monitor sync logs for errors")
            print()

    finally:
        db.close()


if __name__ == "__main__":
    verify_metadata_distribution()
