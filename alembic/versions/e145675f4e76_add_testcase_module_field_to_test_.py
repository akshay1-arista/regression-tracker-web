"""Add testcase_module field to test_results

Revision ID: e145675f4e76
Revises: 1c9b6008c034
Create Date: 2026-01-20 21:29:30.648557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e145675f4e76'
down_revision: Union[str, Sequence[str], None] = '1c9b6008c034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - simplified for SQLite compatibility."""
    # Add testcase_module column and index (the only critical change for this migration)
    op.add_column('test_results', sa.Column('testcase_module', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_test_results_testcase_module'), 'test_results', ['testcase_module'], unique=False)

    # Note: Other schema changes detected by autogenerate (column type changes, index modifications)
    # are skipped because SQLite has limited ALTER TABLE support. These are non-critical changes
    # that don't affect the testcase_module functionality.


def downgrade() -> None:
    """Downgrade schema - simplified for SQLite compatibility."""
    # Remove testcase_module index and column
    op.drop_index(op.f('ix_test_results_testcase_module'), table_name='test_results')
    op.drop_column('test_results', 'testcase_module')
