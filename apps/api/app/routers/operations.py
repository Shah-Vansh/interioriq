"""M10–M11 operations: quotation approval + payments, purchase orders + goods receipt, inventory ledger, manufacturing work orders + cutting lists,
deliveries, installation, QC + snags, handover. Every step checks the previous one; every action is written to the project timeline."""
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access
from app.services import catalogue as catlib, company as companylib, cutting, doc_pdf, flow, fulfilment, notify
from app.services.cost_engine import D, inr, split_payments
from app.services import quote_terms
from app.services import supplier_prices as sp_lib

router = APIRouter(tags=["Operations"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))
Q_WRITE = ("ADMIN", "PROJECT_MANAGER", "SALES", "ESTIMATOR")
PAY = ("ADMIN", "PROJECT_MANAGER", "SALES")
PROC = ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER")
RECEIVE = PROC + ("INVENTORY_MANAGER",)
MFG = ("ADMIN", "PROJECT_MANAGER", "MANUFACTURING_MANAGER")
DELIV = ("ADMIN", "PROJECT_MANAGER", "INVENTORY_MANAGER", "INSTALLATION_MANAGER")
INSTALL = ("ADMIN", "PROJECT_MANAGER", "INSTALLATION_MANAGER", "SITE_ENGINEER")
QC = ("ADMIN", "PROJECT_MANAGER", "QC_MANAGER")
SNAG_FIX = QC + ("INSTALLATION_MANAGER", "SITE_ENGINEER")
HANDOVER = ("ADMIN", "PROJECT_MANAGER")
WO_STAGES = ["PENDING", "CUTTING", "EDGEBANDING", "ASSEMBLY", "FINISHING", "READY"]
STANDARD_QC = ["All shutters aligned, gaps even and level", "Hinges, channels and locks operate smoothly", "Edges banded, no chipping or open joints",
               "Surfaces clean, no scratches, stains or glue marks", "Electrical points and lighting working", "Site cleaned and debris removed"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _dt(d: date | None):
    return datetime.combine(d, time(12), tzinfo=timezone.utc) if d else None


def _iso(x): return x.isoformat() if x else None
def _money(x) -> str: return f"{D(x):.2f}"


def _project(db: Session, pid: str) -> m.Project:
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    return p


def _boq(db: Session, bid: str) -> m.Boq:
    b = db.get(m.Boq, bid)
    if not b: raise HTTPException(404, "BOQ not found")
    return b


def _qno(db: Session, b: m.Boq) -> str: return flow.quote_no(flow.project_of_boq(db, b).project_number, b)


def _locked(db: Session, pid: str):
    if db.query(m.Handover).filter_by(project_id=pid).first(): raise HTTPException(409, "This project has been handed over; its records are closed.")


def _approved(db: Session, b: m.Boq):
    if flow.boq_status(b) != "APPROVED": raise HTTPException(409, f"{_qno(db, b)} is {flow.boq_status(b)}, not APPROVED. Only an approved quotation can be executed.")


def _approved_boqs(db: Session, pid: str) -> list[m.Boq]:
    rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=pid)]
    return db.query(m.Boq).filter(m.Boq.room_id.in_(rooms), m.Boq.status == "APPROVED").order_by(m.Boq.created_at).all() if rooms else []


# ── Quotations ────────────────────────────────────────────────────────────────
def _paid(db: Session, bid: str) -> Decimal:
    return D(db.query(func.coalesce(func.sum(m.Payment.amount), 0)).filter_by(boq_id=bid).scalar() or 0)


def quotation_row(db: Session, b: m.Boq) -> dict:
    room = db.get(m.Room, b.room_id); p = db.get(m.Project, room.project_id); c = db.get(m.Client, p.client_id) if p.client_id else None
    return {"id": b.id, "quotation_no": flow.quote_no(p.project_number, b), "project_id": p.id, "project_number": p.project_number, "project_name": p.name,
            "client_name": c.name if c else None, "room_id": room.id, "room_name": room.name, "version": b.version, "design_version": b.design_version,
            "grand_total": b.totals["grand_total"], "status": flow.boq_status(b), "status_note": b.status_note, "status_at": _iso(b.status_at),
            "paid": _money(_paid(db, b.id)), "created_at": _iso(b.created_at)}


@router.get("/quotations")
def list_quotations(status: str | None = None, q: str | None = None, project_id: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    rows = [quotation_row(db, b) for b in db.query(m.Boq).order_by(m.Boq.created_at.desc())]
    ids = access.visible_ids(db, user)
    if ids is not None: rows = [r for r in rows if r["project_id"] in ids]
    if status: rows = [r for r in rows if r["status"] == status]
    if project_id: rows = [r for r in rows if r["project_id"] == project_id]
    if q and q.strip():
        k = q.strip().lower(); rows = [r for r in rows if any(k in (r[f] or "").lower() for f in ("quotation_no", "project_name", "client_name", "room_name"))]
    return rows


class StatusIn(_In):
    status: str
    note: str | None = Field(None, max_length=1000)


ALLOWED = {"DRAFT": {"SENT", "APPROVED", "REJECTED"}, "SENT": {"APPROVED", "REJECTED"}, "REJECTED": {"SENT"}, "APPROVED": set(), "SUPERSEDED": set()}


def _has_execution(db: Session, bid: str) -> list[str]:
    found = []
    if db.query(m.PurchaseOrder).filter(m.PurchaseOrder.boq_id == bid, m.PurchaseOrder.status != "CANCELLED").first(): found.append("purchase orders")
    if db.query(m.WorkOrder).filter_by(boq_id=bid).first(): found.append("work orders")
    if db.query(m.DeliveryNote).filter(m.DeliveryNote.boq_id == bid, m.DeliveryNote.status != "CANCELLED").first(): found.append("deliveries")
    if db.query(m.Payment).filter_by(boq_id=bid).first(): found.append("payments")
    if db.query(m.StockMovement).filter_by(ref_type="ALLOC", ref_id=bid).first(): found.append("stock allocations")
    return found


def set_quote_status(db: Session, b: m.Boq, to: str, note: str | None, user: dict):
    cur = flow.boq_status(b)
    if to not in ALLOWED.get(cur, set()):
        raise HTTPException(409, f"{_qno(db, b)} is {cur}; it can't be marked {to}." + (" An approved quotation is final — create a new BOQ version instead." if cur == "APPROVED" else ""))
    if to == "REJECTED" and not (note and note.strip()): raise HTTPException(422, [{"loc": ["body", "note"], "msg": "Give a reason for the rejection", "type": "value_error"}])
    project = flow.project_of_boq(db, b)
    if to == "APPROVED":
        for old in db.query(m.Boq).filter(m.Boq.room_id == b.room_id, m.Boq.status == "APPROVED", m.Boq.id != b.id):
            used = _has_execution(db, old.id)
            if used: raise HTTPException(409, f"{_qno(db, old)} is already approved for this room and has {', '.join(used)}. Cancel those before approving another version.")
            old.status, old.status_at, old.status_note = "SUPERSEDED", flow.now(), f"Superseded by {_qno(db, b)}"
            flow.event(db, project.id, "QUOTATION", f"{_qno(db, old)} superseded by {_qno(db, b)}", user, "BOQ", old.id)
    b.status, b.status_note, b.status_at = to, (note or "").strip() or None, flow.now()
    flow.event(db, project.id, "QUOTATION", f"{_qno(db, b)} marked {to}" + (f": {b.status_note}" if b.status_note else ""), user, "BOQ", b.id)
    if to == "SENT": flow.advance(db, project, "QUOTATION", user, f"{_qno(db, b)} sent to the client")
    if to == "APPROVED": flow.advance(db, project, "PROCUREMENT", user, f"{_qno(db, b)} approved")


@router.post("/boqs/{bid}/status")
def change_quote_status(bid: str, body: StatusIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*Q_WRITE))):
    b = _boq(db, bid); _locked(db, flow.project_of_boq(db, b).id)
    set_quote_status(db, b, body.status, body.note, user)
    if body.status == "SENT": notify.auto(db, "QUOTATION", b.id, user)
    db.commit()
    return quotation_row(db, b)


# ── Payments ──────────────────────────────────────────────────────────────────
MODES = ["BANK", "UPI", "CHEQUE", "CASH", "CARD"]


class PaymentIn(_In):
    boq_id: str
    amount: Decimal = Field(gt=0, le=10_000_000_000, decimal_places=2)
    received_on: date
    mode: str
    reference: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=500)

    @field_validator("mode")
    @classmethod
    def _m(cls, v):
        if v not in MODES: raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return v

    @field_validator("received_on")
    @classmethod
    def _d(cls, v):
        if v > date.today(): raise ValueError("A payment can't be received in the future")
        return v


def payment_summary(db: Session, pid: str) -> dict:
    boqs = _approved_boqs(db, pid)
    quoted = sum((D(b.totals["grand_total"]) for b in boqs), Decimal(0))
    pays = db.query(m.Payment).filter_by(project_id=pid).order_by(m.Payment.received_on, m.Payment.created_at).all()
    paid = sum((D(x.amount) for x in pays), Decimal(0))
    schedule, cum, left = [], Decimal(0), paid
    if quoted > 0:
        stages: dict = {}                                                    # label → amount, in first-seen order
        for b in boqs:
            sch = quote_terms.schedule_of(b.params)
            for (label, _), amt in zip(sch, split_payments(b.totals["grand_total"], [p for _, p in sch])): stages[label] = stages.get(label, Decimal(0)) + amt
        for label, amt in stages.items():
            got = min(amt, max(Decimal(0), left)); left -= got
            pct = format((amt * 100 / quoted).quantize(Decimal("0.01")).normalize(), "f")
            schedule.append({"stage": label, "pct": pct, "amount": _money(amt), "received": _money(got), "status": "PAID" if got == amt else ("PART" if got > 0 else "DUE")})
    return {"quoted": _money(quoted), "paid": _money(paid), "balance": _money(quoted - paid), "schedule": schedule,
            "payments": [{"id": x.id, "boq_id": x.boq_id, "amount": _money(x.amount), "received_on": x.received_on.date().isoformat(), "mode": x.mode,
                          "reference": x.reference, "note": x.note, "user_name": x.user_name} for x in pays]}


@router.get("/projects/{pid}/payments")
def list_payments(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); return payment_summary(db, pid)


@router.post("/projects/{pid}/payments", status_code=201)
def add_payment(pid: str, body: PaymentIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PAY))):
    p = _project(db, pid); b = _boq(db, body.boq_id)
    if flow.project_of_boq(db, b).id != pid: raise HTTPException(409, "That quotation belongs to another project")
    _approved(db, b)
    total, paid = D(b.totals["grand_total"]), _paid(db, b.id)
    if paid + body.amount > total:
        raise HTTPException(409, f"That would take payments to Rs. {inr(paid + body.amount)}, more than the quotation total Rs. {inr(total)} (balance Rs. {inr(total - paid)}).")
    pay = m.Payment(project_id=pid, boq_id=b.id, amount=body.amount, received_on=_dt(body.received_on), mode=body.mode, reference=body.reference,
                    note=body.note, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(pay); db.flush()
    flow.event(db, pid, "PAYMENT", f"Payment Rs. {inr(body.amount)} received ({body.mode}) against {_qno(db, b)}", user, "BOQ", b.id)
    notify.auto(db, "PAYMENT", pay.id, user)
    db.commit(); return payment_summary(db, pid)


# ── Fulfilment + procurement ──────────────────────────────────────────────────
@router.get("/boqs/{bid}/fulfilment")
def get_fulfilment(bid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    b = _boq(db, bid)
    rows = fulfilment.lines(db, b)
    for r in rows: r.pop("size", None)
    return {"boq": quotation_row(db, b), "lines": rows, "boards": fulfilment.board_need(db, b)}


def po_out(db: Session, po: m.PurchaseOrder, with_lines=True) -> dict:
    s = db.get(m.Supplier, po.supplier_id); p = db.get(m.Project, po.project_id)
    lines = db.query(m.POLine).filter_by(po_id=po.id).order_by(m.POLine.description).all()
    total = sum((D(l.rate) * l.qty for l in lines), Decimal(0))
    out = {"id": po.id, "po_number": po.po_number, "status": po.status, "project_id": p.id, "project_number": p.project_number, "project_name": p.name,
           "boq_id": po.boq_id, "supplier_id": s.id, "supplier_name": s.name, "supplier_phone": s.phone, "expected_on": po.expected_on.date().isoformat() if po.expected_on else None,
           "notes": po.notes, "total": _money(total), "lines_count": len(lines), "received_pct": round(100 * sum(l.received for l in lines) / max(1, sum(l.qty for l in lines))),
           "created_at": _iso(po.created_at), "issued_at": _iso(po.issued_at)}
    if with_lines:
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "sku": l.sku, "description": l.description, "unit": l.unit, "qty": l.qty, "received": l.received,
                         "outstanding": l.qty - l.received, "rate": _money(l.rate), "amount": _money(D(l.rate) * l.qty)} for l in lines]
    return out


class ProcureIn(_In):
    use_stock: bool = True


@router.post("/boqs/{bid}/procure")
def procure(bid: str, body: ProcureIn = ProcureIn(), db: Session = Depends(get_db), user: dict = Depends(require_roles(*PROC))):
    """Allocate what's in stock and raise DRAFT purchase orders (one per supplier) for the rest. Safe to run again: only the remaining need is ordered."""
    b = _boq(db, bid); _approved(db, b); project = flow.project_of_boq(db, b); _locked(db, project.id)
    qno = _qno(db, b); need: dict[str, list] = defaultdict(list); allocated, unassigned, manual = [], [], []
    wanted: list[tuple[m.FurnitureItem, int, str]] = []
    for r in fulfilment.lines(db, b):
        if r["kind"] == "BOUGHT_OUT":
            rest = r["qty"] - r["ready"] - r["on_order"]
            if rest > 0: wanted.append((db.get(m.FurnitureItem, r["item_id"]), rest, r["description"]))
        elif r["kind"] == "MANUAL": manual.append(r["description"])
    comp = companylib.get(db); boards = fulfilment.board_need(db, b)
    for key, amount in (("board_sku_18", boards["sheets"].get(cutting.T, 0)), ("board_sku_8", boards["sheets"].get(cutting.BACK_T, 0)),
                        ("edge_band_sku", int(-(-boards["edge_band_m"] // 1)))):
        sku = (comp.get(key) or "").strip().upper()
        if not sku or amount <= 0: continue
        it = db.query(m.FurnitureItem).filter(func.upper(m.FurnitureItem.sku) == sku).first()
        if not it: unassigned.append(f"{sku} (set in Settings → Company, but not in the catalogue)"); continue
        rest = amount - fulfilment.allocated(db, b.id, it.id) - fulfilment.on_order(db, b.id, it.id)
        if rest > 0: wanted.append((it, rest, it.name))
    switched: list = []
    for it, rest, desc in wanted:
        if body.use_stock and (it.stock or 0) > 0:
            take = min(rest, it.stock)
            catlib.move_stock(db, it, -take, f"Allocated to {project.project_number} ({qno}) from stock", user, ref_type="ALLOC", ref_id=b.id, project_id=project.id,
                              unit_cost=it.cost_price if it.cost_price is not None else it.price)     # costed now; PO receipts are costed on their PO line
            allocated.append({"sku": it.sku, "qty": take}); rest -= take
        if rest <= 0: continue
        sid, rate, src, quote = sp_lib.best(db, it, rest)                           # M34: cheapest valid supplier quote, else default supplier at cost
        if not sid: unassigned.append(f"{it.sku} {it.name} × {rest}"); continue
        need[sid].append((it, rest, rate))
        if src == "QUOTE" and sid != it.supplier_id: switched.append(f"{it.sku}: {db.get(m.Supplier, sid).name} at Rs. {rate:,.2f} (best valid quote)")
    created = []
    for sid, rows in need.items():
        po = m.PurchaseOrder(po_number=flow.next_number(db, m.PurchaseOrder, m.PurchaseOrder.po_number, f"PO-{project.project_number}"), project_id=project.id,
                             boq_id=b.id, supplier_id=sid, status="DRAFT", created_by=user.get("sub"))
        db.add(po); db.flush()
        for it, q, rate in rows:
            db.add(m.POLine(po_id=po.id, item_id=it.id, sku=it.sku, description=it.name, unit=it.unit or "No.", qty=q, rate=rate))   # what we pay; editable while a draft
        created.append(po)
        flow.event(db, project.id, "PROCUREMENT", f"{po.po_number} drafted for {db.get(m.Supplier, sid).name} ({len(rows)} line(s)) from {qno}", user, "PO", po.id)
    if allocated: flow.event(db, project.id, "PROCUREMENT", f"Allocated from stock for {qno}: " + ", ".join(f"{a['sku']} × {a['qty']}" for a in allocated), user, "BOQ", b.id)
    db.commit()
    return {"created": [po_out(db, po, False) for po in created], "allocated_from_stock": allocated, "unassigned": unassigned,
            "manual": manual, "supplier_quotes_used": switched, "nothing_to_do": not (created or allocated or unassigned)}


@router.get("/purchase-orders")
def list_pos(project_id: str | None = None, status: str | None = None, supplier_id: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    q = access.scope(db.query(m.PurchaseOrder), m.PurchaseOrder.project_id, db, user)
    if project_id: q = q.filter_by(project_id=project_id)
    if status: q = q.filter_by(status=status)
    if supplier_id: q = q.filter_by(supplier_id=supplier_id)
    return [po_out(db, x, False) for x in q.order_by(m.PurchaseOrder.created_at.desc())]


def _po(db: Session, poid: str) -> m.PurchaseOrder:
    po = db.get(m.PurchaseOrder, poid)
    if not po: raise HTTPException(404, "Purchase order not found")
    return po


@router.get("/purchase-orders/{poid}")
def get_po(poid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))): return po_out(db, _po(db, poid))


class POPatch(_In):
    expected_on: date | None = None
    notes: str | None = Field(None, max_length=1000)
    lines: list[dict] | None = None        # [{id, qty, rate?}] — DRAFT only


@router.patch("/purchase-orders/{poid}")
def patch_po(poid: str, body: POPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PROC))):
    po = _po(db, poid); data = body.model_dump(exclude_unset=True)
    if po.status in ("RECEIVED", "CANCELLED"): raise HTTPException(409, f"{po.po_number} is {po.status}")
    if "expected_on" in data: po.expected_on = _dt(body.expected_on)
    if "notes" in data: po.notes = body.notes
    if body.lines is not None:
        if po.status != "DRAFT": raise HTTPException(409, "Quantities can only change while the PO is a draft")
        mine = {l.id: l for l in db.query(m.POLine).filter_by(po_id=po.id)}
        for row in body.lines:
            l = mine.get(str(row.get("id")))
            q = row.get("qty", l.qty if l else None)
            if not l or not isinstance(q, int) or q < 1 or q > 1_000_000: raise HTTPException(422, "Each line needs a valid id and a whole qty ≥ 1")
            if "rate" in row:
                try: r = Decimal(str(row["rate"]).replace(",", ""))
                except Exception: raise HTTPException(422, f"{l.sku}: rate must be a number")
                if r < 0 or r > 1_000_000_000 or r != r.quantize(Decimal("0.01")): raise HTTPException(422, f"{l.sku}: rate must be ≥ 0 with at most 2 decimals")
                l.rate = r
            l.qty = q
    db.commit(); return po_out(db, po)


@router.post("/purchase-orders/{poid}/issue")
def issue_po(poid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PROC))):
    po = _po(db, poid)
    if po.status != "DRAFT": raise HTTPException(409, f"{po.po_number} is {po.status}; only a draft can be issued")
    po.status, po.issued_at = "ISSUED", flow.now()
    flow.event(db, po.project_id, "PROCUREMENT", f"{po.po_number} issued to {db.get(m.Supplier, po.supplier_id).name}", user, "PO", po.id)
    db.commit(); return po_out(db, po)


@router.post("/purchase-orders/{poid}/cancel")
def cancel_po(poid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PROC))):
    po = _po(db, poid)
    if po.status not in ("DRAFT", "ISSUED"): raise HTTPException(409, f"{po.po_number} is {po.status}; goods have been received, so it can't be cancelled")
    po.status = "CANCELLED"; flow.event(db, po.project_id, "PROCUREMENT", f"{po.po_number} cancelled", user, "PO", po.id)
    db.commit(); return po_out(db, po)


class ReceiveLine(_In):
    line_id: str
    qty: int = Field(ge=1, le=1_000_000)


class ReceiveIn(_In):
    lines: list[ReceiveLine] = Field(min_length=1)


@router.post("/purchase-orders/{poid}/receive")
def receive_po(poid: str, body: ReceiveIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*RECEIVE))):
    """Goods received: stock IN against the PO, then allocated OUT to the project's quotation — both in the stock ledger."""
    po = _po(db, poid)
    if po.status not in ("ISSUED", "PARTIAL"): raise HTTPException(409, f"{po.po_number} is {po.status}; only an issued PO can be received")
    mine = {l.id: l for l in db.query(m.POLine).filter_by(po_id=po.id)}
    project = db.get(m.Project, po.project_id); qno = _qno(db, db.get(m.Boq, po.boq_id)); got = []
    for r in body.lines:
        l = mine.get(r.line_id)
        if not l: raise HTTPException(422, f"Line {r.line_id} is not on {po.po_number}")
        if r.qty > l.qty - l.received: raise HTTPException(409, f"{l.sku}: only {l.qty - l.received} {l.unit} outstanding on {po.po_number}")
        it = db.get(m.FurnitureItem, l.item_id)
        catlib.move_stock(db, it, r.qty, f"Received on {po.po_number}", user, ref_type="PO", ref_id=po.id, project_id=project.id)
        catlib.move_stock(db, it, -r.qty, f"Allocated to {project.project_number} ({qno}) from {po.po_number}", user, ref_type="ALLOC", ref_id=po.boq_id, project_id=project.id)
        l.received += r.qty; got.append(f"{l.sku} × {r.qty}")
    po.status = "RECEIVED" if all(l.received >= l.qty for l in mine.values()) else "PARTIAL"
    flow.event(db, project.id, "PROCUREMENT", f"Goods received on {po.po_number}: {', '.join(got)} ({po.status.lower()})", user, "PO", po.id)
    db.commit(); return po_out(db, po)


@router.get("/purchase-orders/{poid}/pdf")
def po_pdf(poid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    po = _po(db, poid); o = po_out(db, po); s = db.get(m.Supplier, po.supplier_id); p = db.get(m.Project, po.project_id)
    pdf = doc_pdf.render(company=companylib.get(db), title="Purchase Order", number=po.po_number,
                         meta=[("Status", po.status), ("Date", (po.issued_at or po.created_at).date().isoformat()), ("Expected delivery", o["expected_on"] or "To be confirmed"),
                               ("Project", f"{p.project_number} · {p.name}")],
                         parties=[("Supplier", [s.name, s.contact_person, s.address, s.city, s.phone, f"GSTIN {s.gstin}" if s.gstin else None]),
                                  ("Deliver to", [p.site_address or "Our workshop / as instructed", f"Ref. {p.project_number}"])],
                         header=["#", "SKU", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"], widths=[8, 32, 70, 18, 24, 26], right_cols=(3, 4, 5),
                         rows=[[str(i), l["sku"], l["description"], f"{l['qty']} {l['unit']}", inr(l["rate"]), inr(l["amount"])] for i, l in enumerate(o["lines"], 1)],
                         totals=[("Total (before tax)", inr(o["total"]))],
                         paragraphs=[f"Notes: {po.notes}" if po.notes else "", "Please quote the PO number on your invoice and delivery challan. Taxes as applicable."],
                         signatures=("Accepted by supplier", "Authorised signatory"))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{po.po_number}.pdf"'})


@router.get("/inventory/movements")
def movements(item_id: str | None = None, project_id: str | None = None, limit: int = 200, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    q = db.query(m.StockMovement, m.FurnitureItem).join(m.FurnitureItem, m.FurnitureItem.id == m.StockMovement.item_id)
    if item_id: q = q.filter(m.StockMovement.item_id == item_id)
    if project_id: q = q.filter(m.StockMovement.project_id == project_id)
    q = access.scope(q, m.StockMovement.project_id, db, user)
    rows = q.order_by(m.StockMovement.created_at.desc()).limit(max(1, min(limit, 1000))).all()
    return [{"id": s.id, "item_id": i.id, "sku": i.sku, "name": i.name, "unit": i.unit or "No.", "delta": s.delta, "balance": s.balance, "reason": s.reason,
             "ref_type": s.ref_type, "project_id": s.project_id, "user_name": s.user_name, "created_at": _iso(s.created_at)} for s, i in rows]


# ── Manufacturing ─────────────────────────────────────────────────────────────
def wo_out(db: Session, w: m.WorkOrder) -> dict:
    p = db.get(m.Project, w.project_id)
    return {"id": w.id, "wo_number": w.wo_number, "project_id": p.id, "project_number": p.project_number, "project_name": p.name, "boq_id": w.boq_id,
            "sku": w.sku, "description": w.description, "unit_no": w.unit_no, "stage": w.stage, "cut_list": w.cut_list, "updated_at": _iso(w.updated_at)}


@router.post("/boqs/{bid}/work-orders")
def create_work_orders(bid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MFG))):
    """One work order (with its cutting list) per unit of every in-house item on an approved quotation. Running it again adds only missing units."""
    b = _boq(db, bid); _approved(db, b); project = flow.project_of_boq(db, b); _locked(db, project.id)
    made = []
    for r in fulfilment.lines(db, b):
        if r["kind"] != "MANUFACTURED": continue
        have = db.query(m.WorkOrder).filter_by(boq_id=b.id, sku=r["sku"]).count()
        L, W, H = r["size"]; cl = cutting.cut_list(L, W, H)
        for n in range(have + 1, r["qty"] + 1):
            w = m.WorkOrder(wo_number=flow.next_number(db, m.WorkOrder, m.WorkOrder.wo_number, f"WO-{project.project_number}", 3), project_id=project.id, boq_id=b.id,
                            sku=r["sku"], description=r["description"], unit_no=n, cut_list=cl, updated_by=user.get("name"))
            db.add(w); db.flush(); made.append(w)
    if made: flow.event(db, project.id, "MANUFACTURING", f"{len(made)} work order(s) created from {_qno(db, b)}", user, "BOQ", b.id)
    db.commit(); return {"created": [wo_out(db, w) for w in made]}


@router.get("/work-orders")
def list_wos(project_id: str | None = None, stage: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    q = access.scope(db.query(m.WorkOrder), m.WorkOrder.project_id, db, user)
    if project_id: q = q.filter_by(project_id=project_id)
    if stage: q = q.filter_by(stage=stage)
    return [wo_out(db, w) for w in q.order_by(m.WorkOrder.wo_number)]


class StageIn(_In):
    stage: str


@router.post("/work-orders/{wid}/stage")
def wo_stage(wid: str, body: StageIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MFG))):
    w = db.get(m.WorkOrder, wid)
    if not w: raise HTTPException(404, "Work order not found")
    _locked(db, w.project_id)
    if body.stage not in WO_STAGES: raise HTTPException(422, f"stage must be one of {', '.join(WO_STAGES)}")
    if body.stage == w.stage: return wo_out(db, w)
    if WO_STAGES.index(body.stage) < WO_STAGES.index(w.stage):
        booked = fulfilment.delivered_map(db, w.boq_id).get(w.sku, 0)
        ready = db.query(m.WorkOrder).filter_by(boq_id=w.boq_id, sku=w.sku, stage="READY").count()
        if w.stage == "READY" and ready - 1 < booked: raise HTTPException(409, f"{w.wo_number} is already booked on a delivery; cancel that delivery first")
    old, w.stage, w.updated_by = w.stage, body.stage, user.get("name")
    project = db.get(m.Project, w.project_id)
    flow.event(db, project.id, "MANUFACTURING", f"{w.wo_number} {w.description} (unit {w.unit_no}): {old} → {body.stage}", user, "WO", w.id)
    if body.stage != "PENDING": flow.advance(db, project, "MANUFACTURING", user, f"{w.wo_number} started")
    db.commit(); return wo_out(db, w)


@router.get("/projects/{pid}/cutting")
def project_cutting(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); out = []
    for b in _approved_boqs(db, pid):
        need = fulfilment.board_need(db, b)
        items = [{"sku": r["sku"], "description": r["description"], "qty": r["qty"], "cut_list": cutting.cut_list(*r["size"])}
                 for r in fulfilment.lines(db, b) if r["kind"] == "MANUFACTURED"]
        out.append({"boq": quotation_row(db, b), "items": items, "sheets": {str(k): v for k, v in need["sheets"].items()}, "edge_band_m": need["edge_band_m"]})
    return out


# ── Delivery ──────────────────────────────────────────────────────────────────
def dn_out(db: Session, d: m.DeliveryNote) -> dict:
    p = db.get(m.Project, d.project_id)
    lines = db.query(m.DeliveryLine).filter_by(dn_id=d.id).all()
    return {"id": d.id, "dn_number": d.dn_number, "status": d.status, "project_id": p.id, "project_number": p.project_number, "project_name": p.name, "boq_id": d.boq_id,
            "scheduled_on": d.scheduled_on.date().isoformat() if d.scheduled_on else None, "vehicle": d.vehicle, "driver": d.driver, "received_by": d.received_by,
            "delivered_at": _iso(d.delivered_at), "created_at": _iso(d.created_at),
            "lines": [{"sku": l.sku, "description": l.description, "unit": l.unit, "qty": l.qty} for l in lines]}


@router.get("/projects/{pid}/deliverable")
def deliverable(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); out = []
    for b in _approved_boqs(db, pid):
        rows = fulfilment.lines(db, b)
        for r in rows: r.pop("size", None)
        out.append({"boq": quotation_row(db, b), "lines": rows})
    return out


class DLine(_In):
    sku: str | None = None
    description: str | None = None
    qty: int = Field(ge=1, le=100_000)


class DeliveryIn(_In):
    boq_id: str
    scheduled_on: date
    vehicle: str | None = Field(None, max_length=40)
    driver: str | None = Field(None, max_length=80)
    lines: list[DLine] = Field(min_length=1)


@router.post("/projects/{pid}/deliveries", status_code=201)
def create_delivery(pid: str, body: DeliveryIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*DELIV))):
    p = _project(db, pid); _locked(db, pid); b = _boq(db, body.boq_id); _approved(db, b)
    if flow.project_of_boq(db, b).id != pid: raise HTTPException(409, "That quotation belongs to another project")
    avail = {(r["sku"] or r["description"]): r for r in fulfilment.lines(db, b)}
    seen = set()
    for l in body.lines:
        key = l.sku or l.description
        r = avail.get(key)
        if not r: raise HTTPException(422, f"{key} is not on {_qno(db, b)}")
        if key in seen: raise HTTPException(422, f"{key} is listed twice")
        seen.add(key)
        if l.qty > r["deliverable"]:
            why = {"MANUFACTURED": f"{r['ready']} of {r['qty']} made (READY)", "BOUGHT_OUT": f"{r['ready']} of {r['qty']} received/allocated", "MANUAL": ""}[r["kind"]]
            raise HTTPException(409, f"{r['description']}: only {r['deliverable']} can be delivered now ({why}; {r['booked']} already on delivery notes).")
    d = m.DeliveryNote(dn_number=flow.next_number(db, m.DeliveryNote, m.DeliveryNote.dn_number, f"DN-{p.project_number}"), project_id=pid, boq_id=b.id,
                       scheduled_on=_dt(body.scheduled_on), vehicle=body.vehicle, driver=body.driver, created_by=user.get("sub"))
    db.add(d); db.flush()
    for l in body.lines:
        r = avail[l.sku or l.description]
        db.add(m.DeliveryLine(dn_id=d.id, sku=r["sku"], description=r["description"], unit=r["unit"], qty=l.qty))
    flow.event(db, pid, "DELIVERY", f"{d.dn_number} scheduled for {body.scheduled_on.isoformat()} ({len(body.lines)} line(s))", user, "DN", d.id)
    db.commit(); return dn_out(db, d)


@router.get("/deliveries")
def list_deliveries(project_id: str | None = None, status: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    q = access.scope(db.query(m.DeliveryNote), m.DeliveryNote.project_id, db, user)
    if project_id: q = q.filter_by(project_id=project_id)
    if status: q = q.filter_by(status=status)
    return [dn_out(db, d) for d in q.order_by(m.DeliveryNote.created_at.desc())]


def _dn(db: Session, did: str) -> m.DeliveryNote:
    d = db.get(m.DeliveryNote, did)
    if not d: raise HTTPException(404, "Delivery note not found")
    _locked(db, d.project_id); return d


@router.post("/deliveries/{did}/dispatch")
def dispatch(did: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*DELIV))):
    d = _dn(db, did)
    if d.status != "SCHEDULED": raise HTTPException(409, f"{d.dn_number} is {d.status}")
    d.status = "DISPATCHED"; p = db.get(m.Project, d.project_id)
    flow.event(db, p.id, "DELIVERY", f"{d.dn_number} dispatched" + (f" ({d.vehicle})" if d.vehicle else ""), user, "DN", d.id)
    flow.advance(db, p, "DELIVERY", user, f"{d.dn_number} dispatched")
    notify.auto(db, "DELIVERY", d.id, user)
    db.commit(); return dn_out(db, d)


class DeliveredIn(_In):
    received_by: str = Field(min_length=2, max_length=120)


@router.post("/deliveries/{did}/deliver")
def mark_delivered(did: str, body: DeliveredIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*DELIV))):
    d = _dn(db, did)
    if d.status != "DISPATCHED": raise HTTPException(409, f"{d.dn_number} is {d.status}; dispatch it first")
    d.status, d.received_by, d.delivered_at = "DELIVERED", body.received_by.strip(), flow.now()
    p = db.get(m.Project, d.project_id)
    for l in db.query(m.DeliveryLine).filter_by(dn_id=d.id):           # each delivered item becomes (or adds to) an installation task
        t = db.query(m.InstallTask).filter_by(project_id=p.id, sku=l.sku, title=f"Install {l.description}").first()
        if t:
            t.qty += l.qty
            if t.status == "DONE": t.status = "PENDING"
        else: db.add(m.InstallTask(project_id=p.id, sku=l.sku, title=f"Install {l.description}", qty=l.qty))
    flow.event(db, p.id, "DELIVERY", f"{d.dn_number} delivered, received by {d.received_by}", user, "DN", d.id)
    flow.advance(db, p, "DELIVERY", user, f"{d.dn_number} delivered")
    db.commit(); return dn_out(db, d)


@router.post("/deliveries/{did}/cancel")
def cancel_delivery(did: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*DELIV))):
    d = _dn(db, did)
    if d.status not in ("SCHEDULED", "DISPATCHED"): raise HTTPException(409, f"{d.dn_number} is {d.status}; a delivered note can't be cancelled")
    d.status = "CANCELLED"; flow.event(db, d.project_id, "DELIVERY", f"{d.dn_number} cancelled", user, "DN", d.id)
    db.commit(); return dn_out(db, d)


@router.get("/deliveries/{did}/pdf")
def dn_pdf(did: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    d = db.get(m.DeliveryNote, did)
    if not d: raise HTTPException(404, "Delivery note not found")
    o = dn_out(db, d); p = db.get(m.Project, d.project_id); c = db.get(m.Client, p.client_id) if p.client_id else None
    pdf = doc_pdf.render(company=companylib.get(db), title="Delivery Challan", number=d.dn_number,
                         meta=[("Status", d.status), ("Scheduled", o["scheduled_on"] or ""), ("Vehicle / driver", " / ".join(x for x in (d.vehicle, d.driver) if x) or "—"),
                               ("Project", f"{p.project_number} · {p.name}")],
                         parties=[("Deliver to", [c.name if c else "Client", p.site_address or (c.address if c else None), c.city if c else None, c.phone if c else None])],
                         header=["#", "SKU", "Description", "Qty"], widths=[10, 40, 100, 28], right_cols=(3,),
                         rows=[[str(i), l["sku"] or "—", l["description"], f"{l['qty']} {l['unit']}"] for i, l in enumerate(o["lines"], 1)],
                         paragraphs=["Goods received in good condition unless noted on this challan at the time of delivery."],
                         signatures=("Received by (signature, name, date)", "Dispatched by"))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{d.dn_number}.pdf"'})


# ── Installation ──────────────────────────────────────────────────────────────
def task_out(db: Session, t: m.InstallTask, users: dict) -> dict:
    return {"id": t.id, "project_id": t.project_id, "sku": t.sku, "title": t.title, "qty": t.qty, "status": t.status, "assigned_to": t.assigned_to,
            "assigned_name": users.get(t.assigned_to), "note": t.note, "updated_by": t.updated_by, "updated_at": _iso(t.updated_at)}


def _users(db: Session) -> dict: return {u.id: u.full_name for u in db.query(m.User)}


@router.get("/projects/{pid}/install-tasks")
def list_tasks(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); us = _users(db)
    return [task_out(db, t, us) for t in db.query(m.InstallTask).filter_by(project_id=pid).order_by(m.InstallTask.created_at)]


class TaskPatch(_In):
    status: str | None = None
    assigned_to: str | None = None
    note: str | None = Field(None, max_length=1000)


def _all_installed(db: Session, pid: str) -> bool:
    tasks = db.query(m.InstallTask).filter_by(project_id=pid).all()
    return bool(tasks) and all(t.status == "DONE" for t in tasks) and all(fulfilment.fully_delivered(db, b) for b in _approved_boqs(db, pid))


@router.patch("/install-tasks/{tid}")
def patch_task(tid: str, body: TaskPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*INSTALL))):
    t = db.get(m.InstallTask, tid)
    if not t: raise HTTPException(404, "Installation task not found")
    _locked(db, t.project_id); data = body.model_dump(exclude_unset=True); p = db.get(m.Project, t.project_id)
    if "status" in data:
        if body.status not in ("PENDING", "IN_PROGRESS", "DONE"): raise HTTPException(422, "status must be PENDING, IN_PROGRESS or DONE")
        if body.status != t.status:
            flow.event(db, p.id, "INSTALLATION", f"{t.title} × {t.qty}: {t.status} → {body.status}", user, "TASK", t.id)
            t.status = body.status
            if body.status in ("IN_PROGRESS", "DONE"): flow.advance(db, p, "INSTALLATION", user, f"{t.title} started")
    if "assigned_to" in data:
        if body.assigned_to and not db.get(m.User, body.assigned_to): raise HTTPException(404, "User not found")
        t.assigned_to = body.assigned_to or None
    if "note" in data: t.note = body.note
    t.updated_by = user.get("name"); db.flush()
    if _all_installed(db, p.id): flow.advance(db, p, "QC", user, "everything delivered and installed")
    db.commit(); return task_out(db, t, _users(db))


# ── QC + snags ────────────────────────────────────────────────────────────────
def readiness(db: Session, pid: str) -> dict:
    blockers = []
    boqs = _approved_boqs(db, pid)
    if not boqs: blockers.append("No approved quotation")
    for b in boqs:
        short = [f"{r['description']} ({r['delivered']}/{r['qty']})" for r in fulfilment.lines(db, b) if r["delivered"] < r["qty"]]
        if short: blockers.append(f"Not yet delivered on {_qno(db, b)}: " + ", ".join(short))
    tasks = db.query(m.InstallTask).filter_by(project_id=pid).all()
    open_t = [t.title for t in tasks if t.status != "DONE"]
    if boqs and not tasks: blockers.append("No installation recorded")
    if open_t: blockers.append(f"{len(open_t)} installation task(s) not done")
    checks = db.query(m.QCCheck).filter_by(project_id=pid).all()
    if not checks: blockers.append("QC inspection not started")
    bad = [c for c in checks if c.status != "PASS"]
    if bad: blockers.append(f"{len(bad)} QC check(s) not passed")
    snags = db.query(m.Snag).filter_by(project_id=pid, status="OPEN").count()
    if snags: blockers.append(f"{snags} open snag(s)")
    pay = payment_summary(db, pid)
    return {"ready": not blockers, "blockers": blockers, "balance_due": pay["balance"]}


def qc_out(db: Session, pid: str) -> dict:
    us = _users(db)
    checks = db.query(m.QCCheck).filter_by(project_id=pid).order_by(m.QCCheck.source.desc(), m.QCCheck.created_at).all()
    snags = db.query(m.Snag).filter_by(project_id=pid).order_by(m.Snag.created_at.desc()).all()
    return {"checks": [{"id": c.id, "title": c.title, "source": c.source, "status": c.status, "note": c.note, "checked_by": c.checked_by, "checked_at": _iso(c.checked_at)} for c in checks],
            "snags": [{"id": s.id, "check_id": s.check_id, "title": s.title, "status": s.status, "raised_by": s.raised_by, "fixed_by": s.fixed_by, "fix_note": s.fix_note,
                       "created_at": _iso(s.created_at), "fixed_at": _iso(s.fixed_at)} for s in snags],
            "readiness": readiness(db, pid), "installed": _all_installed(db, pid)}


@router.get("/projects/{pid}/qc")
def get_qc(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); return qc_out(db, pid)


@router.post("/projects/{pid}/qc/start")
def start_qc(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*QC))):
    p = _project(db, pid); _locked(db, pid)
    if not _all_installed(db, pid): raise HTTPException(409, "QC starts after everything is delivered and every installation task is DONE.")
    have = {c.title for c in db.query(m.QCCheck).filter_by(project_id=pid)}
    added = 0
    for t in db.query(m.InstallTask).filter_by(project_id=pid):
        title = f"{t.title.replace('Install ', '', 1)} × {t.qty} installed correctly"
        if title not in have: db.add(m.QCCheck(project_id=pid, title=title, source="TASK")); added += 1
    for title in STANDARD_QC:
        if title not in have: db.add(m.QCCheck(project_id=pid, title=title, source="STANDARD")); added += 1
    if added: flow.event(db, pid, "QC", f"QC inspection started ({added} check(s))", user)
    flow.advance(db, p, "QC", user, "QC inspection started")
    db.commit(); return qc_out(db, pid)


class CheckIn(_In):
    title: str = Field(min_length=3, max_length=200)


@router.post("/projects/{pid}/qc/checks", status_code=201)
def add_check(pid: str, body: CheckIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*QC))):
    _project(db, pid); _locked(db, pid)
    db.add(m.QCCheck(project_id=pid, title=body.title.strip(), source="CUSTOM")); db.commit(); return qc_out(db, pid)


class ResultIn(_In):
    status: str
    note: str | None = Field(None, max_length=1000)


@router.post("/qc-checks/{cid}")
def record_check(cid: str, body: ResultIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*QC))):
    c = db.get(m.QCCheck, cid)
    if not c: raise HTTPException(404, "QC check not found")
    _locked(db, c.project_id)
    if body.status not in ("PASS", "FAIL"): raise HTTPException(422, "status must be PASS or FAIL")
    if body.status == "FAIL" and not (body.note and body.note.strip()): raise HTTPException(422, [{"loc": ["body", "note"], "msg": "Describe what failed (it becomes a snag)", "type": "value_error"}])
    if body.status == "PASS" and db.query(m.Snag).filter_by(check_id=c.id, status="OPEN").first(): raise HTTPException(409, "Fix the open snag on this check first")
    c.status, c.note, c.checked_by, c.checked_at = body.status, (body.note or "").strip() or None, user.get("name"), flow.now()
    if body.status == "FAIL":
        db.add(m.Snag(project_id=c.project_id, check_id=c.id, title=f"{c.title}: {c.note}", raised_by=user.get("name")))
        flow.event(db, c.project_id, "QC", f"QC failed — {c.title}: {c.note} (snag raised)", user, "QC", c.id)
    else: flow.event(db, c.project_id, "QC", f"QC passed — {c.title}", user, "QC", c.id)
    db.commit(); return qc_out(db, c.project_id)


class FixIn(_In):
    note: str = Field(min_length=3, max_length=1000)


@router.post("/snags/{sid}/fix")
def fix_snag(sid: str, body: FixIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*SNAG_FIX))):
    s = db.get(m.Snag, sid)
    if not s: raise HTTPException(404, "Snag not found")
    _locked(db, s.project_id)
    if s.status != "OPEN": raise HTTPException(409, "This snag is already fixed")
    s.status, s.fixed_by, s.fix_note, s.fixed_at = "FIXED", user.get("name"), body.note.strip(), flow.now()
    if s.check_id:
        c = db.get(m.QCCheck, s.check_id); c.status = "PENDING"           # must be re-inspected
    flow.event(db, s.project_id, "QC", f"Snag fixed — {s.title}: {s.fix_note} (re-inspection needed)", user, "SNAG", s.id)
    db.commit(); return qc_out(db, s.project_id)


# ── Handover ──────────────────────────────────────────────────────────────────
class HandoverIn(_In):
    received_by: str = Field(min_length=2, max_length=120)
    handed_over_on: date | None = None
    warranty_months: int | None = Field(None, ge=0, le=120)
    notes: str | None = Field(None, max_length=2000)


def handover_out(db: Session, pid: str) -> dict:
    h = db.query(m.Handover).filter_by(project_id=pid).first()
    return {"handover": None if not h else {"received_by": h.received_by, "handed_over_on": h.handed_over_on.date().isoformat(), "warranty_months": h.warranty_months,
                                           "notes": h.notes, "user_name": h.user_name},
            "readiness": readiness(db, pid) if not h else {"ready": True, "blockers": [], "balance_due": payment_summary(db, pid)["balance"]}}


@router.get("/projects/{pid}/handover")
def get_handover(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid); return handover_out(db, pid)


@router.post("/projects/{pid}/handover", status_code=201)
def do_handover(pid: str, body: HandoverIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*HANDOVER))):
    p = _project(db, pid); _locked(db, pid)
    r = readiness(db, pid)
    if not r["ready"]: raise HTTPException(409, "Not ready for handover: " + "; ".join(r["blockers"]))
    when = body.handed_over_on or date.today()
    if when > date.today(): raise HTTPException(422, "Handover date can't be in the future")
    h = m.Handover(project_id=pid, received_by=body.received_by.strip(), handed_over_on=_dt(when),
                   warranty_months=body.warranty_months if body.warranty_months is not None else int(companylib.get(db)["warranty_months"]),
                   notes=body.notes, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(h)
    flow.event(db, pid, "HANDOVER", f"Handed over to {h.received_by}; warranty {h.warranty_months} months", user)
    flow.advance(db, p, "COMPLETED", user, "handed over to the client")
    db.flush(); notify.auto(db, "HANDOVER", pid, user)
    db.commit(); return handover_out(db, pid)


@router.get("/projects/{pid}/handover.pdf")
def handover_pdf(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    p = _project(db, pid); h = db.query(m.Handover).filter_by(project_id=pid).first()
    if not h: raise HTTPException(409, "This project has not been handed over yet")
    c = db.get(m.Client, p.client_id) if p.client_id else None
    items = []
    for b in _approved_boqs(db, pid):
        items += [[str(len(items) + 1), r["sku"] or "—", r["description"], f"{r['delivered']} {r['unit']}"] for r in fulfilment.lines(db, b)]
    checks = db.query(m.QCCheck).filter_by(project_id=pid).count()
    pdf = doc_pdf.render(company=companylib.get(db), title="Handover Certificate", number=f"HO-{p.project_number}",
                         meta=[("Project", f"{p.project_number} · {p.name}"), ("Handed over on", h.handed_over_on.date().isoformat()),
                               ("Received by", h.received_by), ("Warranty", f"{h.warranty_months} months from handover")],
                         parties=[("Client", [c.name if c else "—", c.company if c else None, p.site_address or (c.address if c else None), c.city if c else None])],
                         header=["#", "SKU", "Item", "Installed"], widths=[10, 40, 100, 28], right_cols=(3,), rows=items,
                         paragraphs=[f"All {checks} quality checks passed and every snag was closed before handover.", f"Notes: {h.notes}" if h.notes else "",
                                     "The client confirms the works above were received complete and in good condition."],
                         signatures=("Client (signature and date)", "Project manager"))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="HO-{p.project_number}.pdf"'})


# ── Timeline + overview ───────────────────────────────────────────────────────
@router.get("/projects/{pid}/timeline")
def timeline(pid: str, limit: int = 200, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _project(db, pid)
    rows = db.query(m.ProjectEvent).filter_by(project_id=pid).order_by(m.ProjectEvent.created_at.desc()).limit(max(1, min(limit, 1000)))
    return [{"id": e.id, "kind": e.kind, "text": e.text, "user_name": e.user_name, "created_at": _iso(e.created_at)} for e in rows]


def overview(db: Session, pid: str) -> dict:
    p = _project(db, pid); c = db.get(m.Client, p.client_id) if p.client_id else None
    wos = db.query(m.WorkOrder).filter_by(project_id=pid).all()
    pos = db.query(m.PurchaseOrder).filter(m.PurchaseOrder.project_id == pid, m.PurchaseOrder.status != "CANCELLED").all()
    dns = db.query(m.DeliveryNote).filter(m.DeliveryNote.project_id == pid, m.DeliveryNote.status != "CANCELLED").all()
    tasks = db.query(m.InstallTask).filter_by(project_id=pid).all()
    checks = db.query(m.QCCheck).filter_by(project_id=pid).all()
    return {"id": p.id, "project_number": p.project_number, "name": p.name, "status": p.status or "LEAD", "progress": p.progress or 0, "archived": bool(p.archived),
            "client_name": c.name if c else None, "site_address": p.site_address, "target_date": p.target_date.date().isoformat() if p.target_date else None,
            "stages": m.PROJECT_STAGES, "stage_index": flow.stage_index(p.status),
            "quotations": [quotation_row(db, b) for b in db.query(m.Boq).filter(m.Boq.room_id.in_([r.id for r in db.query(m.Room.id).filter_by(project_id=pid)])).order_by(m.Boq.created_at.desc())],
            "payments": payment_summary(db, pid),
            "procurement": {"pos": len(pos), "open": sum(x.status in ("DRAFT", "ISSUED", "PARTIAL") for x in pos), "received": sum(x.status == "RECEIVED" for x in pos)},
            "manufacturing": {"work_orders": len(wos), "ready": sum(w.stage == "READY" for w in wos)},
            "delivery": {"notes": len(dns), "delivered": sum(d.status == "DELIVERED" for d in dns)},
            "installation": {"tasks": len(tasks), "done": sum(t.status == "DONE" for t in tasks)},
            "qc": {"checks": len(checks), "passed": sum(x.status == "PASS" for x in checks), "open_snags": db.query(m.Snag).filter_by(project_id=pid, status="OPEN").count()},
            "handover": handover_out(db, pid)["handover"]}


@router.get("/projects/{pid}/overview")
def get_overview(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))): return overview(db, pid)
