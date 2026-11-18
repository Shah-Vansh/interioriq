"""Payables: what we owe suppliers. Decimal only; balances are always recomputed from bills and (active) payment allocations."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import models as m
from app.services.cost_engine import D, q

ZERO = Decimal("0.00")
TOLERANCE_PCT = Decimal("1")          # billing up to 1% (or Rs. 1) over the received value still counts as matched (rounding, freight paise)
BUCKETS = [("not_due", "Not due yet"), ("d0_30", "1–30 days overdue"), ("d31_60", "31–60 days"), ("d61_90", "61–90 days"), ("d90_plus", "Over 90 days")]


def dt(d: date) -> datetime: return datetime.combine(d, time(12), tzinfo=timezone.utc)


def _aware(t): return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def paid_on_bill(db: Session, bill_id: str) -> Decimal:
    v = (db.query(func.coalesce(func.sum(m.PaymentAllocation.amount), 0)).join(m.SupplierPayment, m.SupplierPayment.id == m.PaymentAllocation.payment_id)
         .filter(m.PaymentAllocation.bill_id == bill_id, m.SupplierPayment.status == "ACTIVE").scalar())
    return D(v or 0)


def outstanding(db: Session, b: m.SupplierBill) -> Decimal:
    return ZERO if b.status == "VOID" else D(b.total) - paid_on_bill(db, b.id)


def refresh_status(db: Session, b: m.SupplierBill):
    if b.status == "VOID": return
    paid = paid_on_bill(db, b.id)
    b.status = "PAID" if paid >= D(b.total) else ("PARTIAL" if paid > 0 else "OPEN")


def po_match(db: Session, po: m.PurchaseOrder, taxable: Decimal, exclude_bill: str | None = None) -> dict:
    """3-way check (PO ↔ goods received ↔ bill): compare everything billed on this PO (taxable value) with the value of goods actually received."""
    lines = db.query(m.POLine).filter_by(po_id=po.id).all()
    ordered = sum((q(D(l.rate) * l.qty) for l in lines), ZERO)
    received = sum((q(D(l.rate) * l.received) for l in lines), ZERO)
    qb = db.query(func.coalesce(func.sum(m.SupplierBill.taxable), 0)).filter(m.SupplierBill.po_id == po.id, m.SupplierBill.status != "VOID")
    if exclude_bill: qb = qb.filter(m.SupplierBill.id != exclude_bill)
    billed_before = D(qb.scalar() or 0)
    after = billed_before + D(taxable)
    allowance = max(received * TOLERANCE_PCT / 100, Decimal("1"))
    status = "OVER_BILLED" if after > received + allowance else ("UNDER_BILLED" if after < received - allowance else "MATCHED")
    return {"ordered": f"{ordered:.2f}", "received": f"{received:.2f}", "billed_before": f"{billed_before:.2f}", "billed_after": f"{after:.2f}",
            "left_to_bill": f"{max(ZERO, received - billed_before):.2f}", "status": status}


def due_date(bill_date: date, supplier: m.Supplier) -> date:
    return bill_date + timedelta(days=supplier.payment_terms_days if supplier.payment_terms_days is not None else 30)


def bucket(b: m.SupplierBill, today: date) -> str:
    late = (today - _aware(b.due_date).date()).days
    if late <= 0: return "not_due"
    return "d0_30" if late <= 30 else "d31_60" if late <= 60 else "d61_90" if late <= 90 else "d90_plus"


def auto_allocate(db: Session, supplier_id: str, amount: Decimal) -> list[tuple[m.SupplierBill, Decimal]]:
    """Oldest due first (then oldest bill date) until the amount is used up."""
    out, left = [], D(amount)
    bills = (db.query(m.SupplierBill).filter(m.SupplierBill.supplier_id == supplier_id, m.SupplierBill.status.in_(["OPEN", "PARTIAL"]))
             .order_by(m.SupplierBill.due_date, m.SupplierBill.bill_date, m.SupplierBill.created_at).all())
    for b in bills:
        if left <= 0: break
        o = outstanding(db, b)
        if o <= 0: continue
        take = min(o, left); out.append((b, take)); left -= take
    return out


def summary(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    sups = {s.id: s for s in db.query(m.Supplier)}
    per = defaultdict(lambda: {"outstanding": ZERO, "overdue": ZERO, "bills": 0, **{k: ZERO for k, _ in BUCKETS}})
    totals = {"outstanding": ZERO, "overdue": ZERO, "due_7_days": ZERO, **{k: ZERO for k, _ in BUCKETS}}
    due_soon = []
    for b in db.query(m.SupplierBill).filter(m.SupplierBill.status.in_(["OPEN", "PARTIAL"])):
        o = outstanding(db, b)
        if o <= 0: continue
        k = bucket(b, today); r = per[b.supplier_id]
        r["outstanding"] += o; r["bills"] += 1; r[k] += o; totals["outstanding"] += o; totals[k] += o
        if k != "not_due": r["overdue"] += o; totals["overdue"] += o
        days = (_aware(b.due_date).date() - today).days
        if 0 <= days <= 7: totals["due_7_days"] += o; due_soon.append((b, o, days))
    rows = [{"supplier_id": sid, "supplier_name": sups[sid].name if sid in sups else "?", "bills": r["bills"], **{k: f"{v:.2f}" for k, v in r.items() if k != "bills"}}
            for sid, r in per.items()]
    rows.sort(key=lambda x: -D(x["outstanding"]))
    return {"totals": {k: f"{v:.2f}" for k, v in totals.items()}, "buckets": [{"key": k, "label": l, "amount": f"{totals[k]:.2f}"} for k, l in BUCKETS],
            "suppliers": rows,
            "due_soon": [{"bill_id": b.id, "bill_no": b.bill_no, "supplier_name": sups.get(b.supplier_id).name if sups.get(b.supplier_id) else "?", "due_date": _aware(b.due_date).date().isoformat(),
                          "days": d, "outstanding": f"{o:.2f}"} for b, o, d in sorted(due_soon, key=lambda x: x[2])]}


def statement(db: Session, supplier_id: str) -> dict:
    """Supplier ledger: bills raise what we owe, payments reduce it; voided documents are shown but don't count."""
    entries = []
    for b in db.query(m.SupplierBill).filter_by(supplier_id=supplier_id):
        entries.append({"date": _aware(b.bill_date).date().isoformat(), "type": "BILL", "ref": b.bill_no, "id": b.id, "bill": f"{D(b.total):.2f}", "paid": None,
                        "void": b.status == "VOID", "note": b.void_reason if b.status == "VOID" else (f"due {_aware(b.due_date).date().isoformat()}"), "_ts": b.created_at})
    for p in db.query(m.SupplierPayment).filter_by(supplier_id=supplier_id):
        entries.append({"date": _aware(p.paid_on).date().isoformat(), "type": "PAYMENT", "ref": p.reference or p.mode, "id": p.id, "bill": None, "paid": f"{D(p.amount):.2f}",
                        "void": p.status == "VOID", "note": p.void_reason if p.status == "VOID" else p.mode, "_ts": p.created_at})
    entries.sort(key=lambda e: (e["date"], e["_ts"]))
    bal = ZERO
    for e in entries:
        if not e["void"]: bal += D(e["bill"] or 0) - D(e["paid"] or 0)
        e["balance"] = f"{bal:.2f}"; e.pop("_ts")
    return {"entries": entries, "balance": f"{bal:.2f}"}


def paid_out_for_project(db: Session, pid: str) -> Decimal:
    """Supplier payments allocated to this project's bills (cash actually gone out to suppliers)."""
    v = (db.query(func.coalesce(func.sum(m.PaymentAllocation.amount), 0)).join(m.SupplierPayment, m.SupplierPayment.id == m.PaymentAllocation.payment_id)
         .join(m.SupplierBill, m.SupplierBill.id == m.PaymentAllocation.bill_id)
         .filter(m.SupplierBill.project_id == pid, m.SupplierPayment.status == "ACTIVE").scalar())
    return D(v or 0)
