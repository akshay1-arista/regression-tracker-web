"""add_index_on_testcase_metadata_release_id

Adds performance index on testcase_metadata.release_id for faster queries.

This index improves performance for release-specific metadata queries,
which are common in the Git-based metadata sync feature.

Revision ID: 36c78902bcf4
Revises: e977e2ce3a00
Create Date: 2026-02-20 11:19:42.881964

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36c78902bcf4'
down_revision: Union[str, Sequence[str], None] = 'e977e2ce3a00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add index on testcase_metadata.release_id for performance."""
    # Create index for release_id filtering
    # This speeds up queries like:
    #   SELECT * FROM testcase_metadata WHERE release_id = X
    #   SELECT * FROM testcase_metadata WHERE release_id IS NULL
    op.create_index(
        'idx_testcase_metadata_release_id',
        'testcase_metadata',
        ['release_id']
    )


def downgrade() -> None:
    """Remove index on testcase_metadata.release_id."""
    op.drop_index('idx_testcase_metadata_release_id', table_name='testcase_metadata')
