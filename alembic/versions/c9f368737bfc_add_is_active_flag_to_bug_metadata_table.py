"""Add is_active flag to bug_metadata table

Revision ID: c9f368737bfc
Revises: 0a749d6f148e
Create Date: 2026-01-22 20:34:30.786988

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f368737bfc'
down_revision: Union[str, Sequence[str], None] = '0a749d6f148e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_active column with default True
    op.add_column('bug_metadata', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))

    # Create index for better query performance
    op.create_index('idx_is_active', 'bug_metadata', ['is_active'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index first
    op.drop_index('idx_is_active', table_name='bug_metadata')

    # Drop column
    op.drop_column('bug_metadata', 'is_active')
