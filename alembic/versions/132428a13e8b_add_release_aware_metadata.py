"""add_release_aware_metadata

Revision ID: 132428a13e8b
Revises: 3a2f7fe9b5c2
Create Date: 2026-02-06 11:02:17.002048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = '132428a13e8b'
down_revision: Union[str, Sequence[str], None] = '3a2f7fe9b5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = reflection.Inspector.from_engine(conn)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    conn = op.get_bind()
    inspector = reflection.Inspector.from_engine(conn)
    # Get all indexes from all tables
    for table_name in inspector.get_table_names():
        indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
        if index_name in indexes:
            return True
    return False


def upgrade() -> None:
    """Upgrade schema."""
    # Add git_branch column to releases table
    if not _column_exists('releases', 'git_branch'):
        op.add_column('releases', sa.Column('git_branch', sa.String(100), nullable=True))

    # Add release_id column to testcase_metadata table
    if not _column_exists('testcase_metadata', 'release_id'):
        op.add_column('testcase_metadata', sa.Column('release_id', sa.Integer(), nullable=True))

    # Add is_removed column to testcase_metadata table
    if not _column_exists('testcase_metadata', 'is_removed'):
        op.add_column('testcase_metadata', sa.Column('is_removed', sa.Boolean(), nullable=False, server_default='0'))

    # Add is_removed column to test_results table
    if not _column_exists('test_results', 'is_removed'):
        op.add_column('test_results', sa.Column('is_removed', sa.Boolean(), nullable=False, server_default='0'))

    # Add release_id column to metadata_sync_logs table
    if not _column_exists('metadata_sync_logs', 'release_id'):
        op.add_column('metadata_sync_logs', sa.Column('release_id', sa.Integer(), nullable=True))

    # Create composite index on testcase_metadata (release_id, testcase_name)
    if not _index_exists('idx_release_testcase'):
        op.create_index('idx_release_testcase', 'testcase_metadata', ['release_id', 'testcase_name'])

    # Create index on testcase_metadata.is_removed
    if not _index_exists('idx_is_removed'):
        op.create_index('idx_is_removed', 'testcase_metadata', ['is_removed'])

    # Create index on test_results.is_removed
    if not _index_exists('idx_test_results_is_removed'):
        op.create_index('idx_test_results_is_removed', 'test_results', ['is_removed'])

    # Backfill git_branch for existing releases
    op.execute("""
        UPDATE releases SET git_branch = 'master' WHERE name = '7.0.0.0' AND git_branch IS NULL
    """)
    op.execute("""
        UPDATE releases SET git_branch = 'release_6.4' WHERE name = '6.4.0.0' AND git_branch IS NULL
    """)
    op.execute("""
        UPDATE releases SET git_branch = 'release_6.1_branch' WHERE name = '6.1.0.0' AND git_branch IS NULL
    """)

    # Backfill is_removed from testcase_metadata_changes (only if not already done)
    op.execute("""
        UPDATE testcase_metadata
        SET is_removed = 1
        WHERE is_removed = 0
          AND testcase_name IN (
            SELECT DISTINCT testcase_name
            FROM testcase_metadata_changes
            WHERE change_type = 'removed'
        )
    """)

    # Backfill is_removed into test_results from testcase_metadata (only if not already done)
    op.execute("""
        UPDATE test_results
        SET is_removed = 1
        WHERE is_removed = 0
          AND test_name IN (
            SELECT testcase_name
            FROM testcase_metadata
            WHERE is_removed = 1
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    if _index_exists('idx_test_results_is_removed'):
        op.drop_index('idx_test_results_is_removed', 'test_results')
    if _index_exists('idx_is_removed'):
        op.drop_index('idx_is_removed', 'testcase_metadata')
    if _index_exists('idx_release_testcase'):
        op.drop_index('idx_release_testcase', 'testcase_metadata')

    # Drop columns
    if _column_exists('metadata_sync_logs', 'release_id'):
        op.drop_column('metadata_sync_logs', 'release_id')
    if _column_exists('test_results', 'is_removed'):
        op.drop_column('test_results', 'is_removed')
    if _column_exists('testcase_metadata', 'is_removed'):
        op.drop_column('testcase_metadata', 'is_removed')
    if _column_exists('testcase_metadata', 'release_id'):
        op.drop_column('testcase_metadata', 'release_id')
    if _column_exists('releases', 'git_branch'):
        op.drop_column('releases', 'git_branch')
