#!/usr/bin/env python3
"""
Migration script to convert POLLING_INTERVAL_MINUTES to POLLING_INTERVAL_HOURS.

This script migrates the database setting from the old POLLING_INTERVAL_MINUTES
to the new POLLING_INTERVAL_HOURS format.

Usage:
    python scripts/migrate_polling_interval.py
"""
import sys
from pathlib import Path

# Add parent directory to path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from app.database import get_db_context
from app.models.db_models import AppSettings
import json


def migrate_polling_interval():
    """Migrate POLLING_INTERVAL_MINUTES to POLLING_INTERVAL_HOURS."""
    with get_db_context() as db:
        # Check if old setting exists
        old_setting = db.query(AppSettings).filter(
            AppSettings.key == 'POLLING_INTERVAL_MINUTES'
        ).first()

        # Check if new setting already exists
        new_setting = db.query(AppSettings).filter(
            AppSettings.key == 'POLLING_INTERVAL_HOURS'
        ).first()

        if not old_setting:
            print("✓ No POLLING_INTERVAL_MINUTES setting found, nothing to migrate")
            if new_setting:
                print(f"  POLLING_INTERVAL_HOURS is already set to {new_setting.value} hours")
            return

        if new_setting:
            print("⚠ Both POLLING_INTERVAL_MINUTES and POLLING_INTERVAL_HOURS exist")
            print(f"  POLLING_INTERVAL_MINUTES: {old_setting.value} minutes")
            print(f"  POLLING_INTERVAL_HOURS: {new_setting.value} hours")
            print("\n  Keeping POLLING_INTERVAL_HOURS (newer setting takes precedence)")
            print("  Deleting POLLING_INTERVAL_MINUTES...")
            db.delete(old_setting)
            db.commit()
            print("✓ Migration complete")
            return

        # Convert minutes to hours
        interval_minutes = json.loads(old_setting.value)
        interval_hours = interval_minutes / 60.0

        print(f"Migrating POLLING_INTERVAL_MINUTES ({interval_minutes} min) → POLLING_INTERVAL_HOURS ({interval_hours} h)")

        # Create new setting
        new_setting = AppSettings(
            key='POLLING_INTERVAL_HOURS',
            value=json.dumps(interval_hours),
            description=f'Jenkins polling interval in hours (migrated from {interval_minutes} minutes)'
        )
        db.add(new_setting)

        # Delete old setting
        db.delete(old_setting)

        db.commit()

        print("✓ Migration complete")
        print(f"  New setting: POLLING_INTERVAL_HOURS = {interval_hours} hours")
        print(f"  Old setting: POLLING_INTERVAL_MINUTES (deleted)")


if __name__ == '__main__':
    try:
        migrate_polling_interval()
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
