"""remove_unique_constraint_on_testcase_name

This migration removes the UNIQUE constraint on testcase_name to allow
the same test to have different metadata in different releases.

The composite index idx_release_testcase (release_id, testcase_name)
provides uniqueness per release, which is the correct behavior.

Revision ID: 87c8aa4c8094
Revises: 132428a13e8b
Create Date: 2026-02-06 12:44:05.232564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = '87c8aa4c8094'
down_revision: Union[str, Sequence[str], None] = '132428a13e8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(index_name: str, table_name: str) -> bool:
    """Check if an index exists on a specific table."""
    conn = op.get_bind()
    inspector = reflection.Inspector.from_engine(conn)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """
    Remove UNIQUE constraint on testcase_metadata.testcase_name.

    This allows the same test to have different metadata in different releases.
    The composite index (release_id, testcase_name) ensures uniqueness per release.
    """
    # Drop both unique indexes on testcase_name
    # These prevent having the same test with different release_ids
    if _index_exists('ix_testcase_metadata_testcase_name', 'testcase_metadata'):
        op.drop_index('ix_testcase_metadata_testcase_name', 'testcase_metadata')

    if _index_exists('idx_testcase_name', 'testcase_metadata'):
        op.drop_index('idx_testcase_name', 'testcase_metadata')

    # Create non-unique index for search performance
    op.create_index('idx_testcase_name_search', 'testcase_metadata', ['testcase_name'])


def downgrade() -> None:
    """Restore UNIQUE constraint on testcase_name."""
    # Drop the non-unique index
    if _index_exists('idx_testcase_name_search', 'testcase_metadata'):
        op.drop_index('idx_testcase_name_search', 'testcase_metadata')

    # Recreate the unique indexes
    op.create_index('ix_testcase_metadata_testcase_name', 'testcase_metadata', ['testcase_name'], unique=True)
    op.create_index('idx_testcase_name', 'testcase_metadata', ['testcase_name'], unique=True)
