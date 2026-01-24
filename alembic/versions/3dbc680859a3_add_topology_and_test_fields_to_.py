"""add topology and test fields to testcase_metadata

Revision ID: 3dbc680859a3
Revises: c9f368737bfc
Create Date: 2026-01-24 22:57:05.171886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3dbc680859a3'
down_revision: Union[str, Sequence[str], None] = 'c9f368737bfc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 5 new fields to testcase_metadata table."""
    with op.batch_alter_table('testcase_metadata', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('module', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('test_state', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('test_class_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('test_path', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('topology', sa.String(length=100), nullable=True))

        # Create indexes for commonly filtered fields
        batch_op.create_index('idx_module_meta', ['module'], unique=False)
        batch_op.create_index('idx_topology_meta', ['topology'], unique=False)
        batch_op.create_index('idx_test_state_meta', ['test_state'], unique=False)


def downgrade() -> None:
    """Remove fields added to testcase_metadata table."""
    with op.batch_alter_table('testcase_metadata', schema=None) as batch_op:
        # Drop indexes first
        batch_op.drop_index('idx_test_state_meta')
        batch_op.drop_index('idx_topology_meta')
        batch_op.drop_index('idx_module_meta')

        # Drop columns
        batch_op.drop_column('topology')
        batch_op.drop_column('test_path')
        batch_op.drop_column('test_class_name')
        batch_op.drop_column('test_state')
        batch_op.drop_column('module')
