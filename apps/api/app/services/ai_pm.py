"""AI Project Manager — deterministic risk rules over the real project data (no LLM, so every alert is explainable and repeatable).
Each alert says WHICH rule fired, the evidence, and the suggested next action."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import models as m
from app.services import flow
from app.services.cost_engine import D, inr

SEV = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _days(a, b) -> int: return (a - b).days


def _aware(t):
    from datetime import timezone
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def project_alerts(db: Session, p: m.Project, now=None, money: bool = False) -> list[dict]:
    now = now or flow.now(); out = []
    stage = flow.stage_index(p.status)
    def add(sev, rule, text, action): out.append({"severity": sev, "rule": rule, "text": text, "action": action, "project_id": p.id, "project_number": p.project_number, "project_name": p.name})
    if p.archived or p.status == "COMPLETED": return out
    target = _aware(p.target_date)
    if target:
        left = _days(target, now)
        if left < 0: add("HIGH", "OVERDUE", f"Handover date passed {-left} day(s) ago; project is at {p.status}.", "Agree a new date with the client and re-plan the remaining stages.")
        elif left <= 14 and stage < flow.stage_index("INSTALLATION"):
            add("HIGH", "DEADLINE_AT_RISK", f"Handover due in {left} day(s) but the project is still at {p.status}.", "Expedite manufacturing/procurement or reset the client's expectation now.")
        elif left <= 30 and stage < flow.stage_index("MANUFACTURING"):
            add("MEDIUM", "DEADLINE_AT_RISK", f"Handover due in {left} day(s); nothing is in production yet ({p.status}).", "Get the quotation approved and start procurement this week.")
    rooms = [r.id for r in db.query(m.Room.id).filter_by(project_id=p.id)]
    boqs = db.query(m.Boq).filter(m.Boq.room_id.in_(rooms)).all() if rooms else []
    for b in boqs:
        if (b.status or "DRAFT") == "SENT" and b.status_at and _days(now, _aware(b.status_at)) > 14:
            add("MEDIUM", "QUOTE_NO_RESPONSE", f"{flow.quote_no(p.project_number, b)} was sent {_days(now, _aware(b.status_at))} days ago with no decision.", "Follow up with the client; offer a revision call.")
    approved = [b for b in boqs if b.status == "APPROVED"]
    quoted = sum((D(b.totals["grand_total"]) for b in approved), Decimal(0))
    if quoted > 0:
        paid = sum((D(x.amount) for x in db.query(m.Payment).filter_by(project_id=p.id)), Decimal(0))
        expected_pct = {"PROCUREMENT": 30, "MANUFACTURING": 50, "DELIVERY": 75, "INSTALLATION": 75, "QC": 95, "HANDOVER": 95}.get(p.status, 0)
        if expected_pct and paid * 100 < quoted * expected_pct:
            add("HIGH" if expected_pct >= 75 else "MEDIUM", "PAYMENT_BEHIND",
                f"Received Rs. {inr(paid)} of Rs. {inr(quoted)} ({int(paid * 100 / quoted)}%); the schedule expects {expected_pct}% by {p.status}.",
                "Raise the pending milestone invoice before the next stage starts.")
    for po in db.query(m.PurchaseOrder).filter(m.PurchaseOrder.project_id == p.id, m.PurchaseOrder.status.in_(["ISSUED", "PARTIAL"])):
        if po.expected_on and _aware(po.expected_on) < now:
            add("HIGH", "PO_LATE", f"{po.po_number} was expected {_days(now, _aware(po.expected_on))} day(s) ago and is {po.status}.", "Call the supplier for a firm date; consider an alternate supplier.")
    for po in db.query(m.PurchaseOrder).filter(m.PurchaseOrder.project_id == p.id, m.PurchaseOrder.status == "DRAFT"):
        if _days(now, _aware(po.created_at)) > 3:
            add("LOW", "PO_NOT_ISSUED", f"{po.po_number} has been a draft for {_days(now, _aware(po.created_at))} days.", "Review and issue it, or cancel it.")
    for w in db.query(m.WorkOrder).filter(m.WorkOrder.project_id == p.id, m.WorkOrder.stage.notin_(["READY"])):
        if _days(now, _aware(w.updated_at)) > 7:
            add("MEDIUM", "WORK_ORDER_STUCK", f"{w.wo_number} ({w.description}) has been at {w.stage} for {_days(now, _aware(w.updated_at))} days.", "Check the workshop queue for this unit.")
    for s in db.query(m.Snag).filter_by(project_id=p.id, status="OPEN"):
        if _days(now, _aware(s.created_at)) > 5:
            add("MEDIUM", "SNAG_OPEN", f"Snag open {_days(now, _aware(s.created_at))} days: {s.title}", "Assign a site engineer to close it.")
    if money and approved:
        from app.services.profit import project_profit
        pr = project_profit(db, p.id); rev, act, est = D(pr["revenue"]), D(pr["actual"]["total"]), D(pr["estimate"]["total"])
        if act > 0 and rev > 0 and (rev - act) * 100 < rev * 10:
            add("HIGH" if act > rev else "MEDIUM", "LOW_MARGIN", f"Margin so far is {pr['actual']['margin_pct']}% (cost Rs. {inr(act)} on revenue Rs. {inr(rev)} before GST).",
                "Review open purchase orders and expenses; agree any extra work as a new quotation.")
        if est > 0 and act > est * Decimal("1.10"):
            add("MEDIUM", "COST_OVERRUN", f"Actual cost Rs. {inr(act)} is over the estimate Rs. {inr(est)} by {((act - est) * 100 / est).quantize(Decimal('0.1'))}%.",
                "Check which supplier or expense category is over and update catalogue costs.")
    last = db.query(m.ProjectEvent).filter_by(project_id=p.id).order_by(m.ProjectEvent.created_at.desc()).first()
    if last and _days(now, _aware(last.created_at)) > 21 and stage < flow.stage_index("HANDOVER"):
        add("LOW", "NO_ACTIVITY", f"No activity for {_days(now, _aware(last.created_at))} days (at {p.status}).", "Confirm the project is still live or archive it.")
    return out


def low_stock_alerts(db: Session) -> list[dict]:
    out = []
    for it in db.query(m.FurnitureItem).filter(m.FurnitureItem.is_active.isnot(False), m.FurnitureItem.min_stock.isnot(None)):
        if (it.stock or 0) <= it.min_stock:
            out.append({"severity": "LOW" if it.stock else "MEDIUM", "rule": "LOW_STOCK", "text": f"{it.sku} {it.name}: {it.stock or 0} {it.unit or 'No.'} left (reorder level {it.min_stock}).",
                        "action": "Raise a purchase order with its supplier.", "project_id": None, "project_number": None, "project_name": None})
    return out


def bill_alerts(db: Session, now=None) -> list[dict]:
    from app.services.payables import outstanding
    now = now or flow.now(); out = []; sups = {s.id: s.name for s in db.query(m.Supplier)}
    for b in db.query(m.SupplierBill).filter(m.SupplierBill.status.in_(["OPEN", "PARTIAL"])):
        late = (now.date() - _aware(b.due_date).date()).days; o = outstanding(db, b)
        if late > 0 and o > 0:
            out.append({"severity": "HIGH" if late > 30 else "MEDIUM", "rule": "BILL_OVERDUE", "text": f"{sups.get(b.supplier_id, '?')} bill {b.bill_no}: Rs. {inr(o)} is {late} day(s) past due.",
                        "action": "Pay it or agree a new date with the supplier (late payments can hold up deliveries).", "project_id": None, "project_number": None, "project_name": None})
    return out


def all_alerts(db: Session, now=None, money: bool = False) -> list[dict]:
    rows = []
    for p in db.query(m.Project): rows += project_alerts(db, p, now, money)
    if money: rows += bill_alerts(db, now)
    from app.services.followups import alerts as lead_alerts
    rows += lead_alerts(db, now)
    rows += low_stock_alerts(db)
    return sorted(rows, key=lambda a: (SEV[a["severity"]], a["project_number"] or "~", a["rule"]))
