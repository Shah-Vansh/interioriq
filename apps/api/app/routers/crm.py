from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from datetime import timedelta, timezone

from app.services import crm, flow, followups as fups
from app.services.phone import PhoneError, normalize_phone

router = APIRouter(tags=["CRM"])
WRITE = ("ADMIN", "PROJECT_MANAGER", "SALES")
READ = WRITE + ("INTERIOR_DESIGNER", "ESTIMATOR", "SITE_ENGINEER")      # staff only; CLIENT never sees other clients
MONEY = dict(ge=0, le=10_000_000_000)


def _text(v, n=200):
    if v is None: return None
    v = str(v).strip()
    return v[:n] or None


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("phone", check_fields=False)
    @classmethod
    def _phone(cls, v):
        if v is None or not str(v).strip(): return None
        try: normalize_phone(v)
        except PhoneError as e: raise ValueError(str(e))
        return str(v).strip()

    @field_validator("email", check_fields=False)
    @classmethod
    def _email(cls, v):
        if v is None or not str(v).strip(): return None
        v = str(v).strip()
        if "@" not in v or "." not in v.split("@")[-1] or " " in v: raise ValueError("Not a valid email address")
        return v


class LeadIn(_Base):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None; email: str | None = None; city: str | None = Field(None, max_length=80)
    source: str | None = Field(None, max_length=60); requirement: str | None = Field(None, max_length=2000)
    budget: Decimal | None = Field(None, **MONEY)


class LeadPatch(_Base):
    name: str | None = Field(None, min_length=1, max_length=120)
    phone: str | None = None; email: str | None = None; city: str | None = Field(None, max_length=80)
    source: str | None = Field(None, max_length=60); requirement: str | None = Field(None, max_length=2000)
    budget: Decimal | None = Field(None, **MONEY)


class StageIn(_Base):
    stage: str
    reason: str | None = Field(None, max_length=500)     # required when moving to LOST

    @field_validator("stage")
    @classmethod
    def _stage(cls, v):
        if v not in m.LEAD_STAGES: raise ValueError(f"Stage must be one of {', '.join(m.LEAD_STAGES)}")
        return v


class NoteIn(_Base):
    text: str = Field(min_length=1, max_length=4000)


class ConvertIn(_Base):
    project_number: str = Field(min_length=1, max_length=40)
    project_name: str | None = Field(None, max_length=120)
    budget: Decimal | None = Field(None, **MONEY)


class ClientIn(_Base):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None; email: str | None = None; city: str | None = Field(None, max_length=80)
    company: str | None = Field(None, max_length=120); address: str | None = Field(None, max_length=500); notes: str | None = Field(None, max_length=4000)
    gstin: str | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        from app.services.catalogue import normalize_gstin
        return normalize_gstin(v)


class ClientPatch(_Base):
    name: str | None = Field(None, min_length=1, max_length=120)
    phone: str | None = None; email: str | None = None; city: str | None = Field(None, max_length=80)
    company: str | None = Field(None, max_length=120); address: str | None = Field(None, max_length=500); notes: str | None = Field(None, max_length=4000)
    gstin: str | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        from app.services.catalogue import normalize_gstin
        return normalize_gstin(v)


def _iso(d: datetime | None): return d.isoformat() if d else None
def _money(v): return None if v is None else f"{Decimal(v):.2f}"


def _lead(l: m.Lead, project: m.Project | None = None, fu: tuple | None = None, users: dict | None = None, db: Session | None = None) -> dict:
    if fu is None and db is not None: fu = fups.open_by_lead(db, {l.id}).get(l.id, (None, 0))
    first, n = fu or (None, 0)
    if users is None and db is not None: users = {u.id: u.full_name for u in db.query(m.User)}
    users = users or {}
    return {"id": l.id, "name": l.name, "phone": l.phone, "email": l.email, "city": l.city, "source": l.source, "requirement": l.requirement,
            "budget": _money(l.budget), "stage": l.stage, "client_id": l.client_id, "project_id": l.project_id,
            "project_number": project.project_number if project else None, "created_at": _iso(l.created_at), "updated_at": _iso(l.updated_at),
            "assigned_to": l.assigned_to, "assigned_name": users.get(l.assigned_to), "archived": bool(l.archived), "lost_reason": l.lost_reason,
            "next_follow_up": _iso(first.due_at) if first else None, "next_follow_up_kind": first.kind if first else None, "open_follow_ups": n,
            "follow_up_status": fups.lead_status(l, first)}


def _client(c: m.Client, projects: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "city": c.city, "company": c.company, "address": c.address, "gstin": c.gstin,
            "notes": c.notes, "projects": projects, "created_at": _iso(c.created_at)}


def _get_lead(db, lid) -> m.Lead:
    l = db.get(m.Lead, lid)
    if not l: raise HTTPException(404, "Lead not found")
    return l


def _get_client(db, cid) -> m.Client:
    c = db.get(m.Client, cid)
    if not c: raise HTTPException(404, "Client not found")
    return c


def _clean(d: dict) -> dict:
    """Trim text; blank strings become None. Other values pass through."""
    return {k: (_text(v, 4000) if isinstance(v, str) else v) for k, v in d.items()}


# ── Leads ───────────────────────────────────────────────────────────────────
@router.get("/crm/stages")
def stages(user: dict = Depends(require_roles(*READ))): return m.LEAD_STAGES


@router.get("/crm/meta")
def crm_meta(db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    assignable = [{"id": u.id, "name": u.full_name, "role": u.role} for u in db.query(m.User).filter(m.User.is_active.isnot(False), m.User.role.in_(fups.ASSIGNABLE)).order_by(m.User.full_name)]
    return {"stages": m.LEAD_STAGES, "lost_reasons": m.LOST_REASONS, "follow_up_kinds": m.FOLLOWUP_KINDS, "assignable": assignable}


@router.get("/leads")
def list_leads(q: str | None = None, stage: str | None = None, assigned: str | None = None, follow_up: str | None = None, archived: bool = False,
               db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    """assigned: me | unassigned | <user id>. follow_up: OVERDUE | TODAY | UPCOMING | NONE. archived=true shows only archived leads."""
    qry = db.query(m.Lead).filter(m.Lead.archived.is_(True) if archived else m.Lead.archived.isnot(True))
    if stage: qry = qry.filter(m.Lead.stage == stage)
    if assigned == "me": qry = qry.filter(m.Lead.assigned_to == user.get("sub"))
    elif assigned == "unassigned": qry = qry.filter(m.Lead.assigned_to.is_(None))
    elif assigned: qry = qry.filter(m.Lead.assigned_to == assigned)
    if q and q.strip():
        like = f"%{q.strip()}%"; conds = [m.Lead.name.ilike(like), m.Lead.city.ilike(like), m.Lead.requirement.ilike(like), m.Lead.phone.ilike(like)]
        try: conds.append(m.Lead.phone_norm == normalize_phone(q))
        except PhoneError: pass
        qry = qry.filter(or_(*conds))
    leads = qry.order_by(m.Lead.updated_at.desc()).all()
    pids = {l.project_id for l in leads if l.project_id}
    projects = {p.id: p for p in db.query(m.Project).filter(m.Project.id.in_(pids))} if pids else {}
    firsts = fups.open_by_lead(db, {l.id for l in leads}); users = {u.id: u.full_name for u in db.query(m.User)}
    rows = [_lead(l, projects.get(l.project_id), firsts.get(l.id, (None, 0)), users) for l in leads]
    if follow_up: rows = [r for r in rows if r["follow_up_status"] == follow_up.upper()]
    return rows


@router.post("/leads", status_code=201)
def create_lead(b: LeadIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    d = _clean(b.model_dump())
    l = m.Lead(**d, phone_norm=normalize_phone(d["phone"]), stage="NEW", created_by=user.get("sub"),
               assigned_to=user.get("sub") if user.get("role") in fups.ASSIGNABLE else None)        # whoever logs a lead owns it until reassigned
    db.add(l); db.flush()
    crm.log(db, l, user, "CREATED", to="NEW")
    existing = crm.find_client_by_phone(db, l.phone_norm)
    db.commit()
    out = _lead(l, db=db)
    out["existing_client"] = {"id": existing.id, "name": existing.name} if existing else None
    return out


@router.get("/leads/{lid}")
def get_lead(lid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    l = _get_lead(db, lid)
    acts = db.query(m.LeadActivity).filter_by(lead_id=lid).order_by(m.LeadActivity.created_at.desc()).all()
    out = _lead(l, db.get(m.Project, l.project_id) if l.project_id else None, db=db)
    users = {u.id: u.full_name for u in db.query(m.User)}
    out["follow_ups"] = [fu_out(f, users) for f in db.query(m.LeadFollowUp).filter_by(lead_id=lid).order_by(m.LeadFollowUp.status != "OPEN", m.LeadFollowUp.due_at.desc())]
    existing = crm.find_client_by_phone(db, l.phone_norm)
    out["existing_client"] = {"id": existing.id, "name": existing.name} if existing else None
    out["activity"] = [{"id": a.id, "kind": a.kind, "from_stage": a.from_stage, "to_stage": a.to_stage, "text": a.text, "user_name": a.user_name,
                        "created_at": _iso(a.created_at)} for a in acts]
    return out


@router.patch("/leads/{lid}")
def update_lead(lid: str, b: LeadPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    d = _clean(b.model_dump(exclude_unset=True))
    if "name" in d and not d["name"]: raise HTTPException(422, "Name can't be empty")
    for k, v in d.items(): setattr(l, k, v)
    if "phone" in d: l.phone_norm = normalize_phone(d["phone"])
    db.commit(); return _lead(l, db=db)


@router.post("/leads/{lid}/stage")
def move_stage(lid: str, b: StageIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    if l.stage == b.stage: return _lead(l, db=db)
    if l.project_id and b.stage != "WON": raise HTTPException(409, "This lead is converted to a project; its stage stays Won")
    if b.stage == "LOST":
        reason = (b.reason or "").strip()
        if len(reason) < 3: raise HTTPException(422, [{"loc": ["body", "reason"], "msg": "Say why the lead was lost", "type": "value_error"}])
        l.lost_reason = reason
        for f in db.query(m.LeadFollowUp).filter_by(lead_id=l.id, status="OPEN"):        # no point chasing a lost lead
            f.status, f.outcome, f.closed_by, f.closed_at = "CANCELLED", "Lead marked lost", user.get("name"), flow.now()
        crm.log(db, l, user, "STAGE", frm=l.stage, to=b.stage, text=f"Lost: {reason}")
    else:
        if l.stage == "LOST": l.lost_reason = None
        crm.log(db, l, user, "STAGE", frm=l.stage, to=b.stage)
    l.stage = b.stage; db.commit()
    return _lead(l, db=db)


class AssignIn(_Base):
    user_id: str | None = None


@router.post("/leads/{lid}/assign")
def assign(lid: str, b: AssignIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    try: u = fups.check_assignee(db, b.user_id)
    except ValueError as e: raise HTTPException(422, str(e))
    if l.assigned_to == (u.id if u else None): return _lead(l, db=db)
    old = l.assigned_to; l.assigned_to = u.id if u else None
    for f in db.query(m.LeadFollowUp).filter_by(lead_id=l.id, status="OPEN"):       # the owner's open follow-ups move with the lead
        if f.assigned_to in (old, None): f.assigned_to = l.assigned_to
    crm.log(db, l, user, "ASSIGNED", text=f"Assigned to {u.full_name}" if u else "Unassigned")
    db.commit(); return _lead(l, db=db)


class ArchiveIn(_Base):
    archived: bool


@router.post("/leads/{lid}/archive")
def archive(lid: str, b: ArchiveIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    if bool(l.archived) == b.archived: return _lead(l, db=db)
    l.archived = b.archived
    if b.archived:
        for f in db.query(m.LeadFollowUp).filter_by(lead_id=l.id, status="OPEN"):
            f.status, f.outcome, f.closed_by, f.closed_at = "CANCELLED", "Lead archived", user.get("name"), flow.now()
    crm.log(db, l, user, "ARCHIVED" if b.archived else "RESTORED", text="Archived" if b.archived else "Restored from archive")
    db.commit(); return _lead(l, db=db)


# ── Follow-ups ──────────────────────────────────────────────────────────────
def fu_out(f: m.LeadFollowUp, users: dict, lead: m.Lead | None = None) -> dict:
    out = {"id": f.id, "lead_id": f.lead_id, "kind": f.kind, "due_at": _iso(f.due_at), "note": f.note, "assigned_to": f.assigned_to, "assigned_name": users.get(f.assigned_to),
           "status": f.status, "outcome": f.outcome, "closed_by": f.closed_by, "closed_at": _iso(f.closed_at),
           "bucket": fups.bucket(f.due_at) if f.status == "OPEN" else f.status, "reminded_at": _iso(getattr(f, "reminded_at", None)),
           "repeat_days": getattr(f, "repeat_days", None)}
    if lead is not None: out.update(lead_name=lead.name, lead_phone=lead.phone, lead_stage=lead.stage, lead_city=lead.city)
    return out


def _future(due: datetime) -> datetime:
    due = due if due.tzinfo else due.replace(tzinfo=fups.local_tz())         # a time without a zone is company local time
    if due < flow.now() - timedelta(minutes=5): raise HTTPException(422, [{"loc": ["body", "due_at"], "msg": "A follow-up can't be scheduled in the past", "type": "value_error"}])
    return due.astimezone(timezone.utc)        # store UTC: SQLite keeps no zone, and everything else reads stored times as UTC


class FollowUpIn(_Base):
    due_at: datetime
    kind: str = "CALL"
    note: str | None = Field(None, max_length=1000)
    assigned_to: str | None = None
    repeat_days: int | None = Field(None, ge=1, le=90)      # M31: repeat every N days (1–90); None = once

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        v = v.upper()
        if v not in m.FOLLOWUP_KINDS: raise ValueError(f"kind must be one of {', '.join(m.FOLLOWUP_KINDS)}")
        return v


def _add_followup(db: Session, l: m.Lead, b: FollowUpIn, user: dict) -> m.LeadFollowUp:
    if l.archived or l.stage in ("LOST", "WON"): raise HTTPException(409, f"This lead is {'archived' if l.archived else l.stage.lower()}; follow-ups are for open leads")
    try: u = fups.check_assignee(db, b.assigned_to or l.assigned_to or (user.get("sub") if user.get("role") in fups.ASSIGNABLE else None))
    except ValueError as e: raise HTTPException(422, str(e))
    f = m.LeadFollowUp(lead_id=l.id, kind=b.kind, due_at=_future(b.due_at), note=(b.note or "").strip() or None, assigned_to=u.id if u else None, created_by=user.get("sub"),
                       repeat_days=b.repeat_days)
    db.add(f); db.flush()
    local = f.due_at.astimezone(fups.local_tz())
    crm.log(db, l, user, "FOLLOW_UP", text=f"{b.kind.title()} scheduled for {local:%d %b %Y %H:%M}" + (f" with {u.full_name}" if u else "")
            + (f", repeating every {b.repeat_days} day(s)" if b.repeat_days else "") + (f": {f.note}" if f.note else ""))
    l.updated_at = flow.now()
    return f


@router.post("/leads/{lid}/followups", status_code=201)
def add_followup(lid: str, b: FollowUpIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid); f = _add_followup(db, l, b, user); db.commit()
    return fu_out(f, {u.id: u.full_name for u in db.query(m.User)}, l)


def _get_fu(db: Session, fid: str) -> m.LeadFollowUp:
    f = db.get(m.LeadFollowUp, fid)
    if not f: raise HTTPException(404, "Follow-up not found")
    if f.status != "OPEN": raise HTTPException(409, f"This follow-up is already {f.status.lower()}")
    return f


class DoneIn(_Base):
    outcome: str = Field(min_length=3, max_length=1000)
    next: FollowUpIn | None = None          # book the next step in the same action
    stage: str | None = None                # optionally move the lead on (e.g. CONTACTED → SITE_VISIT)
    stop_repeat: bool = False               # M31: a repeating follow-up books its next occurrence unless this is set


def _next_repeat(f: m.LeadFollowUp) -> datetime:
    """Next occurrence: due + N days, rolled forward past now (a late 'done' doesn't book something already overdue)."""
    step = timedelta(days=f.repeat_days); nxt = fups._aware(f.due_at) + step; now = flow.now()
    while nxt <= now: nxt += step
    return nxt


@router.post("/followups/{fid}/done")
def done(fid: str, b: DoneIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    f = _get_fu(db, fid); l = db.get(m.Lead, f.lead_id)
    f.status, f.outcome, f.closed_by, f.closed_at = "DONE", b.outcome.strip(), user.get("name"), flow.now()
    crm.log(db, l, user, "FOLLOW_UP", text=f"{f.kind.title()} done: {f.outcome}")
    if b.stage and b.stage != l.stage:
        if b.stage not in m.LEAD_STAGES or b.stage in ("LOST", "WON"): raise HTTPException(422, "Move to Lost/Won from the lead itself (Lost needs a reason, Won comes from converting)")
        if l.project_id: raise HTTPException(409, "This lead is converted; its stage stays Won")
        crm.log(db, l, user, "STAGE", frm=l.stage, to=b.stage); l.stage = b.stage
    nxt = _add_followup(db, l, b.next, user) if b.next else None
    if f.repeat_days and not b.stop_repeat and not l.archived and l.stage not in ("WON", "LOST"):
        rep = m.LeadFollowUp(lead_id=l.id, kind=f.kind, due_at=_next_repeat(f), note=f.note, assigned_to=f.assigned_to, created_by=user.get("sub"), repeat_days=f.repeat_days)
        db.add(rep); db.flush()
        crm.log(db, l, user, "FOLLOW_UP", text=f"Repeating {f.kind.lower()} booked for {rep.due_at.astimezone(fups.local_tz()):%d %b %Y %H:%M} (every {f.repeat_days} day(s))")
        nxt = nxt or rep
    elif f.repeat_days and b.stop_repeat:
        crm.log(db, l, user, "FOLLOW_UP", text=f"{f.kind.title()} stopped repeating")
    db.commit(); users = {u.id: u.full_name for u in db.query(m.User)}
    return {"done": fu_out(f, users, l), "next": fu_out(nxt, users, l) if nxt else None, "lead": _lead(l, db=db)}


class CancelIn(_Base):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/followups/{fid}/cancel")
def cancel_fu(fid: str, b: CancelIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    f = _get_fu(db, fid); l = db.get(m.Lead, f.lead_id)
    f.status, f.outcome, f.closed_by, f.closed_at = "CANCELLED", b.reason.strip(), user.get("name"), flow.now()
    crm.log(db, l, user, "FOLLOW_UP", text=f"{f.kind.title()} cancelled: {f.outcome}")
    db.commit(); return fu_out(f, {u.id: u.full_name for u in db.query(m.User)}, l)


class RescheduleIn(_Base):
    due_at: datetime | None = None
    note: str | None = Field(None, max_length=1000)
    assigned_to: str | None = None
    repeat_days: int | None = Field(None, ge=1, le=90)      # null in the body = stop repeating


@router.patch("/followups/{fid}")
def reschedule(fid: str, b: RescheduleIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    f = _get_fu(db, fid); l = db.get(m.Lead, f.lead_id); d = b.model_dump(exclude_unset=True)
    if "due_at" in d and d["due_at"]:
        old = _iso(f.due_at); f.due_at = _future(b.due_at); f.reminded_at = None          # remind again for the new time
        crm.log(db, l, user, "FOLLOW_UP", text=f"{f.kind.title()} moved to {f.due_at.astimezone(fups.local_tz()):%d %b %Y %H:%M}")
    if "note" in d: f.note = (b.note or "").strip() or None
    if "repeat_days" in d and d["repeat_days"] != f.repeat_days:
        f.repeat_days = d["repeat_days"]
        crm.log(db, l, user, "FOLLOW_UP", text=f"{f.kind.title()} now repeats every {f.repeat_days} day(s)" if f.repeat_days else f"{f.kind.title()} no longer repeats")
    if "assigned_to" in d:
        try: u = fups.check_assignee(db, b.assigned_to)
        except ValueError as e: raise HTTPException(422, str(e))
        if (u.id if u else None) != f.assigned_to: f.reminded_at = None                 # the new person gets their own reminder
        f.assigned_to = u.id if u else None
    db.commit(); return fu_out(f, {u.id: u.full_name for u in db.query(m.User)}, l)


# ── M25: WhatsApp (free click-to-chat links — the user presses send) ────────────
WA_TARGETS = ("LEAD", "ASSIGNEE")


def _wa_draft(db: Session, f: m.LeadFollowUp, target: str, user: dict) -> dict:
    from app.services import reminders
    target = (target or "").upper()
    if target not in WA_TARGETS: raise HTTPException(422, "target must be LEAD or ASSIGNEE")
    l = db.get(m.Lead, f.lead_id)
    if target == "LEAD":
        return {"target": "LEAD", "name": l.name, "phone": l.phone, "text": reminders.whatsapp_text(db, f, l, user.get("name")),
                "problem": None if l.phone else "This lead has no phone number — add it on the lead first"}
    a = db.get(m.User, f.assigned_to) if f.assigned_to else None
    if not a: raise HTTPException(409, "Nobody is assigned to this follow-up")
    return {"target": "ASSIGNEE", "name": a.full_name, "phone": a.phone, "text": reminders.reminder(db, f, l, a)[1],
            "problem": None if a.phone else f"{a.full_name} has no phone number — add it in Settings → Users"}


@router.get("/followups/{fid}/whatsapp")
def whatsapp_draft(fid: str, target: str = "LEAD", db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    return _wa_draft(db, _get_fu(db, fid), target, user)


class WhatsAppIn(_Base):
    target: str
    phone: str | None = Field(None, max_length=40)       # default: the lead's / assignee's number
    text: str = Field(min_length=1, max_length=4000)


@router.post("/followups/{fid}/whatsapp", status_code=201)
def whatsapp_open(fid: str, b: WhatsAppIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    from app.services import notify
    f = _get_fu(db, fid); d = _wa_draft(db, f, b.target, user); l = db.get(m.Lead, f.lead_id)
    phone = (b.phone or "").strip() or d["phone"]
    if not phone: raise HTTPException(409, d["problem"])
    try: url = notify.whatsapp_url(phone, b.text)
    except notify.NotifyError as e: raise HTTPException(e.status, e.detail)
    kind = "FOLLOWUP_WHATSAPP" if d["target"] == "LEAD" else "FOLLOWUP_REMINDER"
    db.add(m.Message(channel="WHATSAPP", kind=kind, trigger="MANUAL", project_id=None, ref_id=f.id, to=phone, subject=None, body=b.text, status="LINK",
                     user_id=user.get("sub"), user_name=user.get("name")))
    crm.log(db, l, user, "FOLLOW_UP", text=(f"WhatsApp opened to the lead ({phone})" if d["target"] == "LEAD" else f"WhatsApp reminder opened for {d['name']} ({phone})"))
    db.commit(); return {"whatsapp_url": url, "to": phone, "target": d["target"]}


@router.get("/followups")
def list_followups(scope: str = "mine", when: str = "open", db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    """scope: mine | team | <user id>. when: overdue | today | upcoming | open (all three) | done."""
    q = db.query(m.LeadFollowUp)
    q = q.filter(m.LeadFollowUp.status == "DONE") if when == "done" else q.filter(m.LeadFollowUp.status == "OPEN")
    if scope == "mine": q = q.filter(m.LeadFollowUp.assigned_to == user.get("sub"))
    elif scope != "team": q = q.filter(m.LeadFollowUp.assigned_to == scope)
    rows = q.order_by(m.LeadFollowUp.closed_at.desc() if when == "done" else m.LeadFollowUp.due_at).limit(500).all()
    leads = {l.id: l for l in db.query(m.Lead).filter(m.Lead.id.in_({f.lead_id for f in rows}))} if rows else {}
    users = {u.id: u.full_name for u in db.query(m.User)}
    out = [fu_out(f, users, leads.get(f.lead_id)) for f in rows]
    if when in ("overdue", "today", "upcoming"): out = [r for r in out if r["bucket"] == when.upper()]
    counts = {"OVERDUE": 0, "TODAY": 0, "UPCOMING": 0}
    if when != "done":
        for r in out if when == "open" else [fu_out(f, users) for f in q.all()]:
            if r["bucket"] in counts: counts[r["bucket"]] += 1
    return {"items": out, "counts": counts}


@router.post("/leads/{lid}/notes", status_code=201)
def add_note(lid: str, b: NoteIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    text = b.text.strip()
    if not text: raise HTTPException(422, "Note can't be empty")
    a = crm.log(db, l, user, "NOTE", text=text); l.updated_at = func.now(); db.commit()
    return {"id": a.id, "kind": a.kind, "text": a.text, "user_name": a.user_name, "created_at": _iso(a.created_at)}


@router.post("/leads/{lid}/convert", status_code=201)
def convert(lid: str, b: ConvertIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    l = _get_lead(db, lid)
    try:
        out = crm.convert_lead(db, l, user, project_number=b.project_number.strip(), project_name=_text(b.project_name, 120), budget=b.budget)
        db.commit()
    except crm.ConvertError as e:
        db.rollback(); raise HTTPException(e.status, e.detail)
    except Exception:
        db.rollback(); raise
    return out


# ── Clients ─────────────────────────────────────────────────────────────────
def _dup(db, phone_norm, exclude_id=None):
    c = crm.find_client_by_phone(db, phone_norm)
    if c and c.id != exclude_id:
        raise HTTPException(409, f"A client with this phone number already exists: {c.name}")


@router.get("/clients")
def list_clients(q: str | None = None, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    qry = db.query(m.Client)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds = [m.Client.name.ilike(like), m.Client.company.ilike(like), m.Client.city.ilike(like), m.Client.email.ilike(like), m.Client.phone.ilike(like)]
        try: conds.append(m.Client.phone_norm == normalize_phone(q))
        except PhoneError: pass
        qry = qry.filter(or_(*conds))
    counts = dict(db.query(m.Project.client_id, func.count(m.Project.id)).group_by(m.Project.client_id).all())
    return [_client(c, counts.get(c.id, 0)) for c in qry.order_by(m.Client.name).all()]


@router.post("/clients", status_code=201)
def create_client(b: ClientIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    d = _clean(b.model_dump()); pn = normalize_phone(d["phone"])
    _dup(db, pn)
    c = m.Client(**d, phone_norm=pn); db.add(c); db.commit()
    return _client(c)


@router.get("/clients/{cid}")
def get_client(cid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*READ))):
    c = _get_client(db, cid)
    projects = db.query(m.Project).filter_by(client_id=cid).all()
    out = _client(c, len(projects))
    out["project_list"] = [{"id": p.id, "project_number": p.project_number, "name": p.name, "status": p.status} for p in projects]
    out["leads"] = [{"id": l.id, "name": l.name, "stage": l.stage} for l in db.query(m.Lead).filter_by(client_id=cid)]
    return out


@router.patch("/clients/{cid}")
def update_client(cid: str, b: ClientPatch, db: Session = Depends(get_db), user: dict = Depends(require_roles(*WRITE))):
    c = _get_client(db, cid)
    d = _clean(b.model_dump(exclude_unset=True))
    if "name" in d and not d["name"]: raise HTTPException(422, "Name can't be empty")
    if "phone" in d:
        pn = normalize_phone(d["phone"]); _dup(db, pn, exclude_id=c.id); c.phone_norm = pn
    for k, v in d.items(): setattr(c, k, v)
    db.commit()
    return _client(c, db.query(m.Project).filter_by(client_id=cid).count())
