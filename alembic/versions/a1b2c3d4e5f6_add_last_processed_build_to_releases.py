"""add last_processed_build to releases

Revision ID: a1b2c3d4e5f6
Revises: d629f0307876
Create Date: 2024-01-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd629f0307876'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add last_processed_build column to releases table to track
    which main job build number was last processed by polling.
    """
    # Add column with default value of 0
    op.add_column('releases', sa.Column('last_processed_build', sa.Integer(), nullable=True, default=0))

    # Update existing rows to have 0 as the default
    op.execute('UPDATE releases SET last_processed_build = 0 WHERE last_processed_build IS NULL')

    # Make column non-nullable after setting defaults
    # (SQLite doesn't support ALTER COLUMN, so we'll keep it nullable)


def downgrade():
    """Remove last_processed_build column."""
    op.drop_column('releases', 'last_processed_build')
