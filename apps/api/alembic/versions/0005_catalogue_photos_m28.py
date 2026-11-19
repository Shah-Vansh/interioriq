"""catalogue item photos (M28)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('furniture_items') as b:
        b.add_column(sa.Column('photo', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('furniture_items') as b:
        b.drop_column('photo')
