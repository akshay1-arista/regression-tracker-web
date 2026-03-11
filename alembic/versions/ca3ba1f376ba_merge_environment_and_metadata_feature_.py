"""merge environment and metadata feature branches

Revision ID: ca3ba1f376ba
Revises: 36c78902bcf4, 787cbd70f222
Create Date: 2026-03-10 15:33:17.684332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca3ba1f376ba'
down_revision: Union[str, Sequence[str], None] = ('36c78902bcf4', '787cbd70f222')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
