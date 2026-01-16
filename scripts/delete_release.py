#!/usr/bin/env python3
"""
Delete a release and all associated data from the database.

Usage:
    python delete_release.py <release_name>

Example:
    python delete_release.py 7.0.0.0
"""
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import get_db_context
from app.models.db_models import Release, Module, Job, TestResult


def create_backup(db_path: str) -> str:
    """Create a backup of the database before deletion."""
    backup_dir = Path(__file__).parent / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"regression_tracker_backup_{timestamp}.db"

    shutil.copy2(db_path, backup_path)
    return str(backup_path)


def get_deletion_stats(db, release_name: str):
    """Get statistics about what will be deleted."""
    release = db.query(Release).filter(Release.name == release_name).first()

    if not release:
        return None

    # Count modules
    modules = db.query(Module).filter(Module.release_id == release.id).all()
    module_count = len(modules)

    # Count jobs
    jobs = db.query(Job).join(Module).filter(Module.release_id == release.id).all()
    job_count = len(jobs)

    # Count test results
    test_results_count = db.query(TestResult).join(Job).join(Module).filter(
        Module.release_id == release.id
    ).count()

    return {
        'release': release,
        'modules': module_count,
        'jobs': job_count,
        'test_results': test_results_count,
        'module_names': [m.name for m in modules]
    }


def delete_release(release_name: str, confirm: bool = True):
    """Delete a release and all associated data."""

    db_path = Path(__file__).parent / "data" / "regression_tracker.db"

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return False

    with get_db_context() as db:
        # Get deletion stats
        stats = get_deletion_stats(db, release_name)

        if not stats:
            print(f"❌ Release '{release_name}' not found in database")
            return False

        # Display what will be deleted
        print("\n" + "="*60)
        print(f"📊 DELETION SUMMARY for Release: {release_name}")
        print("="*60)
        print(f"  Modules:       {stats['modules']} ({', '.join(stats['module_names'])})")
        print(f"  Jobs:          {stats['jobs']}")
        print(f"  Test Results:  {stats['test_results']}")
        print("="*60)
        print("\n⚠️  This action will CASCADE DELETE all associated data!")
        print("   (modules, jobs, test_results, MAC addresses, polling logs)\n")

        # Confirm deletion
        if confirm:
            response = input("❓ Are you sure you want to delete this release? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("❌ Deletion cancelled")
                return False

        # Create backup
        print("\n📦 Creating database backup...")
        backup_path = create_backup(db_path)
        print(f"✅ Backup created: {backup_path}")

        # Delete the release (CASCADE will delete modules, jobs, test_results)
        print(f"\n🗑️  Deleting release '{release_name}'...")
        release = stats['release']
        db.delete(release)
        db.commit()

        print(f"✅ Successfully deleted release '{release_name}' and all associated data")
        print(f"   Backup available at: {backup_path}\n")

        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python delete_release.py <release_name>")
        print("Example: python delete_release.py 7.0.0.0")
        sys.exit(1)

    release_name = sys.argv[1]

    # Check for --yes flag to skip confirmation
    confirm = '--yes' not in sys.argv

    success = delete_release(release_name, confirm=confirm)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
