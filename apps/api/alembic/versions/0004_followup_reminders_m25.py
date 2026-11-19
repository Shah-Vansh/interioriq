"""follow-up reminders (M25)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('lead_followups') as b:
        b.add_column(sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('lead_followups') as b:
        b.drop_column('reminded_at')
