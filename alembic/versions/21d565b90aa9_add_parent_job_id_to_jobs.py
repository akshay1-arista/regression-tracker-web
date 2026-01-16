"""add_parent_job_id_to_jobs

Revision ID: 21d565b90aa9
Revises: b2c3d4e5f6g7
Create Date: 2026-01-16 23:26:40.308356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21d565b90aa9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add parent_job_id column to jobs table to track parent Jenkins job."""
    # Add parent_job_id column
    op.add_column('jobs', sa.Column('parent_job_id', sa.String(20), nullable=True))

    # Add index for efficient queries
    op.create_index('idx_parent_job', 'jobs', ['parent_job_id'])


def downgrade() -> None:
    """Remove parent_job_id column from jobs table."""
    # Drop index first
    op.drop_index('idx_parent_job', table_name='jobs')

    # Drop column
    op.drop_column('jobs', 'parent_job_id')
