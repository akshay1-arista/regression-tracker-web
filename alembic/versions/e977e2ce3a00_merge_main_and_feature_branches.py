"""merge main and feature branches

Revision ID: e977e2ce3a00
Revises: 1062c069a1c1, 87c8aa4c8094
Create Date: 2026-02-13 00:14:55.200368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e977e2ce3a00'
down_revision: Union[str, Sequence[str], None] = ('1062c069a1c1', '87c8aa4c8094')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
