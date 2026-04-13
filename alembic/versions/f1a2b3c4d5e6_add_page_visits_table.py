"""add page_visits table

Revision ID: f1a2b3c4d5e6
Revises: e977e2ce3a00
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'ca3ba1f376ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create page_visits table for visit analytics."""
    op.create_table(
        'page_visits',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('path', sa.String(200), nullable=False),
        sa.Column('visited_at', sa.DateTime(), nullable=False),
        sa.Column('ip_hash', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_page_visits_visited_at', 'page_visits', ['visited_at'])
    op.create_index('ix_page_visits_path', 'page_visits', ['path'])


def downgrade() -> None:
    """Drop page_visits table."""
    op.drop_index('ix_page_visits_path', table_name='page_visits')
    op.drop_index('ix_page_visits_visited_at', table_name='page_visits')
    op.drop_table('page_visits')
