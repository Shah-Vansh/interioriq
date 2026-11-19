"""recurring follow-ups (M31)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('lead_followups') as b:
        b.add_column(sa.Column('repeat_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('lead_followups') as b:
        b.drop_column('repeat_days')
