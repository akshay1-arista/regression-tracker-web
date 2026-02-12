"""Add executed_at to jobs

Revision ID: 1062c069a1c1
Revises: 9722860d4fd4
Create Date: 2026-02-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '1062c069a1c1'
down_revision = '9722860d4fd4'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add executed_at column to jobs table to store Jenkins build execution timestamp.

    This allows showing accurate execution time instead of DB import time in parent job dropdown.
    """
    # Add executed_at column (nullable to support existing records)
    op.add_column('jobs', sa.Column('executed_at', sa.DateTime(), nullable=True))

    # Optional: Create index for performance if querying by executed_at frequently
    # op.create_index('idx_job_executed', 'jobs', ['executed_at'])


def downgrade():
    """Remove executed_at column from jobs table."""
    # op.drop_index('idx_job_executed', 'jobs')
    op.drop_column('jobs', 'executed_at')
