#!/usr/bin/env python3
"""Test module breakdown comparison logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db_context
from app.services import data_service


def test_module_comparison():
    """Test that module breakdown includes comparison data."""

    with get_db_context() as db:
        release_name = "7.0"
        parent_job_id = "74"

        print(f"Testing module breakdown for Release {release_name}, Parent Job {parent_job_id}")
        print("=" * 80)

        # Get previous parent job
        prev_parent_job_id = data_service.get_previous_parent_job_id(db, release_name, parent_job_id)
        print(f"Previous parent job ID: {prev_parent_job_id}")

        # Get module breakdown with comparison
        breakdown = data_service.get_module_breakdown_for_parent_job(
            db, release_name, parent_job_id,
            include_comparison=True
        )

        print(f"\nTotal modules: {len(breakdown)}")

        if breakdown:
            first_module = breakdown[0]
            print(f"\nFirst module: {first_module['module_name']}")
            print(f"  Total: {first_module['total']}")
            print(f"  Passed: {first_module['passed']}")
            print(f"  Failed: {first_module['failed']}")
            print(f"  Has comparison: {'comparison' in first_module}")

            if 'comparison' in first_module and first_module['comparison']:
                comp = first_module['comparison']
                print(f"  Comparison data:")
                print(f"    Total delta: {comp['total_delta']}")
                print(f"    Previous total: {comp['previous']['total']}")
            elif 'comparison' in first_module:
                print(f"  Comparison is None (module didn't exist in previous run)")
            else:
                print(f"  No comparison field!")


if __name__ == "__main__":
    test_module_comparison()
