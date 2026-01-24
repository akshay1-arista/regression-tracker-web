#!/usr/bin/env python3
"""
Import topology metadata from dataplane_test_topologies.csv into testcase_metadata table.

This script:
1. Reads dataplane_test_topologies.csv (10,810 test cases)
2. Imports/updates testcase_metadata with 5 new fields (module, test_state, test_class_name, test_path, topology)
3. Uses conditional priority update (only updates if current value is NULL)
4. Always updates topology and other new fields
5. Optionally backfills topology_metadata in test_results table
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.db_models import TestcaseMetadata, TestResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Valid priority values
VALID_PRIORITIES = {'P0', 'P1', 'P2', 'P3'}

# CSV to Database column mapping
CSV_TO_DB_MAPPING = {
    'module': 'module',                        # Direct mapping
    'test_class_name': 'test_class_name',      # Direct mapping
    'testcase_name': 'testcase_name',          # Direct mapping
    'topology': 'topology',                    # Direct mapping
    'path': 'test_path',                       # CSV 'path' → DB 'test_path'
    'test_state': 'test_state',                # Direct mapping
    'testcase_id': 'test_case_id',            # CSV 'testcase_id' → DB 'test_case_id'
    'priority': 'priority'                     # Direct mapping
}


def validate_priority(priority_val: Any, testcase_name: str) -> Optional[str]:
    """
    Validate and normalize priority value.

    Args:
        priority_val: Raw priority value from CSV
        testcase_name: Test case name for logging

    Returns:
        Normalized priority string or None if invalid/missing
    """
    if pd.isna(priority_val) or priority_val == '':
        return None  # Empty priority (~194 cases in CSV)

    priority_str = str(priority_val).strip()

    if priority_str not in VALID_PRIORITIES:
        logger.warning(
            f"Invalid priority '{priority_str}' for test '{testcase_name}'. "
            f"Expected one of {VALID_PRIORITIES}. Setting to NULL."
        )
        return None

    return priority_str


def map_csv_record_to_db(csv_row: pd.Series) -> Dict[str, Any]:
    """
    Map CSV row to database record using column mapping.

    Args:
        csv_row: Pandas Series from CSV

    Returns:
        Dictionary with database column names
    """
    testcase_name = str(csv_row['testcase_name']).strip()

    # Map columns
    db_record = {
        'testcase_name': testcase_name,
        'test_case_id': str(csv_row['testcase_id']).strip() if pd.notna(csv_row.get('testcase_id')) else None,
        'priority': validate_priority(csv_row.get('priority'), testcase_name),
        'module': str(csv_row['module']).strip() if pd.notna(csv_row.get('module')) else None,
        'test_state': str(csv_row['test_state']).strip() if pd.notna(csv_row.get('test_state')) else None,
        'test_class_name': str(csv_row['test_class_name']).strip() if pd.notna(csv_row.get('test_class_name')) else None,
        'test_path': str(csv_row['path']).strip() if pd.notna(csv_row.get('path')) else None,
        'topology': str(csv_row['topology']).strip() if pd.notna(csv_row.get('topology')) else None
    }

    return db_record


def import_record(db: Session, record: Dict[str, Any], dry_run: bool = False) -> str:
    """
    Import or update a single test case record with conditional priority logic.

    Args:
        db: Database session
        record: Database record dictionary
        dry_run: If True, don't commit changes

    Returns:
        Action taken: 'inserted', 'updated', or 'skipped'
    """
    existing = db.query(TestcaseMetadata).filter(
        TestcaseMetadata.testcase_name == record['testcase_name']
    ).first()

    if existing:
        # EXISTING RECORD - Selective updates

        # Always update these fields (unconditional)
        existing.topology = record['topology']
        existing.module = record['module']
        existing.test_state = record['test_state']
        existing.test_class_name = record['test_class_name']
        existing.test_path = record['test_path']
        existing.test_case_id = record['test_case_id']
        existing.updated_at = datetime.now(timezone.utc)

        # Conditionally update priority (only if NULL)
        if existing.priority is None and record['priority'] is not None:
            existing.priority = record['priority']
            logger.debug(f"Updated priority: NULL → {record['priority']} for {record['testcase_name']}")
        elif existing.priority is not None:
            logger.debug(f"Preserved existing priority: {existing.priority} for {record['testcase_name']}")

        if not dry_run:
            # Changes will be committed in batch
            pass

        return 'updated'
    else:
        # NEW RECORD - Insert all fields
        new_metadata = TestcaseMetadata(
            testcase_name=record['testcase_name'],
            test_case_id=record['test_case_id'],
            priority=record['priority'],  # Can be NULL
            module=record['module'],
            test_state=record['test_state'],
            test_class_name=record['test_class_name'],
            test_path=record['test_path'],
            topology=record['topology'],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        if not dry_run:
            db.add(new_metadata)

        return 'inserted'


def import_from_csv(
    db: Session,
    csv_path: Path,
    dry_run: bool = False,
    batch_size: int = 1000
) -> Dict[str, int]:
    """
    Import test case metadata from CSV file.

    Args:
        db: Database session
        csv_path: Path to CSV file
        dry_run: If True, preview changes without committing
        batch_size: Number of records to process per batch

    Returns:
        Dictionary with import statistics
    """
    logger.info(f"Reading CSV from {csv_path}")

    # Read CSV with Windows line ending handling
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except UnicodeDecodeError:
        logger.warning("UTF-8 decoding failed, trying latin-1...")
        df = pd.read_csv(csv_path, encoding='latin-1')

    logger.info(f"Read {len(df)} total rows from CSV")

    # Filter for rows with testcase_name
    df_filtered = df[df['testcase_name'].notna() & (df['testcase_name'] != '')]
    logger.info(f"Filtered to {len(df_filtered)} rows with testcase_name")

    # Statistics counters
    stats = {
        'inserted': 0,
        'updated': 0,
        'skipped': 0,
        'invalid_priority': 0,
        'priority_preserved': 0,
        'priority_updated_from_null': 0
    }

    # Process in batches
    for i in range(0, len(df_filtered), batch_size):
        batch = df_filtered.iloc[i:i + batch_size]

        for _, row in batch.iterrows():
            try:
                # Map CSV to DB record
                db_record = map_csv_record_to_db(row)

                # Track priority validation
                if pd.notna(row.get('priority')) and db_record['priority'] is None:
                    stats['invalid_priority'] += 1

                # Import record
                action = import_record(db, db_record, dry_run)
                stats[action] += 1

                # Track priority updates
                if action == 'updated':
                    existing = db.query(TestcaseMetadata).filter(
                        TestcaseMetadata.testcase_name == db_record['testcase_name']
                    ).first()
                    if existing:
                        if existing.priority == db_record['priority'] and db_record['priority'] is not None:
                            stats['priority_updated_from_null'] += 1
                        elif existing.priority is not None and existing.priority != db_record['priority']:
                            stats['priority_preserved'] += 1

            except Exception as e:
                logger.error(f"Error processing row {row.get('testcase_name')}: {e}")
                stats['skipped'] += 1

        # Commit batch
        if not dry_run:
            db.commit()

        # Progress update
        progress = min(i + batch_size, len(df_filtered))
        logger.info(f"Progress: {progress}/{len(df_filtered)} ({progress/len(df_filtered)*100:.1f}%)")

    logger.info(f"Import completed: {stats}")
    return stats


def backfill_test_results_topology(db: Session, dry_run: bool = False) -> int:
    """
    Backfill topology_metadata in test_results from testcase_metadata.

    Args:
        db: Database session
        dry_run: If True, preview changes without committing

    Returns:
        Number of test results updated
    """
    logger.info("Starting test_results topology_metadata backfill...")

    # Get all unique test names from test_results
    test_names_query = db.query(TestResult.test_name).distinct()
    test_names = [name[0] for name in test_names_query.all()]
    logger.info(f"Found {len(test_names)} unique test names in test_results")

    # Build lookup from metadata
    metadata_records = db.query(
        TestcaseMetadata.testcase_name,
        TestcaseMetadata.topology
    ).filter(
        TestcaseMetadata.testcase_name.in_(test_names),
        TestcaseMetadata.topology.isnot(None)
    ).all()

    topology_lookup = {r.testcase_name: r.topology for r in metadata_records}
    logger.info(f"Found topology for {len(topology_lookup)} test cases in metadata")

    # Update in batches
    batch_size = 5000
    updated_count = 0

    for offset in range(0, len(test_names), batch_size):
        batch_names = test_names[offset:offset + batch_size]

        for test_name in batch_names:
            topology = topology_lookup.get(test_name)
            if topology:
                if not dry_run:
                    db.query(TestResult).filter(
                        TestResult.test_name == test_name
                    ).update({TestResult.topology_metadata: topology})
                updated_count += 1

        if not dry_run:
            db.commit()

        progress = min(offset + batch_size, len(test_names))
        logger.info(f"Backfill progress: {progress}/{len(test_names)} ({progress/len(test_names)*100:.1f}%)")

    logger.info(f"Updated topology_metadata for {updated_count} test results")
    return updated_count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Import topology metadata from dataplane_test_topologies.csv'
    )
    parser.add_argument(
        '--csv-path',
        type=Path,
        default=Path('data/testcase_list/dataplane_test_topologies.csv'),
        help='Path to CSV file (default: data/testcase_list/dataplane_test_topologies.csv)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without committing to database'
    )
    parser.add_argument(
        '--skip-backfill-results',
        action='store_true',
        help='Skip backfilling test_results.topology_metadata (default: skip)'
    )
    parser.add_argument(
        '--only-backfill-results',
        action='store_true',
        help='Only backfill test_results, skip CSV import'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing (default: 1000)'
    )
    parser.add_argument(
        '--database',
        type=Path,
        default=Path('data/regression_tracker.db'),
        help='Path to database file (default: data/regression_tracker.db)'
    )

    args = parser.parse_args()

    # Validate CSV exists
    if not args.only_backfill_results:
        if not args.csv_path.exists():
            logger.error(f"CSV file not found: {args.csv_path}")
            sys.exit(1)

    # Validate database exists
    if not args.database.exists():
        logger.error(f"Database file not found: {args.database}")
        sys.exit(1)

    # Connect to database
    engine = create_engine(f"sqlite:///{args.database}")
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        if args.dry_run:
            logger.info("=== DRY RUN MODE - No changes will be committed ===")

        # Import from CSV
        if not args.only_backfill_results:
            logger.info("=" * 60)
            logger.info("PHASE 1: Import from CSV")
            logger.info("=" * 60)

            stats = import_from_csv(
                db=db,
                csv_path=args.csv_path,
                dry_run=args.dry_run,
                batch_size=args.batch_size
            )

            logger.info("")
            logger.info("=" * 60)
            logger.info("IMPORT SUMMARY")
            logger.info("=" * 60)
            logger.info(f"New records inserted:        {stats['inserted']}")
            logger.info(f"Existing records updated:    {stats['updated']}")
            logger.info(f"Records skipped (errors):    {stats['skipped']}")
            logger.info(f"Invalid priorities (→ NULL): {stats['invalid_priority']}")
            logger.info(f"Priorities preserved:        {stats['priority_preserved']}")
            logger.info(f"Priorities updated (was NULL): {stats['priority_updated_from_null']}")
            logger.info("=" * 60)

        # Backfill test_results
        if args.only_backfill_results or not args.skip_backfill_results:
            logger.info("")
            logger.info("=" * 60)
            logger.info("PHASE 2: Backfill test_results.topology_metadata")
            logger.info("=" * 60)

            updated_count = backfill_test_results_topology(db=db, dry_run=args.dry_run)

            logger.info("")
            logger.info("=" * 60)
            logger.info("BACKFILL SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Test results updated: {updated_count}")
            logger.info("=" * 60)

        if args.dry_run:
            logger.info("")
            logger.info("=== DRY RUN COMPLETED - No changes were made ===")
            db.rollback()
        else:
            logger.info("")
            logger.info("✓ Import completed successfully!")

    except Exception as e:
        logger.error(f"Import failed: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
