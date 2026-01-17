"""
Testcase metadata service for importing and managing test case priority data.

This service imports test case metadata from the master CSV file
(data/testcase_list/hapy_automated.csv) into the database and backfills
priority information into existing test results.
"""
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert

from app.models.db_models import TestcaseMetadata, TestResult, AppSettings

logger = logging.getLogger(__name__)

# CSV file location
CSV_PATH = Path("data/testcase_list/hapy_automated.csv")


def get_import_status(db: Session) -> Optional[Dict[str, Any]]:
    """
    Get the status of the most recent import.

    Args:
        db: Database session

    Returns:
        Dictionary with import status or None if never imported
    """
    # Check for last import timestamp
    setting = db.query(AppSettings).filter(
        AppSettings.key == 'testcase_metadata_last_import'
    ).first()

    if not setting:
        return None

    # Get total count of metadata records
    total_records = db.query(TestcaseMetadata).count()

    # Get count of test results with priority assigned
    priority_assigned = db.query(TestResult).filter(
        TestResult.priority.isnot(None)
    ).count()

    return {
        'last_import': setting.value,
        'total_metadata_records': total_records,
        'test_results_with_priority': priority_assigned
    }


def import_testcase_metadata(db: Session) -> Dict[str, Any]:
    """
    Import testcase metadata from CSV file into database.

    This function:
    1. Reads the CSV file with pandas
    2. Filters out rows without testcase_name (non-automated tests)
    3. Bulk upserts into TestcaseMetadata table
    4. Backfills priority into TestResult table via SQL UPDATE
    5. Updates import status

    Args:
        db: Database session

    Returns:
        Dictionary with import statistics

    Raises:
        FileNotFoundError: If CSV file doesn't exist
        Exception: For other import errors
    """
    logger.info(f"Starting testcase metadata import from {CSV_PATH}")

    # Check if CSV exists
    if not CSV_PATH.exists():
        error_msg = f"CSV file not found: {CSV_PATH}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    try:
        # 1. Read CSV with pandas
        logger.info("Reading CSV file...")
        df = pd.read_csv(CSV_PATH)
        logger.info(f"Read {len(df)} total rows from CSV")

        # 2. Filter for automated tests with testcase_name
        # Skip rows where testcase_name is NaN/empty
        df_filtered = df[df['testcase_name'].notna() & (df['testcase_name'] != '')]
        logger.info(f"Filtered to {len(df_filtered)} rows with testcase_name")

        # Optional: Further filter for only "Hapy Automated" tests
        # Uncomment if you want to exclude manual tests
        # df_filtered = df_filtered[df_filtered['automation_status'] == 'Hapy Automated']
        # logger.info(f"Filtered to {len(df_filtered)} Hapy Automated tests")

        # 3. Prepare records for bulk insert
        logger.info("Preparing records for database insert...")
        metadata_records = []

        for _, row in df_filtered.iterrows():
            metadata_records.append({
                'testcase_name': str(row['testcase_name']).strip(),
                'test_case_id': str(row['test_case_id']) if pd.notna(row.get('test_case_id')) else None,
                'priority': str(row['priority']) if pd.notna(row.get('priority')) else None,
                'testrail_id': str(row['testrail_id']) if pd.notna(row.get('testrail_id')) else None,
                'component': str(row['component']) if pd.notna(row.get('component')) else None,
                'automation_status': str(row['automation_status']) if pd.notna(row.get('automation_status')) else None,
            })

        logger.info(f"Prepared {len(metadata_records)} records")

        # 4. Bulk upsert into TestcaseMetadata
        # Using INSERT OR REPLACE for SQLite
        logger.info("Upserting records into testcase_metadata table...")

        # For SQLite, we need to handle upserts specially
        # Delete existing records and insert new ones (simpler than ON CONFLICT UPDATE)
        db.execute(text("DELETE FROM testcase_metadata"))

        # Bulk insert in batches of 1000
        batch_size = 1000
        inserted_count = 0

        for i in range(0, len(metadata_records), batch_size):
            batch = metadata_records[i:i + batch_size]
            db.bulk_insert_mappings(TestcaseMetadata, batch)
            inserted_count += len(batch)
            logger.info(f"Inserted {inserted_count}/{len(metadata_records)} records")

        db.commit()
        logger.info(f"Successfully upserted {len(metadata_records)} metadata records")

        # 5. Backfill priority into TestResult table
        logger.info("Backfilling priority into test_results table...")

        # Use SQL UPDATE with subquery for efficiency
        update_sql = text("""
            UPDATE test_results
            SET priority = (
                SELECT priority
                FROM testcase_metadata
                WHERE testcase_metadata.testcase_name = test_results.test_name
            )
            WHERE EXISTS (
                SELECT 1
                FROM testcase_metadata
                WHERE testcase_metadata.testcase_name = test_results.test_name
            )
        """)

        result = db.execute(update_sql)
        update_count = result.rowcount
        db.commit()

        logger.info(f"Updated priority for {update_count} test results")

        # 6. Update import status
        now_iso = datetime.now(timezone.utc).isoformat()

        # Upsert import status
        setting = db.query(AppSettings).filter(
            AppSettings.key == 'testcase_metadata_last_import'
        ).first()

        if setting:
            setting.value = now_iso
            setting.updated_at = datetime.now(timezone.utc)
        else:
            setting = AppSettings(
                key='testcase_metadata_last_import',
                value=now_iso,
                description='Timestamp of last testcase metadata CSV import'
            )
            db.add(setting)

        db.commit()
        logger.info("Updated import status")

        # Return statistics
        stats = {
            'success': True,
            'metadata_rows_imported': len(metadata_records),
            'test_results_updated': update_count,
            'import_timestamp': now_iso,
            'csv_total_rows': len(df),
            'csv_filtered_rows': len(df_filtered)
        }

        logger.info(f"Import completed successfully: {stats}")
        return stats

    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error during import: {str(e)}", exc_info=True)
        db.rollback()
        raise Exception(f"Import failed: {str(e)}")


def get_testcase_metadata_by_name(db: Session, testcase_name: str) -> Optional[TestcaseMetadata]:
    """
    Get metadata for a specific test case by name.

    Args:
        db: Database session
        testcase_name: Test case name to look up

    Returns:
        TestcaseMetadata object or None if not found
    """
    return db.query(TestcaseMetadata).filter(
        TestcaseMetadata.testcase_name == testcase_name
    ).first()


def search_testcase_metadata(
    db: Session,
    query: str,
    limit: int = 50
) -> list[TestcaseMetadata]:
    """
    Search testcase metadata by test_case_id, testcase_name, or testrail_id.

    Args:
        db: Database session
        query: Search query string
        limit: Maximum number of results

    Returns:
        List of matching TestcaseMetadata objects
    """
    return db.query(TestcaseMetadata).filter(
        (TestcaseMetadata.test_case_id.ilike(f'%{query}%')) |
        (TestcaseMetadata.testcase_name.ilike(f'%{query}%')) |
        (TestcaseMetadata.testrail_id.ilike(f'%{query}%'))
    ).limit(limit).all()


def get_priority_statistics(db: Session) -> Dict[str, int]:
    """
    Get statistics on priority distribution in metadata.

    Args:
        db: Database session

    Returns:
        Dictionary mapping priority to count
    """
    from sqlalchemy import func

    results = db.query(
        TestcaseMetadata.priority,
        func.count(TestcaseMetadata.id).label('count')
    ).group_by(TestcaseMetadata.priority).all()

    stats = {row.priority or 'UNKNOWN': row.count for row in results}
    return stats
