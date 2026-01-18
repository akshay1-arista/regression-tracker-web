"""add compound index for job_id and priority filtering

Revision ID: d7e8f9g0h1i2
Revises: c3d4e5f6g7h8
Create Date: 2026-01-17 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7e8f9g0h1i2'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add compound index on test_results(job_id, priority) for optimized filtering queries.

    This index supports common query patterns like:
    - SELECT * FROM test_results WHERE job_id = X AND priority = 'P0'
    - SELECT * FROM test_results WHERE job_id = X AND priority IN ('P0', 'P1')
    """
    # Create compound index using batch mode for SQLite compatibility
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.create_index(
            'idx_job_priority',
            ['job_id', 'priority'],
            unique=False
        )


def downgrade():
    """Remove compound index on test_results(job_id, priority)."""
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.drop_index('idx_job_priority')
