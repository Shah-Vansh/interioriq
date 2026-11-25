"""home plan positions (M37)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('rooms') as b:
        b.add_column(sa.Column('plan_x', sa.Float(), nullable=True))
        b.add_column(sa.Column('plan_y', sa.Float(), nullable=True))
        b.add_column(sa.Column('level', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('rooms') as b:
        b.drop_column('level'); b.drop_column('plan_y'); b.drop_column('plan_x')
