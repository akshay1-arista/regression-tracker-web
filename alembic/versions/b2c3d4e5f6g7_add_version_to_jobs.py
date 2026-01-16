"""add version to jobs

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2024-01-16 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add version column to jobs table to store version info
    extracted from Jenkins job title (e.g., "VER: 7.0.0.0").
    """
    # Add column (nullable since existing jobs won't have it)
    op.add_column('jobs', sa.Column('version', sa.String(50), nullable=True))


def downgrade():
    """Remove version column."""
    op.drop_column('jobs', 'version')
