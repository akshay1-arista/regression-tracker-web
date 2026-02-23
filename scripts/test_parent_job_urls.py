#!/usr/bin/env python3
"""
Test that parent job URLs are correctly extracted from actual job records.

This verifies that:
- 6.4 jobs 73, 55 use QA_Release_7.0 URL (new shared URL)
- 6.1 job 64 uses QA_Release_7.0 URL (new shared URL)
- Older 6.4/6.1 jobs still use release-specific URLs (if applicable)
"""
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db_context
from app.services import data_service


def test_parent_job_urls():
    """Test parent job URL extraction for different releases."""

    test_cases = [
        ("7.0", "74"),
        ("7.0", "71"),
        ("6.4", "73"),
        ("6.4", "55"),
        ("6.1", "64"),
    ]

    with get_db_context() as db:
        print("Testing Parent Job URL Extraction")
        print("=" * 100)

        for release_name, parent_job_id in test_cases:
            print(f"\nRelease: {release_name}, Parent Job ID: {parent_job_id}")
            print("-" * 100)

            # Get parent job URL using the new helper function
            parent_job_url = data_service.get_parent_job_url(db, release_name, parent_job_id)

            # Get aggregated stats (which also includes parent_job_url)
            try:
                stats = data_service.get_aggregated_stats_for_parent_job(
                    db, release_name, parent_job_id
                )
                stats_url = stats.get('parent_job_url')
            except Exception as e:
                stats_url = f"ERROR: {e}"

            # Get actual jobs to show what URL they have
            jobs = data_service.get_jobs_by_parent_job_id(db, release_name, parent_job_id)
            if jobs:
                first_job_url = jobs[0].jenkins_url
                print(f"  First job's jenkins_url: {first_job_url}")
            else:
                print(f"  No jobs found for this parent_job_id")
                first_job_url = None

            print(f"  Helper function URL:     {parent_job_url}")
            print(f"  Stats function URL:      {stats_url}")

            # Verify URL correctness
            if parent_job_url:
                if release_name in ["6.4", "6.1"]:
                    # For 6.4 and 6.1, newer jobs should use 7.0 URL
                    if int(parent_job_id) >= 55:  # Adjust threshold as needed
                        if "QA_Release_7.0" in parent_job_url:
                            print(f"  ✓ Correctly using QA_Release_7.0 URL for newer {release_name} job")
                        else:
                            print(f"  ✗ ERROR: Should use QA_Release_7.0 URL, got: {parent_job_url}")
                    else:
                        # Older jobs might use release-specific URLs
                        if f"QA_Release_{release_name}" in parent_job_url:
                            print(f"  ✓ Using release-specific URL for older {release_name} job")
                        elif "QA_Release_7.0" in parent_job_url:
                            print(f"  ⚠ Using QA_Release_7.0 URL (might be correct if migrated)")
                elif release_name == "7.0":
                    if "QA_Release_7.0" in parent_job_url:
                        print(f"  ✓ Correctly using QA_Release_7.0 URL")
                    else:
                        print(f"  ✗ ERROR: Should use QA_Release_7.0 URL, got: {parent_job_url}")
            else:
                print(f"  ✗ ERROR: No parent_job_url generated")

        print(f"\n{'='*100}")
        print("Test complete!")
        print(f"{'='*100}")


if __name__ == "__main__":
    test_parent_job_urls()
