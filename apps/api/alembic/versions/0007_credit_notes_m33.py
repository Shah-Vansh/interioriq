"""credit notes (M33)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('credit_notes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('note_no', sa.String(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('fy', sa.String(), nullable=False),
        sa.Column('invoice_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('issue_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('taxable', sa.Numeric(14, 2), nullable=False),
        sa.Column('cgst', sa.Numeric(14, 2), nullable=False),
        sa.Column('sgst', sa.Numeric(14, 2), nullable=False),
        sa.Column('igst', sa.Numeric(14, 2), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('cancel_reason', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('note_no'))
    op.create_index('ix_credit_notes_invoice_id', 'credit_notes', ['invoice_id'])
    op.create_index('ix_credit_notes_project_id', 'credit_notes', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_credit_notes_project_id', 'credit_notes')
    op.drop_index('ix_credit_notes_invoice_id', 'credit_notes')
    op.drop_table('credit_notes')
