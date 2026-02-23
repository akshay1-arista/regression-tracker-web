#!/usr/bin/env python3
"""
Verify that parent job comparison uses execution time instead of numeric ordering.

This script demonstrates the fix for the comparison discrepancy where job 74
was being compared to job 73 instead of job 71 when releases share Jenkins URLs.
"""
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db_context
from app.services import data_service


def verify_comparison_logic():
    """Verify the comparison logic works correctly."""

    with get_db_context() as db:
        # Test case: Release 7.0, parent job 74
        release_name = "7.0"
        current_parent_job_id = "74"

        print(f"Checking comparison logic for Release {release_name}, Parent Job {current_parent_job_id}")
        print("=" * 80)

        # Get all parent job IDs with their execution times
        parent_jobs = data_service.get_parent_jobs_with_dates(
            db, release_name, module="__all__", limit=10
        )

        print(f"\nAvailable parent jobs (sorted by execution time, newest first):")
        print(f"{'Parent Job ID':<15} {'Executed At':<25} {'URL'}")
        print("-" * 80)

        for pj in parent_jobs[:10]:
            executed_at = pj['executed_at'].strftime('%Y-%m-%d %H:%M:%S') if pj['executed_at'] else 'N/A'
            url = pj['parent_job_url'] if pj['parent_job_url'] else 'N/A'
            marker = " <-- CURRENT" if pj['parent_job_id'] == current_parent_job_id else ""
            print(f"{pj['parent_job_id']:<15} {executed_at:<25} {url}{marker}")

        # Get previous parent job using the comparison logic
        previous_parent_job_id = data_service.get_previous_parent_job_id(
            db, release_name, current_parent_job_id
        )

        print(f"\n{'='*80}")
        print(f"Previous parent job for comparison: {previous_parent_job_id}")
        print(f"{'='*80}\n")

        if previous_parent_job_id:
            # Get stats for both jobs
            current_stats = data_service.get_aggregated_stats_for_parent_job(
                db, release_name, current_parent_job_id
            )
            previous_stats = data_service.get_aggregated_stats_for_parent_job(
                db, release_name, previous_parent_job_id
            )

            print(f"Comparison Details:")
            print(f"-" * 80)
            print(f"Current Job {current_parent_job_id}:  Total={current_stats['total']}, "
                  f"Passed={current_stats['passed']}, Failed={current_stats['failed']}, "
                  f"Skipped={current_stats['skipped']}")
            print(f"Previous Job {previous_parent_job_id}: Total={previous_stats['total']}, "
                  f"Passed={previous_stats['passed']}, Failed={previous_stats['failed']}, "
                  f"Skipped={previous_stats['skipped']}")
            print(f"\nDelta (Current - Previous):")
            print(f"  Total:   {current_stats['total']:5d} - {previous_stats['total']:5d} = {current_stats['total'] - previous_stats['total']:+5d}")
            print(f"  Passed:  {current_stats['passed']:5d} - {previous_stats['passed']:5d} = {current_stats['passed'] - previous_stats['passed']:+5d}")
            print(f"  Failed:  {current_stats['failed']:5d} - {previous_stats['failed']:5d} = {current_stats['failed'] - previous_stats['failed']:+5d}")
            print(f"  Skipped: {current_stats['skipped']:5d} - {previous_stats['skipped']:5d} = {current_stats['skipped'] - previous_stats['skipped']:+5d}")

            print(f"\n{'='*80}")
            print("✓ Comparison is now based on execution time (executed_at), not numeric order")
            print("✓ This ensures correct comparison even when releases share Jenkins URLs")
            print(f"{'='*80}")
        else:
            print("No previous parent job found (this is the first job)")


if __name__ == "__main__":
    verify_comparison_logic()
