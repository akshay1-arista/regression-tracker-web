#!/usr/bin/env python3
"""
Sync last_processed_build in releases table with actual max builds in jobs table.

This script fixes the issue where last_processed_build is out of sync with
the actual jobs in the database, typically after manual imports or migrations.

Usage:
    python scripts/sync_last_processed_builds.py
"""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.db_models import Release, Module, Job
from sqlalchemy import func, cast, Integer


def sync_last_processed_builds():
    """Sync last_processed_build for all releases with actual max builds in database."""
    db = SessionLocal()
    try:
        releases = db.query(Release).all()

        if not releases:
            print("No releases found in database")
            return

        print("Syncing last_processed_build values...")
        print("-" * 60)

        updates_made = 0

        for release in releases:
            # Query max parent_job_id for this release
            # parent_job_id is stored as String, so we need to cast to Integer
            max_parent_job = db.query(
                func.max(cast(Job.parent_job_id, Integer))
            ).join(
                Module
            ).filter(
                Module.release_id == release.id
            ).scalar()

            old_value = release.last_processed_build or 0

            if max_parent_job is not None:
                if max_parent_job != old_value:
                    release.last_processed_build = max_parent_job
                    updates_made += 1
                    print(f"{release.name:15} {old_value:>6} → {max_parent_job:<6} (updated)")
                else:
                    print(f"{release.name:15} {old_value:>6}   (no change)")
            else:
                print(f"{release.name:15} {old_value:>6}   (no jobs found)")

        db.commit()

        print("-" * 60)
        print(f"Sync completed successfully")
        print(f"Releases processed: {len(releases)}")
        print(f"Updates made: {updates_made}")

    except Exception as e:
        db.rollback()
        print(f"Error during sync: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_last_processed_builds()
