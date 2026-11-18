"""baseline schema (M22)

Revision ID: 0001
Revises: 
Create Date: 2026-11-18 15:35:27.367503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── Baseline = the schema as of M22, the last version managed by the old in-place upgrade (create tables + add missing columns).
# Databases created before Alembic have no alembic_version table; for them this same revision is idempotent: tables that exist only get
# the columns they lack (added as NULLable, no data rewritten — exactly what the old upgrade did) and indexes are created if missing.
# Then they are stamped and continue with the normal revision chain like every other database.
def _added() -> list:
    """'table.column' names added to an existing database; migrate() passes a list in config.attributes to collect them."""
    from alembic import context
    return context.config.attributes.setdefault("added", [])


def _create_table(name, *items, **kw):
    bind = op.get_bind(); insp = sa.inspect(bind)
    if not insp.has_table(name):
        op.create_table(name, *items, **kw); return
    have = {c["name"] for c in insp.get_columns(name)}
    for c in items:
        if isinstance(c, sa.Column) and c.name not in have:
            op.add_column(name, sa.Column(c.name, c.type, nullable=True)); _added().append(f"{name}.{c.name}")


def _index(table, name, cols, unique=False):
    insp = sa.inspect(op.get_bind())
    if name not in {i["name"] for i in insp.get_indexes(table)}: op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    """Upgrade schema."""
    _create_table('clients',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('city', sa.String(), nullable=True),
    sa.Column('phone_norm', sa.String(), nullable=True),
    sa.Column('company', sa.String(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('gstin', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _index('clients', 'ix_clients_phone_norm', ['phone_norm'], unique=False)

    _create_table('company_settings',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('updated_by', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    _create_table('suppliers',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('contact_person', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('phone_norm', sa.String(), nullable=True),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('city', sa.String(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('gstin', sa.String(), nullable=True),
    sa.Column('lead_time_days', sa.Integer(), nullable=True),
    sa.Column('payment_terms_days', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _index('suppliers', 'ix_suppliers_gstin', ['gstin'], unique=False)
    _index('suppliers', 'ix_suppliers_phone_norm', ['phone_norm'], unique=False)

    _create_table('contacts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('relation', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('phone_norm', sa.String(), nullable=True),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('contacts', 'ix_contacts_client_id', ['client_id'], unique=False)
    _index('contacts', 'ix_contacts_phone_norm', ['phone_norm'], unique=False)

    _create_table('furniture_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('length_mm', sa.Float(), nullable=True),
    sa.Column('width_mm', sa.Float(), nullable=True),
    sa.Column('height_mm', sa.Float(), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('stock', sa.Integer(), nullable=True),
    sa.Column('material', sa.String(), nullable=True),
    sa.Column('colour', sa.String(), nullable=True),
    sa.Column('cost_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('kind', sa.String(), nullable=True),
    sa.Column('unit', sa.String(), nullable=True),
    sa.Column('supplier_id', sa.String(), nullable=True),
    sa.Column('min_stock', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('mount_mm', sa.Float(), nullable=True),
    sa.Column('style', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('furniture_items', 'ix_furniture_items_kind', ['kind'], unique=False)
    _index('furniture_items', 'ix_furniture_items_sku', ['sku'], unique=True)
    _index('furniture_items', 'ix_furniture_items_supplier_id', ['supplier_id'], unique=False)

    _create_table('projects',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_number', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('budget', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('progress', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=True),
    sa.Column('site_address', sa.Text(), nullable=True),
    sa.Column('target_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_number')
    )
    _create_table('supplier_payments',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('supplier_id', sa.String(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('reference', sa.String(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('supplier_payments', 'ix_supplier_payments_supplier_id', ['supplier_id'], unique=False)

    _create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('password_hash', sa.String(), nullable=False),
    sa.Column('full_name', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('client_id', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('users', 'ix_users_email', ['email'], unique=True)

    _create_table('expenses',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('spent_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('vendor', sa.String(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('expenses', 'ix_expenses_project_id', ['project_id'], unique=False)

    _create_table('handovers',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('received_by', sa.String(), nullable=False),
    sa.Column('handed_over_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('warranty_months', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id')
    )
    _create_table('install_tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('assigned_to', sa.String(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('install_tasks', 'ix_install_tasks_project_id', ['project_id'], unique=False)

    _create_table('leads',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('phone_norm', sa.String(), nullable=True),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('city', sa.String(), nullable=True),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('requirement', sa.Text(), nullable=True),
    sa.Column('budget', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assigned_to', sa.String(), nullable=True),
    sa.Column('lost_reason', sa.Text(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('leads', 'ix_leads_assigned_to', ['assigned_to'], unique=False)
    _index('leads', 'ix_leads_phone_norm', ['phone_norm'], unique=False)
    _index('leads', 'ix_leads_stage', ['stage'], unique=False)

    _create_table('messages',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('channel', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('trigger', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('ref_id', sa.String(), nullable=True),
    sa.Column('to', sa.String(), nullable=False),
    sa.Column('subject', sa.String(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('attachment', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('messages', 'ix_messages_created_at', ['created_at'], unique=False)
    _index('messages', 'ix_messages_project_id', ['project_id'], unique=False)
    _index('messages', 'ix_messages_ref_id', ['ref_id'], unique=False)

    _create_table('price_changes',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('item_id', sa.String(), nullable=False),
    sa.Column('old_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('new_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('field', sa.String(), nullable=True),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['furniture_items.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('price_changes', 'ix_price_changes_item_id', ['item_id'], unique=False)

    _create_table('project_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('ref_type', sa.String(), nullable=True),
    sa.Column('ref_id', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('project_events', 'ix_project_events_created_at', ['created_at'], unique=False)
    _index('project_events', 'ix_project_events_project_id', ['project_id'], unique=False)

    _create_table('project_members',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('added_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member')
    )
    _index('project_members', 'ix_project_members_project_id', ['project_id'], unique=False)
    _index('project_members', 'ix_project_members_user_id', ['user_id'], unique=False)

    _create_table('qc_checks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('checked_by', sa.String(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('qc_checks', 'ix_qc_checks_project_id', ['project_id'], unique=False)

    _create_table('rooms',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('room_type', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('stock_movements',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('item_id', sa.String(), nullable=False),
    sa.Column('delta', sa.Integer(), nullable=False),
    sa.Column('balance', sa.Integer(), nullable=False),
    sa.Column('ref_type', sa.String(), nullable=True),
    sa.Column('ref_id', sa.String(), nullable=True),
    sa.Column('unit_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['furniture_items.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('stock_movements', 'ix_stock_movements_item_id', ['item_id'], unique=False)
    _index('stock_movements', 'ix_stock_movements_project_id', ['project_id'], unique=False)
    _index('stock_movements', 'ix_stock_movements_ref_id', ['ref_id'], unique=False)

    _create_table('designs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('room_id', sa.String(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('tier', sa.String(), nullable=True),
    sa.Column('design_json', sa.JSON(), nullable=False),
    sa.Column('is_valid', sa.Boolean(), nullable=True),
    sa.Column('approval_status', sa.String(), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'version')
    )
    _create_table('documents',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('room_id', sa.String(), nullable=True),
    sa.Column('original_name', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(), nullable=False),
    sa.Column('storage_path', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('error', sa.String(), nullable=True),
    sa.Column('ocr_json', sa.JSON(), nullable=True),
    sa.Column('uploaded_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'sha256')
    )
    _index('documents', 'ix_documents_project_id', ['project_id'], unique=False)

    _create_table('lead_activities',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('lead_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('from_stage', sa.String(), nullable=True),
    sa.Column('to_stage', sa.String(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('lead_activities', 'ix_lead_activities_lead_id', ['lead_id'], unique=False)

    _create_table('lead_followups',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('lead_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('assigned_to', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('closed_by', sa.String(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('lead_followups', 'ix_lead_followups_assigned_to', ['assigned_to'], unique=False)
    _index('lead_followups', 'ix_lead_followups_due_at', ['due_at'], unique=False)
    _index('lead_followups', 'ix_lead_followups_lead_id', ['lead_id'], unique=False)

    _create_table('measurements',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('room_id', sa.String(), nullable=False),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'label')
    )
    _create_table('openings',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('room_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('wall', sa.String(), nullable=False),
    sa.Column('offset_mm', sa.Float(), nullable=False),
    sa.Column('width_mm', sa.Float(), nullable=False),
    sa.Column('height_mm', sa.Float(), nullable=False),
    sa.Column('sill_mm', sa.Float(), nullable=False),
    sa.Column('swing', sa.String(), nullable=True),
    sa.Column('label', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('openings', 'ix_openings_room_id', ['room_id'], unique=False)

    _create_table('snags',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('check_id', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('raised_by', sa.String(), nullable=True),
    sa.Column('fixed_by', sa.String(), nullable=True),
    sa.Column('fix_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fixed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['check_id'], ['qc_checks.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('snags', 'ix_snags_project_id', ['project_id'], unique=False)

    _create_table('boqs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('room_id', sa.String(), nullable=False),
    sa.Column('design_id', sa.String(), nullable=False),
    sa.Column('design_version', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('totals', sa.JSON(), nullable=False),
    sa.Column('warnings', sa.JSON(), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('quote_seq', sa.Integer(), nullable=True),
    sa.Column('status_note', sa.Text(), nullable=True),
    sa.Column('status_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['design_id'], ['designs.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'version')
    )
    _index('boqs', 'ix_boqs_room_id', ['room_id'], unique=False)

    _create_table('boq_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(), nullable=True),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('material', sa.String(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('unit', sa.String(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('labour', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('supplier', sa.String(), nullable=True),
    sa.Column('flags', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('boq_items', 'ix_boq_items_boq_id', ['boq_id'], unique=False)

    _create_table('delivery_notes',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('dn_number', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('scheduled_on', sa.DateTime(timezone=True), nullable=True),
    sa.Column('vehicle', sa.String(), nullable=True),
    sa.Column('driver', sa.String(), nullable=True),
    sa.Column('received_by', sa.String(), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dn_number')
    )
    _index('delivery_notes', 'ix_delivery_notes_project_id', ['project_id'], unique=False)

    _create_table('invoices',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('invoice_no', sa.String(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('fy', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('issue_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('taxable', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gst_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('cgst', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('sgst', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('igst', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('place_of_supply', sa.String(), nullable=True),
    sa.Column('sac_code', sa.String(), nullable=True),
    sa.Column('seller', sa.JSON(), nullable=False),
    sa.Column('buyer', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invoice_no')
    )
    _index('invoices', 'ix_invoices_boq_id', ['boq_id'], unique=False)
    _index('invoices', 'ix_invoices_project_id', ['project_id'], unique=False)

    _create_table('payments',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('received_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('reference', sa.String(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('payments', 'ix_payments_boq_id', ['boq_id'], unique=False)
    _index('payments', 'ix_payments_project_id', ['project_id'], unique=False)

    _create_table('purchase_orders',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('po_number', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('supplier_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('expected_on', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('po_number')
    )
    _index('purchase_orders', 'ix_purchase_orders_boq_id', ['boq_id'], unique=False)
    _index('purchase_orders', 'ix_purchase_orders_project_id', ['project_id'], unique=False)
    _index('purchase_orders', 'ix_purchase_orders_supplier_id', ['supplier_id'], unique=False)

    _create_table('work_orders',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('wo_number', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('boq_id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=True),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('unit_no', sa.Integer(), nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('cut_list', sa.JSON(), nullable=False),
    sa.Column('updated_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['boq_id'], ['boqs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wo_number')
    )
    _index('work_orders', 'ix_work_orders_boq_id', ['boq_id'], unique=False)
    _index('work_orders', 'ix_work_orders_project_id', ['project_id'], unique=False)

    _create_table('delivery_lines',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('dn_id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=True),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('unit', sa.String(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['dn_id'], ['delivery_notes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('delivery_lines', 'ix_delivery_lines_dn_id', ['dn_id'], unique=False)

    _create_table('po_lines',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('po_id', sa.String(), nullable=False),
    sa.Column('item_id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('unit', sa.String(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('received', sa.Integer(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['furniture_items.id'], ),
    sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('po_lines', 'ix_po_lines_po_id', ['po_id'], unique=False)

    _create_table('supplier_bills',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('supplier_id', sa.String(), nullable=False),
    sa.Column('bill_no', sa.String(), nullable=False),
    sa.Column('bill_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('po_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('taxable', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gst', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('match', sa.String(), nullable=True),
    sa.Column('approve_reason', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('user_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('supplier_bills', 'ix_supplier_bills_po_id', ['po_id'], unique=False)
    _index('supplier_bills', 'ix_supplier_bills_project_id', ['project_id'], unique=False)
    _index('supplier_bills', 'ix_supplier_bills_supplier_id', ['supplier_id'], unique=False)

    _create_table('payment_allocations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('payment_id', sa.String(), nullable=False),
    sa.Column('bill_id', sa.String(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['bill_id'], ['supplier_bills.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['supplier_payments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _index('payment_allocations', 'ix_payment_allocations_bill_id', ['bill_id'], unique=False)
    _index('payment_allocations', 'ix_payment_allocations_payment_id', ['payment_id'], unique=False)

    # ### end Alembic commands ###



def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('payment_allocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_allocations_payment_id'))
        batch_op.drop_index(batch_op.f('ix_payment_allocations_bill_id'))

    op.drop_table('payment_allocations')
    with op.batch_alter_table('supplier_bills', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_bills_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_bills_project_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_bills_po_id'))

    op.drop_table('supplier_bills')
    with op.batch_alter_table('po_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_po_lines_po_id'))

    op.drop_table('po_lines')
    with op.batch_alter_table('delivery_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delivery_lines_dn_id'))

    op.drop_table('delivery_lines')
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_work_orders_project_id'))
        batch_op.drop_index(batch_op.f('ix_work_orders_boq_id'))

    op.drop_table('work_orders')
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_purchase_orders_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_purchase_orders_project_id'))
        batch_op.drop_index(batch_op.f('ix_purchase_orders_boq_id'))

    op.drop_table('purchase_orders')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_project_id'))
        batch_op.drop_index(batch_op.f('ix_payments_boq_id'))

    op.drop_table('payments')
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invoices_project_id'))
        batch_op.drop_index(batch_op.f('ix_invoices_boq_id'))

    op.drop_table('invoices')
    with op.batch_alter_table('delivery_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delivery_notes_project_id'))

    op.drop_table('delivery_notes')
    with op.batch_alter_table('boq_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_boq_items_boq_id'))

    op.drop_table('boq_items')
    with op.batch_alter_table('boqs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_boqs_room_id'))

    op.drop_table('boqs')
    with op.batch_alter_table('snags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_snags_project_id'))

    op.drop_table('snags')
    with op.batch_alter_table('openings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_openings_room_id'))

    op.drop_table('openings')
    op.drop_table('measurements')
    with op.batch_alter_table('lead_followups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lead_followups_lead_id'))
        batch_op.drop_index(batch_op.f('ix_lead_followups_due_at'))
        batch_op.drop_index(batch_op.f('ix_lead_followups_assigned_to'))

    op.drop_table('lead_followups')
    with op.batch_alter_table('lead_activities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lead_activities_lead_id'))

    op.drop_table('lead_activities')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_project_id'))

    op.drop_table('documents')
    op.drop_table('designs')
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_movements_ref_id'))
        batch_op.drop_index(batch_op.f('ix_stock_movements_project_id'))
        batch_op.drop_index(batch_op.f('ix_stock_movements_item_id'))

    op.drop_table('stock_movements')
    op.drop_table('rooms')
    with op.batch_alter_table('qc_checks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_qc_checks_project_id'))

    op.drop_table('qc_checks')
    with op.batch_alter_table('project_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_project_members_project_id'))

    op.drop_table('project_members')
    with op.batch_alter_table('project_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_events_project_id'))
        batch_op.drop_index(batch_op.f('ix_project_events_created_at'))

    op.drop_table('project_events')
    with op.batch_alter_table('price_changes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_price_changes_item_id'))

    op.drop_table('price_changes')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_messages_ref_id'))
        batch_op.drop_index(batch_op.f('ix_messages_project_id'))
        batch_op.drop_index(batch_op.f('ix_messages_created_at'))

    op.drop_table('messages')
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_leads_stage'))
        batch_op.drop_index(batch_op.f('ix_leads_phone_norm'))
        batch_op.drop_index(batch_op.f('ix_leads_assigned_to'))

    op.drop_table('leads')
    with op.batch_alter_table('install_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_install_tasks_project_id'))

    op.drop_table('install_tasks')
    op.drop_table('handovers')
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expenses_project_id'))

    op.drop_table('expenses')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('supplier_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_payments_supplier_id'))

    op.drop_table('supplier_payments')
    op.drop_table('projects')
    with op.batch_alter_table('furniture_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_furniture_items_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_furniture_items_sku'))
        batch_op.drop_index(batch_op.f('ix_furniture_items_kind'))

    op.drop_table('furniture_items')
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contacts_phone_norm'))
        batch_op.drop_index(batch_op.f('ix_contacts_client_id'))

    op.drop_table('contacts')
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_suppliers_phone_norm'))
        batch_op.drop_index(batch_op.f('ix_suppliers_gstin'))

    op.drop_table('suppliers')
    op.drop_table('company_settings')
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_clients_phone_norm'))

    op.drop_table('clients')
    # ### end Alembic commands ###
