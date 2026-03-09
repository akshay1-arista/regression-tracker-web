"""Add environment to jobs

Revision ID: 787cbd70f222
Revises: 1062c069a1c1
Create Date: 2026-03-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '787cbd70f222'
down_revision = '1062c069a1c1'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add environment column to jobs table to distinguish prod vs staging runs.

    Uses server_default='prod' so all existing rows are backfilled automatically.
    """
    op.add_column('jobs', sa.Column('environment', sa.String(10), nullable=False, server_default='prod'))
    op.create_index('idx_job_environment', 'jobs', ['environment'])


def downgrade():
    """Remove environment column and index from jobs table."""
    op.drop_index('idx_job_environment', 'jobs')
    op.drop_column('jobs', 'environment')
