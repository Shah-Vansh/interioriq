"""Project profitability — Decimal only, from the ledgers.
REVENUE   = approved quotations' value BEFORE GST (GST is collected for the government, not income).
ESTIMATE  = catalogue COST of each BOQ item (falls back to the selling rate when no cost is set — listed in `missing_cost`) + the BOQ labour + lump sums.
ACTUAL    = purchase-order lines (not cancelled) at their own rates + stock taken for the project at the cost recorded when it was taken + active expenses.
Nothing is stored twice: every figure is recomputed from POs, stock movements, expenses and the frozen BOQs."""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import models as m
from app.services.cost_engine import D, q

SERVICE = {"Transport", "Installation"}
ZERO = Decimal("0.00")


def _m(x) -> str: return f"{q(D(x)):.2f}"


def _pct(part, whole) -> str | None:
    whole = D(whole)
    return None if whole <= 0 else f"{(D(part) * 100 / whole).quantize(Decimal('0.1'))}"


def approved_boqs(db: Session, pid: str) -> list[m.Boq]:
    rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=pid)]
    return db.query(m.Boq).filter(m.Boq.room_id.in_(rooms), m.Boq.status == "APPROVED").all() if rooms else []


def project_profit(db: Session, pid: str) -> dict:
    boqs = approved_boqs(db, pid)
    revenue = sum((D(b.totals.get("after_discount", b.totals["grand_total"])) for b in boqs), ZERO)
    gst = sum((D(b.totals.get("gst", 0)) for b in boqs), ZERO)
    est = {"materials": ZERO, "labour": ZERO, "lump_sums": ZERO}; missing = []
    for b in boqs:
        lines = db.query(m.BoqItem).filter_by(boq_id=b.id).all()
        cat = {i.sku: i for i in db.query(m.FurnitureItem).filter(m.FurnitureItem.sku.in_([l.sku for l in lines if l.sku]))}
        for l in lines:
            qty = D(l.quantity)
            if l.category in SERVICE: est["lump_sums"] += D(l.total); continue
            it = cat.get(l.sku) if l.sku else None
            if it is not None and it.cost_price is not None: est["materials"] += q(qty * D(it.cost_price))
            else:
                est["materials"] += q(qty * D(l.rate)); missing.append(l.description)
            est["labour"] += q(qty * D(l.labour))
    est_total = est["materials"] + est["labour"] + est["lump_sums"]

    po_committed = po_received = ZERO; by_supplier = defaultdict(Decimal)
    sups = {s.id: s.name for s in db.query(m.Supplier)}
    for po in db.query(m.PurchaseOrder).filter(m.PurchaseOrder.project_id == pid, m.PurchaseOrder.status != "CANCELLED"):
        for l in db.query(m.POLine).filter_by(po_id=po.id):
            amt = q(D(l.rate) * l.qty); po_committed += amt; po_received += q(D(l.rate) * l.received); by_supplier[sups.get(po.supplier_id, "?")] += amt
    stock = ZERO
    for s in db.query(m.StockMovement).filter(m.StockMovement.project_id == pid, m.StockMovement.ref_type == "ALLOC", m.StockMovement.unit_cost.isnot(None)):
        stock += q(D(-s.delta) * D(s.unit_cost))
    expenses = defaultdict(Decimal)
    for e in db.query(m.Expense).filter_by(project_id=pid, status="ACTIVE"): expenses[e.category] += D(e.amount)
    exp_total = sum(expenses.values(), ZERO)
    actual = po_committed + stock + exp_total
    paid = sum((D(p.amount) for p in db.query(m.Payment).filter_by(project_id=pid)), ZERO)
    from app.services.payables import paid_out_for_project
    paid_suppliers = paid_out_for_project(db, pid)
    billed = sum((D(b.total) for b in db.query(m.SupplierBill).filter(m.SupplierBill.project_id == pid, m.SupplierBill.status != "VOID")), ZERO)
    flags = []
    if missing: flags.append(f"{len(missing)} item(s) have no cost price — estimate uses the selling rate for them: {', '.join(sorted(set(missing))[:5])}")
    if est_total > 0 and actual > est_total * Decimal("1.10"): flags.append(f"Actual cost is {_pct(actual - est_total, est_total)}% over the estimate")
    if revenue > 0 and actual > revenue: flags.append("Costs exceed the contract value (loss)")
    return {"revenue": _m(revenue), "gst": _m(gst), "contract_value": _m(revenue + gst),
            "estimate": {**{k: _m(v) for k, v in est.items()}, "total": _m(est_total), "profit": _m(revenue - est_total), "margin_pct": _pct(revenue - est_total, revenue)},
            "actual": {"purchase_orders": _m(po_committed), "purchase_received": _m(po_received), "from_stock": _m(stock),
                       "expenses": {k: _m(v) for k, v in sorted(expenses.items())}, "expenses_total": _m(exp_total), "total": _m(actual),
                       "profit": _m(revenue - actual), "margin_pct": _pct(revenue - actual, revenue)},
            "variance": _m(actual - est_total), "by_supplier": [{"supplier": k, "amount": _m(v)} for k, v in sorted(by_supplier.items(), key=lambda x: -x[1])],
            "cash": {"received": _m(paid), "spent_committed": _m(actual), "supplier_bills": _m(billed), "paid_to_suppliers": _m(paid_suppliers),
                     "expenses_paid": _m(exp_total), "position": _m(paid - paid_suppliers - exp_total)},
            "missing_cost": sorted(set(missing)), "flags": flags, "has_quote": bool(boqs)}
