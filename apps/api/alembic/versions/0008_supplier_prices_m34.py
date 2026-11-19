"""per-supplier prices (M34)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('supplier_prices',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('supplier_id', sa.String(), nullable=False),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('min_qty', sa.Integer(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lead_days', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('ended_reason', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['furniture_items.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_supplier_prices_item_id', 'supplier_prices', ['item_id'])
    op.create_index('ix_supplier_prices_supplier_id', 'supplier_prices', ['supplier_id'])


def downgrade() -> None:
    op.drop_index('ix_supplier_prices_supplier_id', 'supplier_prices')
    op.drop_index('ix_supplier_prices_item_id', 'supplier_prices')
    op.drop_table('supplier_prices')
