"""Client portal: a CLIENT login sees ONLY its own client's projects — progress, quotations (approve/reject when sent), payments, deliveries, handover."""
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.routers import estimation as r_est, invoices as r_inv, operations as ops
from app.services import flow

router = APIRouter(tags=["Client portal"])
CLIENT_ONLY = require_roles("CLIENT")
PUBLIC_EVENTS = {"STATUS", "QUOTATION", "PAYMENT", "INVOICE", "DELIVERY", "HANDOVER"}      # internal workshop/QC chatter stays internal


def _mine(db: Session, user: dict, pid: str) -> m.Project:
    p = db.get(m.Project, pid)
    if not p or not user.get("client_id") or p.client_id != user["client_id"]: raise HTTPException(404, "Project not found")
    return p


def _my_boq(db: Session, user: dict, bid: str) -> m.Boq:
    b = db.get(m.Boq, bid)
    if not b: raise HTTPException(404, "Quotation not found")
    _mine(db, user, flow.project_of_boq(db, b).id)
    if flow.boq_status(b) == "DRAFT": raise HTTPException(404, "Quotation not found")          # drafts are internal
    return b


@router.get("/portal/projects")
def my_projects(db: Session = Depends(get_db), user: dict = Depends(CLIENT_ONLY)):
    if not user.get("client_id"): return []
    return [{"id": p.id, "project_number": p.project_number, "name": p.name, "status": p.status or "LEAD", "progress": p.progress or 0}
            for p in db.query(m.Project).filter_by(client_id=user["client_id"]).order_by(m.Project.project_number)]


@router.get("/portal/projects/{pid}")
def my_project(pid: str, db: Session = Depends(get_db), user: dict = Depends(CLIENT_ONLY)):
    _mine(db, user, pid); o = ops.overview(db, pid)
    o["quotations"] = [q for q in o["quotations"] if q["status"] != "DRAFT"]
    events = db.query(m.ProjectEvent).filter(m.ProjectEvent.project_id == pid, m.ProjectEvent.kind.in_(PUBLIC_EVENTS)).order_by(m.ProjectEvent.created_at.desc()).limit(50)
    o["timeline"] = [{"text": e.text, "created_at": e.created_at.isoformat()} for e in events]
    o["invoices"] = [{k: i[k] for k in ("id", "invoice_no", "kind", "issue_date", "description", "amount", "status")}
                     for i in r_inv.summary(db, pid)["invoices"] if i["status"] == "ISSUED"]
    o["credit_notes"] = [{k: n[k] for k in ("id", "note_no", "invoice_no", "issue_date", "reason", "amount")} for n in r_inv.summary(db, pid)["credit_notes"] if n["status"] == "ISSUED"]
    o["deliveries"] = [{k: d[k] for k in ("dn_number", "status", "scheduled_on", "delivered_at", "lines")} for d in ops.list_deliveries(pid, None, db, user)]
    return o


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str | None = Field(None, max_length=1000)


@router.post("/portal/boqs/{bid}/decision")
def decide(bid: str, body: DecisionIn, db: Session = Depends(get_db), user: dict = Depends(CLIENT_ONLY)):
    b = _my_boq(db, user, bid)
    if body.decision not in ("APPROVED", "REJECTED"): raise HTTPException(422, "decision must be APPROVED or REJECTED")
    if flow.boq_status(b) != "SENT": raise HTTPException(409, "Only a quotation that has been sent to you can be approved or rejected")
    ops.set_quote_status(db, b, body.decision, f"By client ({user.get('name')})" + (f": {body.note.strip()}" if body.note and body.note.strip() else ""), user)
    db.commit(); return ops.quotation_row(db, b)


@router.get("/portal/boqs/{bid}/quotation.pdf")
def quote_pdf(bid: str, db: Session = Depends(get_db), user: dict = Depends(CLIENT_ONLY)):
    _my_boq(db, user, bid); return r_est.quotation(bid, db=db, user=user)


@router.get("/portal/projects/{pid}/handover.pdf")
def ho_pdf(pid: str, db: Session = Depends(get_db), user: dict = Depends(CLIENT_ONLY)):
    _mine(db, user, pid); return ops.handover_pdf(pid, db, user)
