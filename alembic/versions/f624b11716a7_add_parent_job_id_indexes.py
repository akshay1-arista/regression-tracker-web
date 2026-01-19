"""add_parent_job_id_indexes

Revision ID: f624b11716a7
Revises: d7e8f9g0h1i2
Create Date: 2026-01-19 13:00:04.800021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f624b11716a7'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9g0h1i2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add indexes for parent_job_id for All Modules feature."""
    # Add index on parent_job_id for efficient grouping
    op.create_index(
        'idx_parent_job_id',
        'jobs',
        ['parent_job_id'],
        unique=False
    )

    # Add composite index for parent_job_id + version filtering
    op.create_index(
        'idx_parent_version',
        'jobs',
        ['parent_job_id', 'version'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema - Remove parent_job_id indexes."""
    op.drop_index('idx_parent_version', table_name='jobs')
    op.drop_index('idx_parent_job_id', table_name='jobs')
