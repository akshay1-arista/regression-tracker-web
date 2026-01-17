"""add priority support: TestcaseMetadata table and TestResult.priority column

Revision ID: c3d4e5f6g7h8
Revises: 21d565b90aa9
Create Date: 2026-01-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import DateTime


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = '21d565b90aa9'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add priority support:
    1. Create testcase_metadata table for CSV data
    2. Add priority column to test_results (denormalized for fast filtering)
    """
    # 1. Create testcase_metadata table
    op.create_table(
        'testcase_metadata',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('testcase_name', sa.String(length=200), nullable=False),
        sa.Column('test_case_id', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.String(length=5), nullable=True),
        sa.Column('testrail_id', sa.String(length=20), nullable=True),
        sa.Column('component', sa.String(length=100), nullable=True),
        sa.Column('automation_status', sa.String(length=50), nullable=True),
        sa.Column('created_at', DateTime(), nullable=True),
        sa.Column('updated_at', DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for testcase_metadata
    op.create_index('idx_testcase_name', 'testcase_metadata', ['testcase_name'], unique=True)
    op.create_index('idx_priority_meta', 'testcase_metadata', ['priority'])
    op.create_index('idx_test_case_id', 'testcase_metadata', ['test_case_id'])
    op.create_index('idx_testrail_id', 'testcase_metadata', ['testrail_id'])

    # 2. Add priority column to test_results
    # Using batch mode for SQLite compatibility
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('priority', sa.String(length=5), nullable=True))
        batch_op.create_index('idx_priority', ['priority'])
        batch_op.create_index('idx_test_name_priority', ['test_name', 'priority'])


def downgrade():
    """
    Remove priority support:
    1. Drop priority indexes and column from test_results
    2. Drop testcase_metadata table
    """
    # Drop indexes and column from test_results
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.drop_index('idx_test_name_priority')
        batch_op.drop_index('idx_priority')
        batch_op.drop_column('priority')

    # Drop testcase_metadata indexes and table
    op.drop_index('idx_testrail_id', table_name='testcase_metadata')
    op.drop_index('idx_test_case_id', table_name='testcase_metadata')
    op.drop_index('idx_priority_meta', table_name='testcase_metadata')
    op.drop_index('idx_testcase_name', table_name='testcase_metadata')
    op.drop_table('testcase_metadata')
