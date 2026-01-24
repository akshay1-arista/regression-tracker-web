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
import os

import pandas as pd
from sqlalchemy import text, func, case
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert

from app.models.db_models import TestcaseMetadata, TestResult, AppSettings
from app.utils.test_name_utils import normalize_test_name

logger = logging.getLogger(__name__)

# Valid priority values
VALID_PRIORITIES = {'P0', 'P1', 'P2', 'P3'}

# Required CSV columns
REQUIRED_CSV_COLUMNS = {
    'testcase_name',
    'test_case_id',
    'priority',
    'testrail_id',
    'component',
    'automation_status'
}

# Default CSV file location (can be overridden via environment variable)
DEFAULT_CSV_PATH = "data/testcase_list/hapy_automated.csv"


def _normalize_test_name_sql(test_name_column):
    """
    Create SQL expression to normalize parameterized test names.

    Extracts base name from parameterized tests:
    - test_foo[param] -> test_foo
    - test_bar -> test_bar (unchanged)

    Args:
        test_name_column: SQLAlchemy column reference (e.g., TestResult.test_name)

    Returns:
        SQLAlchemy CASE expression that normalizes test names
    """
    return case(
        (func.instr(test_name_column, '[') > 0,
         func.substr(test_name_column, 1, func.instr(test_name_column, '[') - 1)),
        else_=test_name_column
    )


def _get_csv_path() -> Path:
    """
    Get CSV file path from environment or use default.

    Returns:
        Path object for CSV file
    """
    csv_path_str = os.environ.get('TESTCASE_CSV_PATH', DEFAULT_CSV_PATH)
    return Path(csv_path_str)


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


def _validate_csv_structure(df: pd.DataFrame) -> None:
    """
    Validate that CSV has all required columns.

    Args:
        df: Pandas DataFrame from CSV

    Raises:
        ValueError: If required columns are missing
    """
    csv_columns = set(df.columns)
    missing_columns = REQUIRED_CSV_COLUMNS - csv_columns

    if missing_columns:
        raise ValueError(
            f"CSV missing required columns: {', '.join(sorted(missing_columns))}. "
            f"Found columns: {', '.join(sorted(csv_columns))}"
        )

    logger.info(f"CSV validation passed. Found all {len(REQUIRED_CSV_COLUMNS)} required columns")


def _validate_and_normalize_priority(priority_val: Any, testcase_name: str) -> Optional[str]:
    """
    Validate and normalize priority value.

    Args:
        priority_val: Raw priority value from CSV
        testcase_name: Test case name for logging

    Returns:
        Normalized priority string or None if invalid/missing
    """
    if pd.isna(priority_val) or priority_val == '':
        return None

    priority_str = str(priority_val).strip()

    if priority_str not in VALID_PRIORITIES:
        logger.warning(
            f"Invalid priority '{priority_str}' for test '{testcase_name}'. "
            f"Expected one of {VALID_PRIORITIES}. Setting to NULL."
        )
        return None

    return priority_str


def import_testcase_metadata(
    db: Session,
    csv_path: Optional[Path] = None,
    job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Import testcase metadata from CSV file into database.

    This function:
    1. Reads and validates the CSV file
    2. Filters out rows without testcase_name (non-automated tests)
    3. Validates priority values
    4. Bulk upserts into TestcaseMetadata table (proper ON CONFLICT handling)
    5. Backfills priority into TestResult table in batches
    6. Updates import status

    Args:
        db: Database session
        csv_path: Optional custom CSV path (defaults to configured path)
        job_id: Optional job ID for background task tracking

    Returns:
        Dictionary with import statistics

    Raises:
        FileNotFoundError: If CSV file doesn't exist
        ValueError: If CSV structure is invalid
    """
    csv_path = csv_path or _get_csv_path()
    log_prefix = f"[Job {job_id}] " if job_id else ""

    logger.info(f"{log_prefix}Starting testcase metadata import from {csv_path}")

    # Check if CSV exists
    if not csv_path.exists():
        error_msg = f"CSV file not found: {csv_path}"
        logger.error(f"{log_prefix}{error_msg}")
        raise FileNotFoundError(error_msg)

    # 1. Read CSV with pandas
    logger.info(f"{log_prefix}Reading CSV file...")
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except UnicodeDecodeError:
        # Fallback to latin-1 if UTF-8 fails
        logger.warning(f"{log_prefix}UTF-8 decoding failed, trying latin-1...")
        df = pd.read_csv(csv_path, encoding='latin-1')

    logger.info(f"{log_prefix}Read {len(df)} total rows from CSV")

    # Validate CSV structure
    try:
        _validate_csv_structure(df)
    except ValueError as e:
        logger.error(f"{log_prefix}CSV validation failed: {str(e)}")
        raise

    # 2. Filter for automated tests with testcase_name
    df_filtered = df[df['testcase_name'].notna() & (df['testcase_name'] != '')]
    logger.info(f"{log_prefix}Filtered to {len(df_filtered)} rows with testcase_name")

    # 3. Prepare records for bulk insert with validation
    logger.info(f"{log_prefix}Preparing and validating records...")
    metadata_records = []
    invalid_priority_count = 0

    for _, row in df_filtered.iterrows():
        testcase_name = str(row['testcase_name']).strip()

        # Validate and normalize priority
        priority_val = _validate_and_normalize_priority(row.get('priority'), testcase_name)
        if pd.notna(row.get('priority')) and priority_val is None:
            invalid_priority_count += 1

        metadata_records.append({
            'testcase_name': testcase_name,
            'test_case_id': str(row['test_case_id']).strip() if pd.notna(row.get('test_case_id')) else None,
            'priority': priority_val,
            'testrail_id': str(row['testrail_id']).strip() if pd.notna(row.get('testrail_id')) else None,
            'component': str(row['component']).strip() if pd.notna(row.get('component')) else None,
            'automation_status': str(row['automation_status']).strip() if pd.notna(row.get('automation_status')) else None,
            'updated_at': datetime.now(timezone.utc)
        })

    logger.info(f"{log_prefix}Prepared {len(metadata_records)} records")
    if invalid_priority_count > 0:
        logger.warning(f"{log_prefix}Found {invalid_priority_count} invalid priority values (set to NULL)")

    # 4. Bulk upsert into TestcaseMetadata using proper ON CONFLICT
    logger.info(f"{log_prefix}Upserting records into testcase_metadata table...")

    inserted_count = 0
    updated_count = 0
    batch_size = 1000

    for i in range(0, len(metadata_records), batch_size):
        batch = metadata_records[i:i + batch_size]

        # Use SQLite's INSERT OR REPLACE (proper UPSERT)
        # For each record in batch, use INSERT ... ON CONFLICT DO UPDATE
        for record in batch:
            stmt = insert(TestcaseMetadata).values(
                testcase_name=record['testcase_name'],
                test_case_id=record['test_case_id'],
                priority=record['priority'],
                testrail_id=record['testrail_id'],
                component=record['component'],
                automation_status=record['automation_status'],
                created_at=datetime.now(timezone.utc),
                updated_at=record['updated_at']
            )

            # On conflict (unique testcase_name), update all fields
            stmt = stmt.on_conflict_do_update(
                index_elements=['testcase_name'],
                set_={
                    'test_case_id': stmt.excluded.test_case_id,
                    'priority': stmt.excluded.priority,
                    'testrail_id': stmt.excluded.testrail_id,
                    'component': stmt.excluded.component,
                    'automation_status': stmt.excluded.automation_status,
                    'updated_at': stmt.excluded.updated_at
                }
            )

            db.execute(stmt)

        db.commit()
        inserted_count += len(batch)
        logger.info(f"{log_prefix}Processed {inserted_count}/{len(metadata_records)} records")

    logger.info(f"{log_prefix}Successfully upserted {len(metadata_records)} metadata records")

    # 5. Backfill priority into TestResult table in batches
    # Use SQL-side normalization with bulk updates for optimal performance
    logger.info(f"{log_prefix}Backfilling priority into test_results table...")

    # Get all testcase names from metadata for batching
    testcase_names = [record['testcase_name'] for record in metadata_records]
    update_batch_size = 5000
    total_updated = 0

    # Use SQL-side normalization to handle parameterized tests
    normalized_test_name = _normalize_test_name_sql(TestResult.test_name)

    for i in range(0, len(testcase_names), update_batch_size):
        batch_names = testcase_names[i:i + update_batch_size]

        # Update with batched names using SQL-side normalization
        # This allows test_foo[param] to match test_foo in metadata
        update_sql = text("""
            UPDATE test_results
            SET priority = (
                SELECT priority
                FROM testcase_metadata
                WHERE testcase_metadata.testcase_name =
                    CASE
                        WHEN INSTR(test_results.test_name, '[') > 0
                        THEN SUBSTR(test_results.test_name, 1, INSTR(test_results.test_name, '[') - 1)
                        ELSE test_results.test_name
                    END
            )
            WHERE CASE
                    WHEN INSTR(test_results.test_name, '[') > 0
                    THEN SUBSTR(test_results.test_name, 1, INSTR(test_results.test_name, '[') - 1)
                    ELSE test_results.test_name
                  END IN :names
            AND EXISTS (
                SELECT 1
                FROM testcase_metadata
                WHERE testcase_metadata.testcase_name =
                    CASE
                        WHEN INSTR(test_results.test_name, '[') > 0
                        THEN SUBSTR(test_results.test_name, 1, INSTR(test_results.test_name, '[') - 1)
                        ELSE test_results.test_name
                    END
            )
        """)

        result = db.execute(update_sql, {"names": tuple(batch_names)})
        batch_updated = result.rowcount
        total_updated += batch_updated
        db.commit()

        logger.info(
            f"{log_prefix}Backfill progress: {i + len(batch_names)}/{len(testcase_names)} names processed, "
            f"{total_updated} test results updated so far"
        )

    logger.info(f"{log_prefix}Updated priority for {total_updated} test results")

    # 6. Update import status
    now_iso = datetime.now(timezone.utc).isoformat()

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
    logger.info(f"{log_prefix}Updated import status")

    # Return statistics
    stats = {
        'success': True,
        'metadata_rows_imported': len(metadata_records),
        'test_results_updated': total_updated,
        'import_timestamp': now_iso,
        'csv_total_rows': len(df),
        'csv_filtered_rows': len(df_filtered),
        'invalid_priority_count': invalid_priority_count
    }

    logger.info(f"{log_prefix}Import completed successfully: {stats}")
    return stats


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
