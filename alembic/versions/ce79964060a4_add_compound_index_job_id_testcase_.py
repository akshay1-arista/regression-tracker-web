"""Add compound index job_id testcase_module

Revision ID: ce79964060a4
Revises: f1a2b3c4d5e6
Create Date: 2026-04-20 10:34:42.364347

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ce79964060a4'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add compound index on (job_id, testcase_module) for batch flaky query optimization."""
    op.create_index('idx_job_testcase_module', 'test_results', ['job_id', 'testcase_module'], unique=False)


def downgrade() -> None:
    """Remove compound index on (job_id, testcase_module)."""
    op.drop_index('idx_job_testcase_module', table_name='test_results')
