import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from app.core.database import Base

def _id() -> str: return str(uuid.uuid4())
_last = [datetime.min.replace(tzinfo=timezone.utc)]
def _now():
    """Strictly increasing UTC timestamps: two rows written in the same clock tick (Windows ticks ~15 ms) still sort in the order they happened."""
    t = datetime.now(timezone.utc)
    if t <= _last[0]: t = _last[0] + timedelta(microseconds=1)
    _last[0] = t
    return t

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_id)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="INTERIOR_DESIGNER")
    is_active = Column(Boolean, default=True)
    client_id = Column(String, ForeignKey("clients.id"))   # CLIENT users only: which client's projects they may see in the portal
    phone = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)

ROLES = ["SUPER_ADMIN", "ADMIN", "PROJECT_MANAGER", "SALES", "INTERIOR_DESIGNER", "ESTIMATOR", "SITE_ENGINEER", "PROCUREMENT_MANAGER",
         "INVENTORY_MANAGER", "MANUFACTURING_MANAGER", "INSTALLATION_MANAGER", "QC_MANAGER", "CLIENT"]

class Client(Base):
    __tablename__ = "clients"
    id = Column(String, primary_key=True, default=_id)
    name = Column(String, nullable=False)
    phone = Column(String); email = Column(String); city = Column(String)
    phone_norm = Column(String, index=True)          # canonical +<country><number>; duplicates are detected on THIS, however the phone was typed
    company = Column(String); address = Column(Text); notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)
    gstin = Column(String)                            # optional: a GST-registered client (B2B); its state code is the default place of supply


LEAD_STAGES = ["NEW", "CONTACTED", "QUALIFIED", "SITE_VISIT", "DESIGN", "QUOTATION", "NEGOTIATION", "WON", "LOST"]


class Lead(Base):
    __tablename__ = "leads"
    id = Column(String, primary_key=True, default=_id)
    name = Column(String, nullable=False)
    phone = Column(String); phone_norm = Column(String, index=True)
    email = Column(String); city = Column(String)
    source = Column(String)                          # walk-in, referral, website, ...
    requirement = Column(Text)
    budget = Column(Numeric(14, 2))
    stage = Column(String, nullable=False, default="NEW", index=True)
    client_id = Column(String, ForeignKey("clients.id"))
    project_id = Column(String, ForeignKey("projects.id"))
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    assigned_to = Column(String, ForeignKey("users.id"), index=True)    # M20: who owns the lead
    lost_reason = Column(Text)                                          # required when moved to LOST
    archived = Column(Boolean)                                          # hidden from the board; never deleted


LOST_REASONS = ["Budget too high", "Chose another firm", "Timeline didn't suit", "Not reachable", "Project cancelled", "Only enquiring", "Other"]
FOLLOWUP_KINDS = ["CALL", "VISIT", "MEETING", "WHATSAPP", "EMAIL", "OTHER"]


class LeadFollowUp(Base):
    """A scheduled next step on a lead. OPEN until done (with an outcome) or cancelled (with a reason); never deleted."""
    __tablename__ = "lead_followups"
    id = Column(String, primary_key=True, default=_id)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, default="CALL")
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    note = Column(Text)
    assigned_to = Column(String, ForeignKey("users.id"), index=True)
    status = Column(String, nullable=False, default="OPEN")     # OPEN | DONE | CANCELLED
    outcome = Column(Text)
    closed_by = Column(String); closed_at = Column(DateTime(timezone=True))
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    repeat_days = Column(Integer)                    # M31: repeat every N days — marking it done books the next one; NULL = once
    reminded_at = Column(DateTime(timezone=True))   # M25: when the "due soon" reminder was claimed (cleared when rescheduled/reassigned)


class LeadActivity(Base):
    """Append-only history of a lead: creation, every stage change, notes, conversion. Never edited."""
    __tablename__ = "lead_activities"
    id = Column(String, primary_key=True, default=_id)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)            # CREATED | STAGE | NOTE | CONVERTED
    from_stage = Column(String); to_stage = Column(String)
    text = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=_id)
    project_number = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    client_id = Column(String, ForeignKey("clients.id"))
    status = Column(String, default="LEAD")
    budget = Column(Numeric(14, 2))
    progress = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_now)
    archived = Column(Boolean)
    site_address = Column(Text)
    target_date = Column(DateTime(timezone=True))       # promised handover date (AI PM flags projects at risk of missing it)
    completed_at = Column(DateTime(timezone=True))

# Forward-only lifecycle; services/flow.advance() never moves a project backwards automatically.
PROJECT_STAGES = ["LEAD", "SURVEY", "DESIGN", "QUOTATION", "PROCUREMENT", "MANUFACTURING", "DELIVERY", "INSTALLATION", "QC", "HANDOVER", "COMPLETED"]

class Room(Base):
    __tablename__ = "rooms"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    room_type = Column(String, nullable=False)
    plan_x = Column(Float); plan_y = Column(Float)      # M37: south-west corner of the room on the home plan (mm); NULL = not placed yet
    level = Column(Integer)                             # M37: floor (0 = ground)
    shape = Column(JSON)            # M41: None/RECT | {"type":"CUTS","cuts":{"NE":[l,w],…}} (L/U/T-shaped) | {"type":"POLYGON","points":[[x,y],…]} (angled walls)
    ceiling_profile = Column(JSON)  # M41: None/FLAT | {"type":"SLOPED","low":mm,"high":mm,"high_wall":"N|E|S|W"} | {"type":"UNEVEN","points":[[x,y,h],…]}

class Measurement(Base):
    """One current value per (room, label). Every value carries provenance."""
    __tablename__ = "measurements"
    __table_args__ = (UniqueConstraint("room_id", "label"),)
    id = Column(String, primary_key=True, default=_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    label = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String, nullable=False, default="mm")
    source = Column(String, nullable=False)
    confidence = Column(Float, default=100.0)
    verified = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

class Design(Base):
    """Append-only: each save is a new (room_id, version) row. Never updated in place."""
    __tablename__ = "designs"
    __table_args__ = (UniqueConstraint("room_id", "version"),)
    id = Column(String, primary_key=True, default=_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    version = Column(Integer, nullable=False)
    tier = Column(String)
    design_json = Column(JSON, nullable=False)
    is_valid = Column(Boolean)
    approval_status = Column(String, default="DRAFT")
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)

class FurnitureItem(Base):
    __tablename__ = "furniture_items"
    id = Column(String, primary_key=True, default=_id)
    sku = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    length_mm = Column(Float); width_mm = Column(Float); height_mm = Column(Float)
    price = Column(Numeric(12, 2), nullable=False)
    stock = Column(Integer, default=0)
    material = Column(String); colour = Column(String)
    cost_price = Column(Numeric(12, 2))                  # M16: what WE pay (purchase cost); price = what the client pays. NULL = not known yet
    # M9: one catalogue table for every kind of item (kept as "furniture_items" so saved designs and old databases keep working).
    kind = Column(String, index=True)                    # FURNITURE | MATERIAL | LIGHTING | HARDWARE  (NULL on pre-M9 rows → backfilled to FURNITURE)
    unit = Column(String)                                # No. | sq.ft | sq.m | r.ft | r.m | sheet | set | kg | litre | box
    supplier_id = Column(String, ForeignKey("suppliers.id"), index=True)
    min_stock = Column(Integer)                          # reorder level: stock at or below this is "low"
    description = Column(Text)
    is_active = Column(Boolean)                          # archived items are hidden from the designer but old designs/BOQs still resolve them
    mount_mm = Column(Float)                             # M21b: fixed this high above the floor when placed (wall cabinet 1450); NULL = stands on the floor
    photo = Column(String)                               # M28: stored photo base name (services/photos.py); NULL = no photo
    style = Column(String)                               # M21b: style tags, lower-case, comma separated (modern, minimal, luxury, …) — the designer prefers matches
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


CATALOGUE_KINDS = ["FURNITURE", "MATERIAL", "LIGHTING", "HARDWARE"]
CATALOGUE_UNITS = ["No.", "set", "sq.ft", "sq.m", "r.ft", "r.m", "sheet", "kg", "litre", "box"]


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(String, primary_key=True, default=_id)
    name = Column(String, nullable=False)
    contact_person = Column(String)
    phone = Column(String); phone_norm = Column(String, index=True)
    email = Column(String); city = Column(String); address = Column(Text)
    gstin = Column(String, index=True)
    lead_time_days = Column(Integer)
    payment_terms_days = Column(Integer)              # M17: days after the bill date a bill falls due (NULL → 30)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class PriceChange(Base):
    """Append-only: every catalogue price change, who made it and why. Never edited or deleted."""
    __tablename__ = "price_changes"
    id = Column(String, primary_key=True, default=_id)
    item_id = Column(String, ForeignKey("furniture_items.id"), nullable=False, index=True)
    old_price = Column(Numeric(12, 2)); new_price = Column(Numeric(12, 2), nullable=False)
    field = Column(String)                               # PRICE (selling, NULL on old rows) | COST (purchase cost)
    reason = Column(String, nullable=False)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class StockMovement(Base):
    """Append-only stock ledger: +received / -issued / correction, with the resulting balance."""
    __tablename__ = "stock_movements"
    id = Column(String, primary_key=True, default=_id)
    item_id = Column(String, ForeignKey("furniture_items.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    balance = Column(Integer, nullable=False)
    ref_type = Column(String); ref_id = Column(String, index=True)       # e.g. PO / BOQ: which document caused the movement
    unit_cost = Column(Numeric(14, 2))                   # cost per unit for allocations taken FROM STOCK (PO receipts are costed on the PO line)
    project_id = Column(String, ForeignKey("projects.id"), index=True)
    reason = Column(String, nullable=False)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class Document(Base):
    """An uploaded floor plan / drawing. The stored filename is generated server-side; the client's name is display-only."""
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    room_id = Column(String, ForeignKey("rooms.id"))
    original_name = Column(String, nullable=False)
    kind = Column(String, nullable=False)                 # pdf | png | jpg | tiff  (sniffed from content, never trusted from the client)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    category = Column(String, default="FLOOR_PLAN")
    status = Column(String, default="UPLOADED")           # UPLOADED | PROCESSING | OCR_DONE | FAILED
    processing_started_at = Column(DateTime(timezone=True))  # M23: when a worker claimed it — a reading older than OCR_STALE_MINUTES is considered dead
    error = Column(String)
    ocr_json = Column(JSON)
    uploaded_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class Boq(Base):
    """Immutable snapshot: prices, rates and totals as they were when generated. Regenerate to get a new version."""
    __tablename__ = "boqs"
    __table_args__ = (UniqueConstraint("room_id", "version"),)
    id = Column(String, primary_key=True, default=_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    design_id = Column(String, ForeignKey("designs.id"), nullable=False)
    design_version = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    params = Column(JSON, nullable=False)
    totals = Column(JSON, nullable=False)
    warnings = Column(JSON, default=list)
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    status = Column(String)                  # DRAFT | SENT | APPROVED | REJECTED | SUPERSEDED  (NULL on pre-M10 rows = DRAFT)
    quote_seq = Column(Integer)              # project-wide quotation number (QT-<project>-NN); version stays per room
    status_note = Column(Text)
    status_at = Column(DateTime(timezone=True))


class BoqItem(Base):
    __tablename__ = "boq_items"
    id = Column(String, primary_key=True, default=_id)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    sku = Column(String)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    material = Column(String)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit = Column(String, nullable=False)
    rate = Column(Numeric(14, 2), nullable=False)
    labour = Column(Numeric(14, 2), nullable=False, default=0)
    total = Column(Numeric(14, 2), nullable=False)
    supplier = Column(String)
    flags = Column(JSON, default=list)


# ── M10–M13: operations ───────────────────────────────────────────────────────
class ProjectEvent(Base):
    """Append-only project timeline (status changes, approvals, POs, deliveries, QC, handover). Feeds the dashboard activity feed."""
    __tablename__ = "project_events"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    ref_type = Column(String); ref_id = Column(String)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    received_on = Column(DateTime(timezone=True), nullable=False)
    mode = Column(String, nullable=False)              # BANK | UPI | CHEQUE | CASH | CARD
    reference = Column(String); note = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(String, primary_key=True, default=_id)
    po_number = Column(String, unique=True, nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="DRAFT")   # DRAFT | ISSUED | PARTIAL | RECEIVED | CANCELLED
    expected_on = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    issued_at = Column(DateTime(timezone=True))


class POLine(Base):
    __tablename__ = "po_lines"
    id = Column(String, primary_key=True, default=_id)
    po_id = Column(String, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    item_id = Column(String, ForeignKey("furniture_items.id"), nullable=False)
    sku = Column(String, nullable=False); description = Column(String, nullable=False); unit = Column(String, nullable=False)
    qty = Column(Integer, nullable=False)
    received = Column(Integer, nullable=False, default=0)
    rate = Column(Numeric(14, 2), nullable=False)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id = Column(String, primary_key=True, default=_id)
    wo_number = Column(String, unique=True, nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False, index=True)
    sku = Column(String); description = Column(String, nullable=False)
    unit_no = Column(Integer, nullable=False)          # 1..qty: one work order per physical unit
    stage = Column(String, nullable=False, default="PENDING")   # PENDING | CUTTING | EDGEBANDING | ASSEMBLY | FINISHING | READY
    cut_list = Column(JSON, nullable=False)
    updated_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"
    id = Column(String, primary_key=True, default=_id)
    dn_number = Column(String, unique=True, nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False)
    status = Column(String, nullable=False, default="SCHEDULED")   # SCHEDULED | DISPATCHED | DELIVERED | CANCELLED
    scheduled_on = Column(DateTime(timezone=True))
    vehicle = Column(String); driver = Column(String); received_by = Column(String)
    delivered_at = Column(DateTime(timezone=True))
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class DeliveryLine(Base):
    __tablename__ = "delivery_lines"
    id = Column(String, primary_key=True, default=_id)
    dn_id = Column(String, ForeignKey("delivery_notes.id"), nullable=False, index=True)
    sku = Column(String); description = Column(String, nullable=False); unit = Column(String, nullable=False)
    qty = Column(Integer, nullable=False)


class InstallTask(Base):
    __tablename__ = "install_tasks"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    sku = Column(String); title = Column(String, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="PENDING")  # PENDING | IN_PROGRESS | DONE
    assigned_to = Column(String)                                # user id
    note = Column(Text)
    updated_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class QCCheck(Base):
    __tablename__ = "qc_checks"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    source = Column(String, nullable=False)       # TASK | STANDARD | CUSTOM
    status = Column(String, nullable=False, default="PENDING")   # PENDING | PASS | FAIL
    note = Column(Text)
    checked_by = Column(String); checked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)


class Snag(Base):
    __tablename__ = "snags"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    check_id = Column(String, ForeignKey("qc_checks.id"))
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="OPEN")      # OPEN | FIXED
    raised_by = Column(String); fixed_by = Column(String); fix_note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)
    fixed_at = Column(DateTime(timezone=True))


class Handover(Base):
    __tablename__ = "handovers"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, unique=True)
    received_by = Column(String, nullable=False)
    handed_over_on = Column(DateTime(timezone=True), nullable=False)
    warranty_months = Column(Integer, nullable=False, default=12)
    notes = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class Contact(Base):
    """People around a client: spouse, architect, site supervisor, accounts."""
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, default=_id)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    relation = Column(String)
    phone = Column(String); phone_norm = Column(String, index=True); email = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)


class ProjectMember(Base):
    """M22: who is on a project's team. Only matters when Settings → Company 'Limit staff to their projects' is on."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    added_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class JobLock(Base):
    """M24: named schedule claims (e.g. 'auto_backup' = the local date of the last automatic backup). A conditional UPDATE on this row is
    how several API servers agree that exactly one of them runs a scheduled job."""
    __tablename__ = "job_locks"
    name = Column(String, primary_key=True)
    value = Column(String)
    updated_at = Column(DateTime(timezone=True), default=_now)


class CompanySetting(Base):
    """Key/value company profile (name, address, GSTIN, quotation validity) editable in Settings -> Company."""
    __tablename__ = "company_settings"
    key = Column(String, primary_key=True)
    value = Column(JSON)
    updated_by = Column(String)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Invoice(Base):
    """Issued invoices are immutable (only cancelled, with a reason). The number is never reused.
    kind TAX = GST tax invoice (GST was ON for the quotation): the amount includes GST, split into taxable value + CGST/SGST or IGST.
    kind PLAIN = GST was OFF for the quotation: no GST anywhere on the document."""
    __tablename__ = "invoices"
    id = Column(String, primary_key=True, default=_id)
    invoice_no = Column(String, unique=True, nullable=False)
    seq = Column(Integer, nullable=False)                  # running number within the financial year
    fy = Column(String, nullable=False)                    # e.g. 2026-27
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    boq_id = Column(String, ForeignKey("boqs.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)                  # TAX | PLAIN
    issue_date = Column(DateTime(timezone=True), nullable=False)
    description = Column(String, nullable=False)           # milestone or free text
    amount = Column(Numeric(14, 2), nullable=False)        # total payable on this invoice
    taxable = Column(Numeric(14, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    cgst = Column(Numeric(14, 2), nullable=False, default=0)
    sgst = Column(Numeric(14, 2), nullable=False, default=0)
    igst = Column(Numeric(14, 2), nullable=False, default=0)
    place_of_supply = Column(String)                       # GST state code (TAX only)
    sac_code = Column(String)
    seller = Column(JSON, nullable=False)                  # company details AS ISSUED (later settings changes don't alter an issued invoice)
    buyer = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="ISSUED")   # ISSUED | CANCELLED
    cancel_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    cancelled_at = Column(DateTime(timezone=True))


class SupplierPrice(Base):
    """M34: what a SUPPLIER charges us for an item (their quote / rate card), with validity dates and a minimum quantity. Procurement buys
    from the cheapest valid quote; with none it falls back to the item's default supplier and cost. Never edited: end a quote and add a new one."""
    __tablename__ = "supplier_prices"
    id = Column(String, primary_key=True, default=_id)
    item_id = Column(String, ForeignKey("furniture_items.id"), nullable=False, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=False, index=True)
    price = Column(Numeric(12, 2), nullable=False)
    min_qty = Column(Integer, nullable=False, default=1)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True))                 # NULL = open-ended
    lead_days = Column(Integer)
    note = Column(Text)
    ended_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class CreditNote(Base):
    """M33: reduces an ISSUED invoice (rate change, item dropped, discount after billing) without cancelling it. Same GST treatment as its
    invoice (TAX: taxable + CGST/SGST or IGST, parts sum exactly; PLAIN: none). Never edited; cancelled with a reason; number never reused."""
    __tablename__ = "credit_notes"
    id = Column(String, primary_key=True, default=_id)
    note_no = Column(String, unique=True, nullable=False)
    seq = Column(Integer, nullable=False); fy = Column(String, nullable=False)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    issue_date = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    taxable = Column(Numeric(14, 2), nullable=False)
    cgst = Column(Numeric(14, 2), nullable=False, default=0); sgst = Column(Numeric(14, 2), nullable=False, default=0); igst = Column(Numeric(14, 2), nullable=False, default=0)
    status = Column(String, nullable=False, default="ISSUED")   # ISSUED | CANCELLED
    cancel_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    cancelled_at = Column(DateTime(timezone=True))


class Message(Base):
    """Outbox / message log (append-only apart from delivery status). Email is sent by the background worker; WhatsApp is a click-to-chat link
    the user opens and sends themselves (status LINK). Auto notifications that couldn't go out are kept as SKIPPED with the reason."""
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=_id)
    channel = Column(String, nullable=False)              # EMAIL | WHATSAPP
    kind = Column(String, nullable=False)                 # QUOTATION | INVOICE | PO | DELIVERY | HANDOVER | PAYMENT | TEST
    trigger = Column(String, nullable=False, default="MANUAL")   # MANUAL | AUTO
    project_id = Column(String, ForeignKey("projects.id"), index=True)
    ref_id = Column(String, index=True)                   # the document it is about
    to = Column(String, nullable=False)
    subject = Column(String)
    body = Column(Text, nullable=False)
    attachment = Column(String)                           # file name of the attached PDF (email only)
    status = Column(String, nullable=False)               # QUEUED | SENDING | SENT | FAILED | LINK | SKIPPED
    error = Column(Text)
    attempts = Column(Integer, nullable=False, default=0)
    claimed_at = Column(DateTime(timezone=True))          # M23: when a worker claimed it for sending — only SENDING rows older than EMAIL_STALE_MINUTES are re-queued
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    sent_at = Column(DateTime(timezone=True))


EXPENSE_CATEGORIES = ["LABOUR", "CONTRACTOR", "TRANSPORT", "SITE", "MATERIAL", "DESIGN", "OTHER"]


class Expense(Base):
    """Project costs that don't come through purchase orders (labour, contractors, transport, site expenses…).
    Never edited; a mistake is VOIDed with a reason so totals and history stay honest."""
    __tablename__ = "expenses"
    id = Column(String, primary_key=True, default=_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    spent_on = Column(DateTime(timezone=True), nullable=False)
    vendor = Column(String); note = Column(Text)
    status = Column(String, nullable=False, default="ACTIVE")   # ACTIVE | VOID
    void_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class SupplierBill(Base):
    """A supplier's invoice to us. Amounts never change after entry; a wrong bill is VOIDed (only while nothing is paid against it)."""
    __tablename__ = "supplier_bills"
    id = Column(String, primary_key=True, default=_id)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=False, index=True)
    bill_no = Column(String, nullable=False)                  # the supplier's own invoice number (unique per supplier)
    bill_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    po_id = Column(String, ForeignKey("purchase_orders.id"), index=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True)
    taxable = Column(Numeric(14, 2), nullable=False)
    gst = Column(Numeric(14, 2), nullable=False, default=0)   # input GST on the bill (0 if the supplier didn't charge GST)
    total = Column(Numeric(14, 2), nullable=False)
    match = Column(String)                                    # MATCHED | OVER_BILLED | UNDER_BILLED | NO_PO  (against goods received on the PO)
    approve_reason = Column(Text)                             # required when OVER_BILLED
    note = Column(Text)
    status = Column(String, nullable=False, default="OPEN")   # OPEN | PARTIAL | PAID | VOID
    void_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class SupplierPayment(Base):
    """Money we paid a supplier, allocated to that supplier's bills (sum of allocations == amount). VOID with a reason reverses it."""
    __tablename__ = "supplier_payments"
    id = Column(String, primary_key=True, default=_id)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    paid_on = Column(DateTime(timezone=True), nullable=False)
    mode = Column(String, nullable=False)
    reference = Column(String); note = Column(Text)
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE | VOID
    void_reason = Column(Text)
    user_id = Column(String); user_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    id = Column(String, primary_key=True, default=_id)
    payment_id = Column(String, ForeignKey("supplier_payments.id"), nullable=False, index=True)
    bill_id = Column(String, ForeignKey("supplier_bills.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)


class Opening(Base):
    """A door or window in a room wall. Plan coordinates: origin at the room's south-west corner; offset runs along the wall —
    from the west end for the S/N walls, from the south end for the W/E walls."""
    __tablename__ = "openings"
    id = Column(String, primary_key=True, default=_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)          # DOOR | WINDOW
    wall = Column(String, nullable=False)          # N | E | S | W
    offset_mm = Column(Float, nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)
    sill_mm = Column(Float, nullable=False, default=0)   # windows: height of the sill above the floor; doors: 0
    swing = Column(String)                         # doors: INWARD_LEFT (hinge at the offset end) | INWARD_RIGHT (hinge at offset + width) | OUTWARD | SLIDING
    label = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
    edge = Column(Integer)                         # M41: set = the opening is on outline edge #edge (offset from that edge's start); NULL = on the N/E/S/W side


class RoomStructure(Base):
    """Fixed building parts inside a room (M41). Plan box x/y/length/width (mm from the room's south-west corner).
    COLUMN (against a wall) / PILLAR (free-standing): floor to ceiling. BEAM / CEILING_DROP: hang depth_mm below the ceiling."""
    __tablename__ = "room_structures"
    id = Column(String, primary_key=True, default=_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)          # BEAM | COLUMN | PILLAR | CEILING_DROP
    x_mm = Column(Float, nullable=False); y_mm = Column(Float, nullable=False)
    length_mm = Column(Float, nullable=False); width_mm = Column(Float, nullable=False)
    depth_mm = Column(Float)                       # beams / ceiling drops: how far below the ceiling the underside is
    label = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)
