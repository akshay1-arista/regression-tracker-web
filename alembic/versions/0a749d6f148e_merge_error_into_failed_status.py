"""merge_error_into_failed_status

Revision ID: 0a749d6f148e
Revises: e145675f4e76
Create Date: 2026-01-22 00:46:34.131873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a749d6f148e'
down_revision: Union[str, Sequence[str], None] = 'e145675f4e76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge ERROR status into FAILED status.

    This migration:
    1. Converts all test_results with status='ERROR' to status='FAILED'
    2. Merges error counts into failed counts in jobs table
    3. Drops the error column from jobs table

    Note: TestStatusEnum.ERROR is kept in the enum for parser compatibility,
    but all ERROR statuses are converted to FAILED on import.
    """
    # Step 1: Update test_results: ERROR → FAILED
    op.execute("""
        UPDATE test_results
        SET status = 'FAILED'
        WHERE status = 'ERROR'
    """)

    # Step 2: Update jobs: merge error count into failed
    op.execute("""
        UPDATE jobs
        SET failed = failed + COALESCE(error, 0)
    """)

    # Step 3: Drop the error column (hybrid approach)
    op.drop_column('jobs', 'error')


def downgrade() -> None:
    """Downgrade schema (partial - cannot restore ERROR vs FAILED distinction).

    This downgrade:
    1. Re-adds the error column to jobs table
    2. Initializes error to 0 for all records

    Note: Cannot restore the original ERROR status in test_results (data loss).
    All previously ERROR tests remain as FAILED.
    """
    # Step 1: Re-add error column
    op.add_column('jobs', sa.Column('error', sa.Integer(), nullable=True))

    # Step 2: Set error to 0 for all records (cannot restore original split)
    op.execute("UPDATE jobs SET error = 0")

    # Cannot restore ERROR status in test_results (data loss)
    # All previously ERROR tests remain as FAILED
