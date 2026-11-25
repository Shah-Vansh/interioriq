"""room shape, ceiling profile, structures (beams / columns / pillars / ceiling drops), openings on any wall (M41)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('rooms') as b:
        b.add_column(sa.Column('shape', sa.JSON(), nullable=True))
        b.add_column(sa.Column('ceiling_profile', sa.JSON(), nullable=True))
    with op.batch_alter_table('openings') as b:
        b.add_column(sa.Column('edge', sa.Integer(), nullable=True))
    op.create_table('room_structures',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('room_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('x_mm', sa.Float(), nullable=False),
        sa.Column('y_mm', sa.Float(), nullable=False),
        sa.Column('length_mm', sa.Float(), nullable=False),
        sa.Column('width_mm', sa.Float(), nullable=False),
        sa.Column('depth_mm', sa.Float(), nullable=True),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_room_structures_room_id', 'room_structures', ['room_id'])


def downgrade() -> None:
    op.drop_index('ix_room_structures_room_id', 'room_structures')
    op.drop_table('room_structures')
    with op.batch_alter_table('openings') as b:
        b.drop_column('edge')
    with op.batch_alter_table('rooms') as b:
        b.drop_column('ceiling_profile'); b.drop_column('shape')
