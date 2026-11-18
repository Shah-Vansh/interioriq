"""Dashboard, reports and AI-PM alerts — all computed from live data (no sample numbers)."""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access
from app.services import ai_pm, catalogue as catlib, flow
from app.services.cost_engine import D

router = APIRouter(tags=["Insights"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))
MONEY_READERS = ("ADMIN", "PROJECT_MANAGER", "SALES", "ESTIMATOR")


def _m(x) -> str: return f"{D(x):.2f}"


def _month(d) -> str: return f"{d.year:04d}-{d.month:02d}"


def _project_rows(db: Session, user: dict | None = None) -> list[dict]:
    clients = {c.id: c.name for c in db.query(m.Client)}
    room_project = {r.id: r.project_id for r in db.query(m.Room)}
    quoted, paid = defaultdict(Decimal), defaultdict(Decimal)
    for b in db.query(m.Boq).filter(m.Boq.status == "APPROVED"): quoted[room_project.get(b.room_id)] += D(b.totals["grand_total"])
    for p in db.query(m.Payment): paid[p.project_id] += D(p.amount)
    snags = dict(db.query(m.Snag.project_id, func.count()).filter_by(status="OPEN").group_by(m.Snag.project_id).all())
    alerts = Counter(a["project_id"] for a in ai_pm.all_alerts(db) if a["project_id"])
    today = flow.now()
    out = []
    q = db.query(m.Project) if user is None else access.scope(db.query(m.Project), m.Project.id, db, user)
    for p in q.order_by(m.Project.project_number):
        td = ai_pm._aware(p.target_date)
        out.append({"id": p.id, "project_number": p.project_number, "name": p.name, "client_name": clients.get(p.client_id), "status": p.status or "LEAD",
                    "progress": p.progress or 0, "archived": bool(p.archived), "target_date": td.date().isoformat() if td else None,
                    "days_left": (td - today).days if td and p.status != "COMPLETED" else None,
                    "quoted": _m(quoted[p.id]), "paid": _m(paid[p.id]), "balance": _m(quoted[p.id] - paid[p.id]), "open_snags": snags.get(p.id, 0), "alerts": alerts.get(p.id, 0)})
    return out


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    today = date.today(); month = _month(today)
    projects = _project_rows(db, user)
    ids = access.visible_ids(db, user); mine = (lambda pid: True) if ids is None else (lambda pid: pid in ids)
    room_project = {r.id: r.project_id for r in db.query(m.Room)}
    live = [p for p in projects if not p["archived"] and p["status"] != "COMPLETED"]
    leads = db.query(m.Lead).all()
    open_leads = [l for l in leads if l.stage not in ("WON", "LOST")]
    pays = [x for x in db.query(m.Payment) if mine(x.project_id)]
    approved = [b for b in db.query(m.Boq).filter(m.Boq.status == "APPROVED") if mine(room_project.get(b.room_id))]
    sent = [b for b in db.query(m.Boq).filter(m.Boq.status == "SENT") if mine(room_project.get(b.room_id))]
    items = db.query(m.FurnitureItem).filter(m.FurnitureItem.is_active.isnot(False)).all()
    pos = [x for x in db.query(m.PurchaseOrder).filter(m.PurchaseOrder.status.in_(["DRAFT", "ISSUED", "PARTIAL"])) if mine(x.project_id)]
    now = flow.now()
    events = access.scope(db.query(m.ProjectEvent), m.ProjectEvent.project_id, db, user).order_by(m.ProjectEvent.created_at.desc()).limit(15).all()
    pmap = {p["id"]: p for p in projects}
    money = user.get("role") in MONEY_READERS + ("SUPER_ADMIN",)
    alerts = [a for a in ai_pm.all_alerts(db, money=user.get("role") in ("ADMIN", "PROJECT_MANAGER", "SUPER_ADMIN") and ids is None) if not a.get("project_id") or mine(a["project_id"])]
    from app.services import followups as fups
    my_due = sum(1 for f in db.query(m.LeadFollowUp).filter_by(status="OPEN", assigned_to=user.get("sub")) if fups.bucket(f.due_at, now) in ("OVERDUE", "TODAY"))
    team_overdue = sum(1 for f in db.query(m.LeadFollowUp).filter_by(status="OPEN") if fups.bucket(f.due_at, now) == "OVERDUE")
    return {
        "cards": {"my_followups_due": my_due, "followups_overdue": team_overdue, "active_projects": len(live), "completed_projects": sum(p["status"] == "COMPLETED" for p in projects),
                  "open_leads": len(open_leads), "pipeline_value": _m(sum((D(l.budget) for l in open_leads if l.budget), Decimal(0))) if money else None,
                  "quotes_awaiting": len(sent), "approved_value": _m(sum((D(b.totals["grand_total"]) for b in approved), Decimal(0))) if money else None,
                  "received_this_month": _m(sum((D(x.amount) for x in pays if _month(x.received_on) == month), Decimal(0))) if money else None,
                  "outstanding": _m(sum((D(p["balance"]) for p in projects), Decimal(0))) if money else None,
                  "open_pos": len(pos), "late_pos": sum(1 for x in pos if x.expected_on and ai_pm._aware(x.expected_on) < now and x.status != "DRAFT"),
                  "low_stock": sum(1 for i in items if catlib.stock_status(i) != "OK"), "high_alerts": sum(a["severity"] == "HIGH" for a in alerts)},
        "stages": [{"stage": s, "count": sum(p["status"] == s for p in live)} for s in m.PROJECT_STAGES if s != "COMPLETED"],
        "lead_stages": [{"stage": s, "count": sum(l.stage == s for l in leads)} for s in m.LEAD_STAGES],
        "projects": sorted(live, key=lambda p: (p["days_left"] is None, p["days_left"] if p["days_left"] is not None else 0))[:8],
        "alerts": alerts[:8],
        "activity": [{"id": e.id, "text": e.text, "kind": e.kind, "user_name": e.user_name, "created_at": e.created_at.isoformat(),
                      "project_number": pmap.get(e.project_id, {}).get("project_number")} for e in events],
        "money_visible": money,
    }


@router.get("/reports/revenue")
def revenue(months: int = 12, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MONEY_READERS))):
    months = max(1, min(months, 36)); today = date.today()
    keys = []
    y, mo = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{mo:02d}"); mo -= 1
        if mo == 0: y, mo = y - 1, 12
    keys.reverse()
    rec, appr, gst = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    ids = access.visible_ids(db, user); room_project = {r.id: r.project_id for r in db.query(m.Room)}
    pays = [p for p in db.query(m.Payment) if ids is None or p.project_id in ids]
    for p in pays: rec[_month(p.received_on)] += D(p.amount)
    for b in db.query(m.Boq).filter(m.Boq.status == "APPROVED"):
        if ids is not None and room_project.get(b.room_id) not in ids: continue
        k = _month(b.status_at or b.created_at); appr[k] += D(b.totals["grand_total"]); gst[k] += D(b.totals.get("gst", 0))
    by_mode = defaultdict(Decimal)
    for p in pays: by_mode[p.mode] += D(p.amount)
    rows = [{"month": k, "received": _m(rec[k]), "approved": _m(appr[k]), "gst_on_approved": _m(gst[k])} for k in keys]
    return {"months": rows, "totals": {"received": _m(sum((rec[k] for k in keys), Decimal(0))), "approved": _m(sum((appr[k] for k in keys), Decimal(0))),
                                       "all_time_received": _m(sum(rec.values(), Decimal(0)))},
            "by_mode": [{"mode": k, "amount": _m(v)} for k, v in sorted(by_mode.items())]}


@router.get("/reports/projects")
def projects_report(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    rows = _project_rows(db, user)
    if user.get("role") not in MONEY_READERS + ("SUPER_ADMIN",):
        for r in rows: r["quoted"] = r["paid"] = r["balance"] = None
    return rows


@router.get("/ai/alerts")
def alerts(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    ids = access.visible_ids(db, user)
    rows = [a for a in ai_pm.all_alerts(db, money=user.get("role") in ("ADMIN", "PROJECT_MANAGER", "SUPER_ADMIN") and ids is None)
            if not a.get("project_id") or ids is None or a["project_id"] in ids]
    return {"alerts": rows, "counts": dict(Counter(a["severity"] for a in rows)), "rules": RULES}


RULES = [
    {"rule": "OVERDUE", "when": "Target handover date has passed and the project isn't completed"},
    {"rule": "DEADLINE_AT_RISK", "when": "≤14 days to handover but not yet installing, or ≤30 days and not yet in production"},
    {"rule": "QUOTE_NO_RESPONSE", "when": "A quotation was SENT more than 14 days ago without a decision"},
    {"rule": "PAYMENT_BEHIND", "when": "Payments received are below the schedule for the current stage (30% procurement, 50% manufacturing, 75% delivery/installation, 95% QC)"},
    {"rule": "PO_LATE", "when": "An issued purchase order is past its expected date"},
    {"rule": "PO_NOT_ISSUED", "when": "A purchase order has been a draft for more than 3 days"},
    {"rule": "WORK_ORDER_STUCK", "when": "A work order hasn't changed stage for more than 7 days"},
    {"rule": "SNAG_OPEN", "when": "A QC snag has been open for more than 5 days"},
    {"rule": "NO_ACTIVITY", "when": "No activity on a live project for 21 days"},
    {"rule": "LOW_STOCK", "when": "A catalogue item is at or below its reorder level"},
    {"rule": "LOW_MARGIN", "when": "Actual margin (revenue before GST − POs − stock used − expenses) is below 10% — shown to admins and project managers only"},
    {"rule": "FOLLOW_UP_OVERDUE", "when": "A lead's scheduled call / visit time has passed and it isn't marked done (HIGH after 3 days)"},
    {"rule": "LEAD_NO_NEXT_STEP", "when": "An open lead has had no follow-up scheduled for more than 2 days"},
    {"rule": "BILL_OVERDUE", "when": "A supplier bill is past its due date and not fully paid — admins and project managers only"},
    {"rule": "COST_OVERRUN", "when": "Actual cost is more than 10% over the estimate — admins and project managers only"},
]


@router.get("/search")
def search(q: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    """Global search for the top bar: projects, clients, leads, catalogue items, quotations, purchase orders (max 6 each)."""
    from sqlalchemy import or_
    from app.services.phone import PhoneError, normalize_phone
    k = q.strip().lower()
    if len(k) < 2: return []
    like = f"%{k}%"; out = []
    try: pn = normalize_phone(q)
    except PhoneError: pn = None
    ids = access.visible_ids(db, user)
    for p in access.scope(db.query(m.Project), m.Project.id, db, user).filter(or_(func.lower(m.Project.project_number).like(like), func.lower(m.Project.name).like(like))).limit(6):
        out.append({"type": "Project", "label": f"{p.project_number} · {p.name}", "href": f"/projects/{p.id}"})
    cq = db.query(m.Client).filter(or_(func.lower(m.Client.name).like(like), func.lower(m.Client.company).like(like), *([m.Client.phone_norm == pn] if pn else [])))
    for c in cq.limit(6): out.append({"type": "Client", "label": c.name + (f" · {c.company}" if c.company else ""), "href": "/crm/clients"})
    lq = db.query(m.Lead).filter(or_(func.lower(m.Lead.name).like(like), func.lower(m.Lead.city).like(like), *([m.Lead.phone_norm == pn] if pn else [])))
    for l in lq.limit(6): out.append({"type": "Lead", "label": f"{l.name} · {l.stage.replace('_', ' ').title()}", "href": "/crm/leads"})
    for i in db.query(m.FurnitureItem).filter(or_(func.lower(m.FurnitureItem.sku).like(like), func.lower(m.FurnitureItem.name).like(like))).limit(6):
        out.append({"type": "Catalogue", "label": f"{i.sku} · {i.name}", "href": f"/catalogue/{({'MATERIAL': 'materials', 'LIGHTING': 'lighting', 'HARDWARE': 'hardware'}).get(i.kind or 'FURNITURE', 'furniture')}"})
    for po in access.scope(db.query(m.PurchaseOrder), m.PurchaseOrder.project_id, db, user).filter(func.lower(m.PurchaseOrder.po_number).like(like)).limit(6):
        out.append({"type": "Purchase order", "label": po.po_number, "href": f"/execution/po?open={po.id}"})
    if k.startswith("qt"):
        for p in access.scope(db.query(m.Project), m.Project.id, db, user).all():
            if p.project_number.lower() in k: out.append({"type": "Quotation", "label": f"Quotations of {p.project_number}", "href": "/estimation/quotations"})
    return out[:30]
