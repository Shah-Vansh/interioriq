"""Lead follow-ups: who calls whom, when. 'Overdue' = due time has passed; 'today' = due later today in company local time (fixed UTC offset)."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m
from app.services import flow

ASSIGNABLE = ("SUPER_ADMIN", "ADMIN", "PROJECT_MANAGER", "SALES")      # the roles that may edit leads (crm.WRITE), so an owner can always act on their follow-ups
ACTIVE_STAGES = [s for s in m.LEAD_STAGES if s not in ("WON", "LOST")]


def _aware(t): return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def local_tz(): return timezone(timedelta(minutes=settings.COMPANY_UTC_OFFSET_MIN))


def bucket(due, now=None) -> str:
    now = now or flow.now(); due = _aware(due)
    if due < now: return "OVERDUE"
    return "TODAY" if due.astimezone(local_tz()).date() == now.astimezone(local_tz()).date() else "UPCOMING"


def open_by_lead(db: Session, lead_ids=None) -> dict:
    """lead_id → (earliest open follow-up, count of open follow-ups)."""
    q = db.query(m.LeadFollowUp).filter(m.LeadFollowUp.status == "OPEN")
    if lead_ids is not None:
        if not lead_ids: return {}
        q = q.filter(m.LeadFollowUp.lead_id.in_(list(lead_ids)))
    out: dict = {}
    for f in q.order_by(m.LeadFollowUp.due_at):
        first, n = out.get(f.lead_id, (None, 0)); out[f.lead_id] = (first or f, n + 1)
    return out


def lead_status(l: m.Lead, first, now=None) -> str:
    """OVERDUE / TODAY / UPCOMING from the next open follow-up; NONE = an active lead with no next step; CLOSED = won/lost/archived."""
    if l.archived or l.stage in ("WON", "LOST"): return "CLOSED"
    return bucket(first.due_at, now) if first else "NONE"


def check_assignee(db: Session, uid: str | None) -> m.User | None:
    if not uid: return None
    u = db.get(m.User, uid)
    if not u or u.is_active is False: raise ValueError("That user doesn't exist or is disabled")
    if u.role not in ASSIGNABLE: raise ValueError(f"Leads can be assigned to {', '.join(r.title().replace('_', ' ') for r in ASSIGNABLE[1:])} only")
    return u


def alerts(db: Session, now=None) -> list[dict]:
    """AI-PM rules for the sales pipeline: overdue follow-ups, and active leads with no next step for more than 2 days."""
    now = now or flow.now(); out = []
    leads = {l.id: l for l in db.query(m.Lead).filter(m.Lead.archived.isnot(True), m.Lead.stage.in_(ACTIVE_STAGES))}
    users = {u.id: u.full_name for u in db.query(m.User)}
    firsts = open_by_lead(db, set(leads))
    for lid, l in leads.items():
        first = firsts.get(lid, (None, 0))[0]
        base = {"project_id": None, "project_number": None, "project_name": None, "lead_id": lid}
        who = users.get((first.assigned_to if first else None) or l.assigned_to) or "nobody"
        if first and _aware(first.due_at) < now:
            late = now - _aware(first.due_at); days = late.days
            out.append({**base, "severity": "HIGH" if days >= 3 else "MEDIUM", "rule": "FOLLOW_UP_OVERDUE",
                        "text": f"Lead {l.name}: {first.kind.lower()} was due {days} day(s) ago" + ("" if days else f" ({int(late.total_seconds() // 3600)} h ago)") + f" — {who}.",
                        "action": "Make the call / visit and record the outcome, or reschedule it."})
        elif not first and now - _aware(l.created_at) > timedelta(days=2):
            out.append({**base, "severity": "LOW", "rule": "LEAD_NO_NEXT_STEP", "text": f"Lead {l.name} ({l.stage.replace('_', ' ').title()}) has no follow-up scheduled — owner {who}.",
                        "action": "Schedule the next call or visit, or mark it Lost with a reason."})
    return out
