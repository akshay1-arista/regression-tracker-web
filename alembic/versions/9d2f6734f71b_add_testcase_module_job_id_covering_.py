"""add_testcase_module_job_id_covering_index

Revision ID: 9d2f6734f71b
Revises: ce79964060a4
Create Date: 2026-05-04 14:59:03.918744

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2f6734f71b'
down_revision: Union[str, Sequence[str], None] = 'ce79964060a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('idx_testcase_module_job_id', 'test_results',
                    ['testcase_module', 'job_id'])


def downgrade() -> None:
    op.drop_index('idx_testcase_module_job_id', table_name='test_results')
