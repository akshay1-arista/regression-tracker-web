"""add_bug_tracking_tables

Revision ID: 1c9b6008c034
Revises: f624b11716a7
Create Date: 2026-01-20 00:05:30.956624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c9b6008c034'
down_revision: Union[str, Sequence[str], None] = 'f624b11716a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add bug tracking tables."""
    # Create bug_metadata table
    op.create_table(
        'bug_metadata',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('defect_id', sa.String(50), nullable=False),
        sa.Column('bug_type', sa.String(10), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('status', sa.String(50)),
        sa.Column('summary', sa.Text()),
        sa.Column('priority', sa.String(20)),
        sa.Column('assignee', sa.String(100)),
        sa.Column('component', sa.String(100)),
        sa.Column('resolution', sa.String(50)),
        sa.Column('affected_versions', sa.String(200)),
        sa.Column('labels', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_defect_id', 'bug_metadata', ['defect_id'], unique=True)
    op.create_index('idx_bug_type', 'bug_metadata', ['bug_type'])
    op.create_index('idx_status', 'bug_metadata', ['status'])

    # Create bug_testcase_mappings table
    op.create_table(
        'bug_testcase_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bug_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['bug_id'], ['bug_metadata.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_case_id', 'bug_testcase_mappings', ['case_id'])
    op.create_index('idx_bug_id', 'bug_testcase_mappings', ['bug_id'])
    op.create_index('idx_bug_case_unique', 'bug_testcase_mappings',
                    ['bug_id', 'case_id'], unique=True)


def downgrade() -> None:
    """
    Downgrade schema - Remove bug tracking tables.

    ⚠️ WARNING: This will permanently delete all bug tracking data!
    Ensure you have a database backup before downgrading.
    All bug metadata and testcase mappings will be lost.
    """
    # Drop bug_testcase_mappings table and indexes
    op.drop_index('idx_bug_case_unique', 'bug_testcase_mappings')
    op.drop_index('idx_bug_id', 'bug_testcase_mappings')
    op.drop_index('idx_case_id', 'bug_testcase_mappings')
    op.drop_table('bug_testcase_mappings')

    # Drop bug_metadata table and indexes
    op.drop_index('idx_status', 'bug_metadata')
    op.drop_index('idx_bug_type', 'bug_metadata')
    op.drop_index('idx_defect_id', 'bug_metadata')
    op.drop_table('bug_metadata')
