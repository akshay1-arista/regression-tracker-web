#!/usr/bin/env python3
"""
Debug script to check test_state data consistency between dashboard and trends.

Usage:
    python debug_test_state.py --release 7.0 --module <module_name>
"""

import argparse
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.database import DATABASE_URL
from app.models.db_models import TestResult, TestcaseMetadata, Job, Module, Release
from app.services import data_service, trend_analyzer

def debug_test_state(release_name: str, module_name: str):
    """Debug test_state filtering issues."""

    # Create database session
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        print(f"\n{'='*80}")
        print(f"Debugging test_state for Release: {release_name}, Module: {module_name}")
        print(f"{'='*80}\n")

        # 1. Check TestcaseMetadata counts
        print("1. TestcaseMetadata counts:")
        metadata_staging = db.query(func.count(TestcaseMetadata.id)).filter(
            TestcaseMetadata.module == module_name,
            TestcaseMetadata.test_state == 'STAGING'
        ).scalar()
        metadata_prod = db.query(func.count(TestcaseMetadata.id)).filter(
            TestcaseMetadata.module == module_name,
            TestcaseMetadata.test_state == 'PROD'
        ).scalar()
        metadata_null = db.query(func.count(TestcaseMetadata.id)).filter(
            TestcaseMetadata.module == module_name,
            TestcaseMetadata.test_state.is_(None)
        ).scalar()

        print(f"   STAGING: {metadata_staging}")
        print(f"   PROD: {metadata_prod}")
        print(f"   NULL: {metadata_null}")

        # 2. Check actual test_state values (case sensitivity)
        print("\n2. Distinct test_state values in metadata:")
        distinct_states = db.query(TestcaseMetadata.test_state).filter(
            TestcaseMetadata.module == module_name,
            TestcaseMetadata.test_state.isnot(None)
        ).distinct().all()
        for state in distinct_states:
            count = db.query(func.count(TestcaseMetadata.id)).filter(
                TestcaseMetadata.module == module_name,
                TestcaseMetadata.test_state == state[0]
            ).scalar()
            print(f"   '{state[0]}': {count} tests")

        # 3. Get release and jobs
        release = data_service.get_release_by_name(db, release_name)
        if not release:
            print(f"\n❌ Release '{release_name}' not found!")
            return

        jobs = data_service.get_jobs_for_testcase_module(db, release_name, module_name)
        if not jobs:
            print(f"\n❌ No jobs found for module '{module_name}' in release '{release_name}'")
            return

        print(f"\n3. Jobs found: {len(jobs)}")
        latest_job = jobs[0]
        print(f"   Latest job: {latest_job.job_id}")

        # 4. Check trends calculation
        print("\n4. Calculating trends...")
        all_trends = trend_analyzer.calculate_test_trends(
            db, release_name, module_name,
            use_testcase_module=True,
            job_limit=5
        )
        print(f"   Total trends calculated: {len(all_trends)}")

        # 5. Check test_state enrichment in trends
        print("\n5. Test state distribution in trends:")
        staging_trends = [t for t in all_trends if t.test_state and t.test_state.upper() == 'STAGING']
        prod_trends = [t for t in all_trends if t.test_state and t.test_state.upper() == 'PROD']
        null_trends = [t for t in all_trends if not t.test_state]

        print(f"   STAGING: {len(staging_trends)}")
        print(f"   PROD: {len(prod_trends)}")
        print(f"   NULL: {len(null_trends)}")

        # 6. Show sample STAGING trends
        if staging_trends:
            print("\n6. Sample STAGING trends:")
            for i, trend in enumerate(staging_trends[:5], 1):
                print(f"   {i}. {trend.test_name}")
                print(f"      test_state: '{trend.test_state}'")
                print(f"      test_key: {trend.test_key}")
        else:
            print("\n6. ❌ No STAGING trends found!")

            # Check if any metadata matches test names in trends
            print("\n   Checking metadata for existing trends...")
            for i, trend in enumerate(all_trends[:5], 1):
                # Normalize test name for matching
                from app.services.testcase_metadata_service import normalize_test_name
                normalized_name = normalize_test_name(trend.test_name)

                metadata = db.query(TestcaseMetadata).filter(
                    TestcaseMetadata.testcase_name == normalized_name
                ).first()

                print(f"   {i}. Trend: {trend.test_name[:60]}")
                print(f"      Normalized: {normalized_name[:60]}")
                if metadata:
                    print(f"      ✓ Metadata found: test_state='{metadata.test_state}', module='{metadata.module}'")
                else:
                    print(f"      ✗ No metadata found")

        # 7. Check priority stats for comparison
        print("\n7. Priority stats (dashboard view):")
        stats = data_service.get_priority_statistics(
            db, release_name, module_name, latest_job.job_id,
            test_states=['STAGING']
        )
        total_staging = sum(stat['total'] for stat in stats)
        print(f"   Total STAGING tests in priority stats: {total_staging}")

        if total_staging > 0 and len(staging_trends) == 0:
            print("\n   ⚠️  DISCREPANCY FOUND:")
            print(f"   Dashboard shows {total_staging} STAGING tests")
            print(f"   But trends show {len(staging_trends)} STAGING trends")
            print("\n   Possible causes:")
            print("   1. Test results don't have matching metadata entries")
            print("   2. Module field mismatch in metadata")
            print("   3. Test name normalization issue")

    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Debug test_state filtering')
    parser.add_argument('--release', required=True, help='Release name (e.g., 7.0)')
    parser.add_argument('--module', required=True, help='Module name')

    args = parser.parse_args()
    debug_test_state(args.release, args.module)
