"""split topology into jenkins_topology and metadata

Revision ID: 9722860d4fd4
Revises: 3dbc680859a3
Create Date: 2026-01-24 22:57:51.400482

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9722860d4fd4'
down_revision: Union[str, Sequence[str], None] = '3dbc680859a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Rename topology to jenkins_topology and add topology_metadata column in test_results.

    IMPORTANT - Data Migration Notes:
    - topology_metadata will be NULL after this migration until import script is run
    - This is EXPECTED behavior - topology_metadata comes from CSV metadata, not Jenkins
    - Run 'python scripts/import_topology_metadata.py' after migration to populate values
    - The NULL window is safe - UI handles NULL values gracefully with 'N/A' display
    """
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        # Step 1: Add new topology_metadata column (will be NULL initially)
        # NOTE: Values populated by import_topology_metadata.py script
        batch_op.add_column(sa.Column('topology_metadata', sa.String(length=100), nullable=True))

        # Step 2: Rename existing topology → jenkins_topology
        batch_op.alter_column('topology',
                            new_column_name='jenkins_topology',
                            existing_type=sa.String(length=100),
                            existing_nullable=True)

        # Step 3: Create indexes on topology columns
        batch_op.create_index('idx_topology_metadata', ['topology_metadata'], unique=False)

        # Step 4: Add compound index for efficient filtering by job + design topology
        batch_op.create_index('idx_job_topology_metadata', ['job_id', 'topology_metadata'], unique=False)


def downgrade() -> None:
    """Reverse the topology column changes in test_results."""
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        # Drop indexes first
        batch_op.drop_index('idx_job_topology_metadata')
        batch_op.drop_index('idx_topology_metadata')

        # Rename jenkins_topology back to topology
        batch_op.alter_column('jenkins_topology',
                            new_column_name='topology',
                            existing_type=sa.String(length=100),
                            existing_nullable=True)

        # Drop the new column
        batch_op.drop_column('topology_metadata')
