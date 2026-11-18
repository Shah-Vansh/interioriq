"""Profitability (ADMIN / PROJECT_MANAGER only) and project expenses."""
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access
from app.services import flow, profit
from app.services.cost_engine import D, inr

router = APIRouter(tags=["Profitability"])
MONEY = ("ADMIN", "PROJECT_MANAGER")                                              # who sees margins
EXP_WRITE = ("ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "PROCUREMENT_MANAGER")   # who records expenses (site engineers log site costs)


def _project(db: Session, pid: str) -> m.Project:
    p = db.get(m.Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    return p


@router.get("/projects/{pid}/profit")
def get_profit(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*MONEY))):
    _project(db, pid); return profit.project_profit(db, pid)


@router.get("/reports/profitability")
def report(db: Session = Depends(get_db), user: dict = Depends(require_roles(*MONEY))):
    rows, tot = [], {"revenue": Decimal(0), "estimate": Decimal(0), "actual": Decimal(0)}
    clients = {c.id: c.name for c in db.query(m.Client)}
    for p in access.scope(db.query(m.Project), m.Project.id, db, user).order_by(m.Project.project_number):
        r = profit.project_profit(db, p.id)
        if not r["has_quote"] and r["actual"]["total"] == "0.00": continue
        rows.append({"id": p.id, "project_number": p.project_number, "name": p.name, "client_name": clients.get(p.client_id), "status": p.status or "LEAD",
                     "revenue": r["revenue"], "estimate_cost": r["estimate"]["total"], "estimate_margin_pct": r["estimate"]["margin_pct"],
                     "actual_cost": r["actual"]["total"], "profit": r["actual"]["profit"], "margin_pct": r["actual"]["margin_pct"], "variance": r["variance"],
                     "flags": r["flags"], "missing_cost": len(r["missing_cost"])})
        tot["revenue"] += D(r["revenue"]); tot["estimate"] += D(r["estimate"]["total"]); tot["actual"] += D(r["actual"]["total"])
    margin = None if tot["revenue"] <= 0 else f"{((tot['revenue'] - tot['actual']) * 100 / tot['revenue']).quantize(Decimal('0.1'))}"
    return {"projects": rows, "totals": {"revenue": f"{tot['revenue']:.2f}", "estimate_cost": f"{tot['estimate']:.2f}", "actual_cost": f"{tot['actual']:.2f}",
                                          "profit": f"{tot['revenue'] - tot['actual']:.2f}", "margin_pct": margin}}


def exp_out(e: m.Expense) -> dict:
    return {"id": e.id, "project_id": e.project_id, "category": e.category, "amount": f"{D(e.amount):.2f}", "spent_on": e.spent_on.date().isoformat(),
            "vendor": e.vendor, "note": e.note, "status": e.status, "void_reason": e.void_reason, "user_name": e.user_name,
            "created_at": e.created_at.isoformat() if e.created_at else None}


@router.get("/projects/{pid}/expenses")
def list_expenses(pid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*(EXP_WRITE + MONEY)))):
    _project(db, pid)
    return {"categories": m.EXPENSE_CATEGORIES,
            "expenses": [exp_out(e) for e in db.query(m.Expense).filter_by(project_id=pid).order_by(m.Expense.spent_on.desc(), m.Expense.created_at.desc())]}


class ExpenseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    spent_on: date
    vendor: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=500)

    @field_validator("category")
    @classmethod
    def _c(cls, v):
        if v not in m.EXPENSE_CATEGORIES: raise ValueError(f"category must be one of {', '.join(m.EXPENSE_CATEGORIES)}")
        return v

    @field_validator("spent_on")
    @classmethod
    def _d(cls, v):
        if v > date.today(): raise ValueError("An expense can't be dated in the future")
        return v


@router.post("/projects/{pid}/expenses", status_code=201)
def add_expense(pid: str, b: ExpenseIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EXP_WRITE))):
    _project(db, pid)
    e = m.Expense(project_id=pid, category=b.category, amount=b.amount, spent_on=datetime.combine(b.spent_on, time(12), tzinfo=timezone.utc),
                  vendor=(b.vendor or "").strip() or None, note=(b.note or "").strip() or None, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(e)
    flow.event(db, pid, "EXPENSE", f"Expense Rs. {inr(b.amount)} ({b.category.lower()}){' — ' + e.vendor if e.vendor else ''}", user, "EXPENSE", None)
    db.commit(); return exp_out(e)


class VoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


@router.post("/expenses/{eid}/void")
def void_expense(eid: str, b: VoidIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*EXP_WRITE))):
    e = db.get(m.Expense, eid)
    if not e: raise HTTPException(404, "Expense not found")
    if e.status == "VOID": raise HTTPException(409, "This expense is already void")
    e.status, e.void_reason = "VOID", b.reason.strip()
    flow.event(db, e.project_id, "EXPENSE", f"Expense Rs. {inr(e.amount)} voided: {e.void_reason}", user, "EXPENSE", e.id)
    db.commit(); return exp_out(e)
