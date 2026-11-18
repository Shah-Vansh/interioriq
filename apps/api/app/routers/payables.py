"""Supplier bills, supplier payments, payables ageing and supplier statements."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import current_user, require_roles
from app.models import models as m
from app.services import access
from app.services import flow, payables as pay
from app.services.cost_engine import D, inr

def _company_wide(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    access.company_wide(db, user, "Payables")          # M22: supplier bills / payments / ageing cover every project


router = APIRouter(dependencies=[Depends(_company_wide)], tags=["Payables"])
READ = ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER")
BILLS = READ                                   # procurement records the bills it receives
PAY = ("ADMIN", "PROJECT_MANAGER")             # paying money out is restricted
MODES = ["BANK", "UPI", "CHEQUE", "CASH", "CARD"]


def _m(x) -> str: return f"{D(x):.2f}"


def bill_out(db: Session, b: m.SupplierBill, sups: dict | None = None) -> dict:
    s = (sups or {}).get(b.supplier_id) or db.get(m.Supplier, b.supplier_id)
    po = db.get(m.PurchaseOrder, b.po_id) if b.po_id else None; p = db.get(m.Project, b.project_id) if b.project_id else None
    paid = pay.paid_on_bill(db, b.id)
    return {"id": b.id, "supplier_id": b.supplier_id, "supplier_name": s.name if s else None, "bill_no": b.bill_no, "bill_date": pay._aware(b.bill_date).date().isoformat(),
            "due_date": pay._aware(b.due_date).date().isoformat(), "po_id": b.po_id, "po_number": po.po_number if po else None, "project_id": b.project_id,
            "project_number": p.project_number if p else None, "taxable": _m(b.taxable), "gst": _m(b.gst), "total": _m(b.total), "paid": _m(paid),
            "outstanding": _m(D(0) if b.status == "VOID" else D(b.total) - paid), "status": b.status, "match": b.match, "approve_reason": b.approve_reason,
            "overdue_days": max(0, (date.today() - pay._aware(b.due_date).date()).days) if b.status in ("OPEN", "PARTIAL") else 0,
            "note": b.note, "void_reason": b.void_reason, "user_name": b.user_name}


@router.get("/payables/summary")
def summary(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))): return pay.summary(db)


@router.get("/bills")
def list_bills(supplier_id: str | None = None, status: str | None = None, project_id: str | None = None, overdue: bool = False,
               db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    q = db.query(m.SupplierBill)
    if supplier_id: q = q.filter_by(supplier_id=supplier_id)
    if status == "UNPAID": q = q.filter(m.SupplierBill.status.in_(["OPEN", "PARTIAL"]))
    elif status: q = q.filter_by(status=status)
    if project_id: q = q.filter_by(project_id=project_id)
    sups = {s.id: s for s in db.query(m.Supplier)}
    rows = [bill_out(db, b, sups) for b in q.order_by(m.SupplierBill.due_date, m.SupplierBill.created_at)]
    return [r for r in rows if r["overdue_days"] > 0] if overdue else rows


@router.get("/bills/po-check")
def po_check(po_id: str, taxable: Decimal = Decimal(0), db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    po = db.get(m.PurchaseOrder, po_id)
    if not po: raise HTTPException(404, "Purchase order not found")
    s = db.get(m.Supplier, po.supplier_id)
    return {**pay.po_match(db, po, taxable), "supplier_id": po.supplier_id, "supplier_name": s.name, "project_id": po.project_id, "po_number": po.po_number,
            "payment_terms_days": s.payment_terms_days if s.payment_terms_days is not None else 30}


class BillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: str | None = None
    po_id: str | None = None
    project_id: str | None = None
    bill_no: str = Field(min_length=1, max_length=60)
    bill_date: date
    due_date: date | None = None
    taxable: Decimal = Field(ge=0, le=10_000_000_000, decimal_places=2)
    gst: Decimal = Field(default=Decimal(0), ge=0, le=10_000_000_000, decimal_places=2)
    note: str | None = Field(None, max_length=500)
    approve_reason: str | None = Field(None, max_length=500)

    @field_validator("bill_date")
    @classmethod
    def _d(cls, v):
        if v > date.today(): raise ValueError("A bill can't be dated in the future")
        return v


@router.post("/bills", status_code=201)
def create_bill(b: BillIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*BILLS))):
    po = db.get(m.PurchaseOrder, b.po_id) if b.po_id else None
    if b.po_id and not po: raise HTTPException(404, "Purchase order not found")
    if po and po.status in ("DRAFT", "CANCELLED"): raise HTTPException(409, f"{po.po_number} is {po.status}; bills are recorded against issued purchase orders")
    sid = po.supplier_id if po else b.supplier_id
    if po and b.supplier_id and b.supplier_id != po.supplier_id: raise HTTPException(422, f"{po.po_number} belongs to another supplier")
    s = db.get(m.Supplier, sid) if sid else None
    if not s: raise HTTPException(422, "Pick the supplier (or the purchase order)")
    pid = po.project_id if po else b.project_id
    if pid and not db.get(m.Project, pid): raise HTTPException(404, "Project not found")
    bill_no = b.bill_no.strip()
    dup = db.query(m.SupplierBill).filter(m.SupplierBill.supplier_id == s.id, func.lower(m.SupplierBill.bill_no) == bill_no.lower(), m.SupplierBill.status != "VOID").first()
    if dup: raise HTTPException(409, f"Bill {dup.bill_no} from {s.name} is already recorded (duplicate)")
    if b.taxable + b.gst <= 0: raise HTTPException(422, "The bill total must be more than 0")
    due = b.due_date or pay.due_date(b.bill_date, s)
    if due < b.bill_date: raise HTTPException(422, "Due date can't be before the bill date")
    match = "NO_PO"
    if po:
        mt = pay.po_match(db, po, b.taxable); match = mt["status"]
        if match == "OVER_BILLED" and not (b.approve_reason and b.approve_reason.strip()):
            raise HTTPException(409, f"This bill takes {po.po_number} to Rs. {inr(mt['billed_after'])} billed, but only Rs. {inr(mt['received'])} of goods were received. "
                                     "Record the goods receipt first, or give an approval reason to accept it.")
    bill = m.SupplierBill(supplier_id=s.id, bill_no=bill_no, bill_date=pay.dt(b.bill_date), due_date=pay.dt(due), po_id=po.id if po else None, project_id=pid,
                          taxable=b.taxable, gst=b.gst, total=b.taxable + b.gst, match=match, approve_reason=(b.approve_reason or "").strip() or None,
                          note=(b.note or "").strip() or None, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(bill); db.flush()
    if pid: flow.event(db, pid, "PAYABLE", f"Supplier bill {bill_no} from {s.name}: Rs. {inr(bill.total)} ({match.replace('_', ' ').lower()})", user, "BILL", bill.id)
    db.commit(); return bill_out(db, bill)


@router.get("/bills/{bid}")
def get_bill(bid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    b = db.get(m.SupplierBill, bid)
    if not b: raise HTTPException(404, "Bill not found")
    allocs = (db.query(m.PaymentAllocation, m.SupplierPayment).join(m.SupplierPayment, m.SupplierPayment.id == m.PaymentAllocation.payment_id)
              .filter(m.PaymentAllocation.bill_id == bid).all())
    return {**bill_out(db, b), "payments": [{"payment_id": p.id, "amount": _m(a.amount), "paid_on": pay._aware(p.paid_on).date().isoformat(), "mode": p.mode,
                                            "reference": p.reference, "status": p.status} for a, p in allocs]}


class VoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


@router.post("/bills/{bid}/void")
def void_bill(bid: str, b: VoidIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*BILLS))):
    bill = db.get(m.SupplierBill, bid)
    if not bill: raise HTTPException(404, "Bill not found")
    if bill.status == "VOID": raise HTTPException(409, "This bill is already void")
    if pay.paid_on_bill(db, bid) > 0: raise HTTPException(409, "Payments are allocated to this bill — void those payments first")
    bill.status, bill.void_reason = "VOID", b.reason.strip()
    if bill.project_id: flow.event(db, bill.project_id, "PAYABLE", f"Supplier bill {bill.bill_no} voided: {bill.void_reason}", user, "BILL", bill.id)
    db.commit(); return bill_out(db, bill)


class AllocIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bill_id: str
    amount: Decimal = Field(gt=0, decimal_places=2)


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: str
    amount: Decimal = Field(gt=0, le=10_000_000_000, decimal_places=2)
    paid_on: date
    mode: str
    reference: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=500)
    allocations: list[AllocIn] | None = None            # omit → oldest due bills first

    @field_validator("mode")
    @classmethod
    def _mo(cls, v):
        if v not in MODES: raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return v

    @field_validator("paid_on")
    @classmethod
    def _d(cls, v):
        if v > date.today(): raise ValueError("A payment can't be dated in the future")
        return v


def pay_out(db: Session, p: m.SupplierPayment) -> dict:
    allocs = db.query(m.PaymentAllocation).filter_by(payment_id=p.id).all()
    bills = {b.id: b for b in db.query(m.SupplierBill).filter(m.SupplierBill.id.in_([a.bill_id for a in allocs]))} if allocs else {}
    s = db.get(m.Supplier, p.supplier_id)
    return {"id": p.id, "supplier_id": p.supplier_id, "supplier_name": s.name if s else None, "amount": _m(p.amount), "paid_on": pay._aware(p.paid_on).date().isoformat(),
            "mode": p.mode, "reference": p.reference, "note": p.note, "status": p.status, "void_reason": p.void_reason, "user_name": p.user_name,
            "allocations": [{"bill_id": a.bill_id, "bill_no": bills[a.bill_id].bill_no if a.bill_id in bills else None, "amount": _m(a.amount)} for a in allocs]}


@router.post("/supplier-payments", status_code=201)
def create_payment(b: PaymentIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PAY))):
    s = db.get(m.Supplier, b.supplier_id)
    if not s: raise HTTPException(404, "Supplier not found")
    owed = sum((pay.outstanding(db, x) for x in db.query(m.SupplierBill).filter(m.SupplierBill.supplier_id == s.id, m.SupplierBill.status.in_(["OPEN", "PARTIAL"]))), Decimal(0))
    if b.amount > owed: raise HTTPException(409, f"We owe {s.name} only Rs. {inr(owed)}; record the supplier's bill before paying more (advances aren't supported).")
    if b.allocations:
        if sum((a.amount for a in b.allocations), Decimal(0)) != b.amount: raise HTTPException(422, "The allocations must add up to the payment amount")
        plan, seen = [], set()
        for a in b.allocations:
            bill = db.get(m.SupplierBill, a.bill_id)
            if not bill or bill.supplier_id != s.id: raise HTTPException(422, "Every allocated bill must belong to this supplier")
            if a.bill_id in seen: raise HTTPException(422, f"Bill {bill.bill_no} is listed twice")
            seen.add(a.bill_id)
            if bill.status not in ("OPEN", "PARTIAL"): raise HTTPException(409, f"Bill {bill.bill_no} is {bill.status}")
            o = pay.outstanding(db, bill)
            if a.amount > o: raise HTTPException(409, f"Bill {bill.bill_no} has only Rs. {inr(o)} outstanding")
            plan.append((bill, a.amount))
    else: plan = pay.auto_allocate(db, s.id, b.amount)
    p = m.SupplierPayment(supplier_id=s.id, amount=b.amount, paid_on=pay.dt(b.paid_on), mode=b.mode, reference=(b.reference or "").strip() or None,
                          note=(b.note or "").strip() or None, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(p); db.flush()
    for bill, amt in plan:
        db.add(m.PaymentAllocation(payment_id=p.id, bill_id=bill.id, amount=amt)); db.flush(); pay.refresh_status(db, bill)
        if bill.project_id: flow.event(db, bill.project_id, "PAYABLE", f"Paid {s.name} Rs. {inr(amt)} against bill {bill.bill_no} ({b.mode})", user, "BILL", bill.id)
    db.commit(); return pay_out(db, p)


@router.get("/supplier-payments")
def list_payments(supplier_id: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    q = db.query(m.SupplierPayment)
    if supplier_id: q = q.filter_by(supplier_id=supplier_id)
    return [pay_out(db, p) for p in q.order_by(m.SupplierPayment.paid_on.desc(), m.SupplierPayment.created_at.desc())]


@router.post("/supplier-payments/{pid}/void")
def void_payment(pid: str, b: VoidIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*PAY))):
    p = db.get(m.SupplierPayment, pid)
    if not p: raise HTTPException(404, "Payment not found")
    if p.status == "VOID": raise HTTPException(409, "This payment is already void")
    p.status, p.void_reason = "VOID", b.reason.strip(); db.flush()
    for a in db.query(m.PaymentAllocation).filter_by(payment_id=p.id):
        bill = db.get(m.SupplierBill, a.bill_id); pay.refresh_status(db, bill)
        if bill.project_id: flow.event(db, bill.project_id, "PAYABLE", f"Supplier payment Rs. {inr(a.amount)} on bill {bill.bill_no} voided: {p.void_reason}", user, "BILL", bill.id)
    db.commit(); return pay_out(db, p)


@router.get("/suppliers/{sid}/statement")
def supplier_statement(sid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    s = db.get(m.Supplier, sid)
    if not s: raise HTTPException(404, "Supplier not found")
    return {"supplier_id": s.id, "supplier_name": s.name, "payment_terms_days": s.payment_terms_days if s.payment_terms_days is not None else 30, **pay.statement(db, sid)}
