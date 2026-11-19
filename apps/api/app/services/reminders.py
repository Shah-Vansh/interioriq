"""M25 follow-up reminders — zero cost.

EMAIL (needs SMTP in .env, like every other email):
  * "due soon": the person a follow-up is assigned to gets one email `before_minutes` before it is due (with the lead's phone and a
    one-tap WhatsApp link). Claimed per follow-up with ONE conditional UPDATE on reminded_at, so several servers / workers never send
    it twice; rescheduling or reassigning clears reminded_at so the new time / person is reminded again. A follow-up the assignee booked
    themselves inside the reminder window is not reminded (they just set it).
  * morning summary: once per local day after `digest_hour`, each person with overdue or today's follow-ups gets ONE email listing them.
    Claimed per day in job_locks (one server sends it).
  If email isn't set up or the person has no address, the reminder is logged SKIPPED with the reason (never silently dropped).
WHATSAPP: free click-to-chat links (routers/crm.py) — to the lead, or to the assignee as a reminder; the user presses send.

Everything is OFF until an admin switches it on in Settings → Notifications. Runs from a thread in the API (thread backend) or from the
Celery sweep (celery backend): tick() is the one entry point."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m
from app.services import company as companylib, flow, followups as fups, notify

log = logging.getLogger("interioriq.reminders")
KEY = "followup_reminders"
DEFAULTS = {"enabled": False, "before_minutes": 30, "digest": True, "digest_hour": 9}
BEFORE_CHOICES = [0, 15, 30, 60, 120]          # 0 = no "due soon" email
KIND_LABEL = {"CALL": "Call", "VISIT": "Site visit", "MEETING": "Meeting", "WHATSAPP": "WhatsApp", "EMAIL": "Email", "OTHER": "Follow-up"}
SYSTEM = {"sub": None, "name": "Reminders"}


def _aware(t): return fups._aware(t)


def get(db: Session) -> dict:
    row = db.get(m.CompanySetting, KEY)
    v = (row.value if row else None) or {}
    return {k: v.get(k, d) for k, d in DEFAULTS.items()}


def save(db: Session, patch: dict, by: str | None) -> dict:
    bad = [k for k in patch if k not in DEFAULTS]
    if bad: raise ValueError(f"Unknown setting(s): {', '.join(bad)}")
    cur = get(db)
    for k, v in patch.items():
        if k in ("enabled", "digest"):
            if not isinstance(v, bool): raise ValueError(f"{k} must be true or false")
        elif k == "before_minutes":
            if not isinstance(v, int) or isinstance(v, bool) or v not in BEFORE_CHOICES: raise ValueError(f"before_minutes must be one of {', '.join(map(str, BEFORE_CHOICES))}")
        elif k == "digest_hour":
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 23: raise ValueError("digest_hour must be a whole hour from 0 to 23")
        cur[k] = v
    row = db.get(m.CompanySetting, KEY)
    if row: row.value, row.updated_by = dict(cur), by
    else: db.add(m.CompanySetting(key=KEY, value=dict(cur), updated_by=by))
    db.commit(); return get(db)


def local(t: datetime) -> datetime: return _aware(t).astimezone(fups.local_tz())


def fmt(t: datetime) -> str: return f"{local(t):%d %b %Y %H:%M}"


def app_url() -> str: return settings.PUBLIC_URL.rstrip("/") + "/crm/followups"


# ── message text ──────────────────────────────────────────────────────────────
def whatsapp_text(db: Session, f: m.LeadFollowUp, lead: m.Lead, sender: str | None) -> str:
    t = notify.templates(db)["FOLLOWUP_WHATSAPP"]
    return notify.render(t["body"], {"lead": lead.name, "user": sender or "our team", "company": companylib.get(db).get("name") or "our studio",
                                     "kind": KIND_LABEL.get(f.kind, f.kind).lower(), "due": fmt(f.due_at)})


def lead_whatsapp_link(db: Session, f: m.LeadFollowUp, lead: m.Lead, sender: str | None) -> str | None:
    if not lead.phone: return None
    try: return notify.whatsapp_url(lead.phone, whatsapp_text(db, f, lead, sender))
    except notify.NotifyError: return None


def reminder(db: Session, f: m.LeadFollowUp, lead: m.Lead, user: m.User | None) -> tuple[str, str]:
    """(subject, body) of the 'due soon' reminder for the assignee — also the text of the WhatsApp reminder."""
    t = notify.templates(db)["FOLLOWUP_REMINDER"]; name = user.full_name if user else "team"
    ctx = {"name": name.split(" ")[0], "lead": lead.name, "kind": KIND_LABEL.get(f.kind, f.kind), "due": fmt(f.due_at), "phone": lead.phone or "—",
           "stage": lead.stage.replace("_", " ").title(), "note": f.note or "—", "whatsapp_link": lead_whatsapp_link(db, f, lead, name) or "— (no valid phone)",
           "app_url": app_url(), "company": companylib.get(db).get("name") or "InteriorIQ"}
    return notify.render(t["subject"], ctx), notify.render(t["body"], ctx)


def digest_items(db: Session, uid: str, now: datetime) -> tuple[list, list]:
    """(overdue, today) open follow-ups of one person, each as (follow-up, lead); closed/archived leads left out."""
    rows = db.query(m.LeadFollowUp).filter(m.LeadFollowUp.status == "OPEN", m.LeadFollowUp.assigned_to == uid).order_by(m.LeadFollowUp.due_at).all()
    leads = {l.id: l for l in db.query(m.Lead).filter(m.Lead.id.in_({f.lead_id for f in rows}))} if rows else {}
    over, today = [], []
    for f in rows:
        l = leads.get(f.lead_id)
        if not l or l.archived or l.stage in ("WON", "LOST"): continue
        b = fups.bucket(f.due_at, now)
        if b == "OVERDUE": over.append((f, l))
        elif b == "TODAY": today.append((f, l))
    return over, today


def digest(db: Session, user: m.User, now: datetime) -> tuple[str, str, int] | None:
    """(subject, body, count) of one person's morning summary, or None when they have nothing overdue or due today."""
    over, today = digest_items(db, user.id, now)
    if not over and not today: return None
    def line(f, l, when):
        wa = lead_whatsapp_link(db, f, l, user.full_name)
        return (f"• {when}  {KIND_LABEL.get(f.kind, f.kind)} — {l.name}" + (f" ({l.phone})" if l.phone else "")
                + (f"\n    {f.note}" if f.note else "") + (f"\n    WhatsApp: {wa}" if wa else ""))
    parts = []
    if over: parts.append(f"OVERDUE ({len(over)})\n" + "\n".join(line(f, l, fmt(f.due_at)) for f, l in over))
    if today: parts.append(f"TODAY ({len(today)})\n" + "\n".join(line(f, l, f"{local(f.due_at):%H:%M}") for f, l in today))
    t = notify.templates(db)["FOLLOWUP_DIGEST"]
    ctx = {"name": user.full_name.split(" ")[0], "date": f"{now.astimezone(fups.local_tz()):%d %b %Y}", "overdue_count": len(over), "today_count": len(today),
           "items": "\n\n".join(parts), "app_url": app_url(), "company": companylib.get(db).get("name") or "InteriorIQ"}
    return notify.render(t["subject"], ctx), notify.render(t["body"], ctx), len(over) + len(today)


def _queue(db: Session, kind: str, ref_id: str, user: m.User | None, subject: str, body: str) -> m.Message:
    base = dict(channel="EMAIL", kind=kind, trigger="AUTO", project_id=None, ref_id=ref_id, subject=subject, body=body, user_id=None, user_name=SYSTEM["name"])
    if not notify.email_ready():
        msg = m.Message(**base, to=(user.email if user else None) or "—", status="SKIPPED", error="Email is not set up (SMTP_HOST in apps/api/.env)")
    elif not user or not user.email or not notify.EMAIL_RE.match(user.email):
        msg = m.Message(**base, to="—", status="SKIPPED", error="The person it is assigned to has no email address")
    else:
        return notify.queue_email(db, kind, ref_id, None, [user.email], subject, body, None, trigger="AUTO")
    db.add(msg); return msg


# ── the two jobs ─────────────────────────────────────────────────────────────
def send_due(db: Session, now: datetime | None = None) -> int:
    """'Due soon' emails for follow-ups due within before_minutes from now. Returns how many reminders were claimed."""
    cfg = get(db)
    if not cfg["enabled"] or not cfg["before_minutes"]: return 0
    now = now or flow.now(); window = timedelta(minutes=cfg["before_minutes"])
    rows = db.query(m.LeadFollowUp).filter(m.LeadFollowUp.status == "OPEN", m.LeadFollowUp.reminded_at.is_(None),
                                           m.LeadFollowUp.due_at > now, m.LeadFollowUp.due_at <= now + window).all()
    n = 0
    for f in rows:
        won = db.query(m.LeadFollowUp).filter(m.LeadFollowUp.id == f.id, m.LeadFollowUp.reminded_at.is_(None)).update(
            {"reminded_at": now}, synchronize_session=False)
        db.commit()
        if won != 1: continue                                              # another server / worker has it
        db.refresh(f); lead = db.get(m.Lead, f.lead_id)
        if not lead or lead.archived or lead.stage in ("WON", "LOST"): continue
        if not f.assigned_to: continue                                     # nobody to remind (the lead has no owner)
        if f.created_by == f.assigned_to and f.created_at and _aware(f.created_at) > _aware(f.due_at) - window: continue   # booked it themselves just now
        user = db.get(m.User, f.assigned_to)
        if user is not None and user.is_active is False: continue
        subject, body = reminder(db, f, lead, user)
        _queue(db, "FOLLOWUP_REMINDER", f.id, user, subject, body); db.commit(); n += 1
    return n


def claim_digest(db: Session, now: datetime, force: bool = False) -> bool:
    """True for exactly one server per local day, once it's past digest_hour (or straight away when force)."""
    cfg = get(db); now_local = now.astimezone(fups.local_tz())
    if not force and now_local.hour < cfg["digest_hour"]: return False
    today = now_local.date().isoformat()
    if not db.get(m.JobLock, "followup_digest"):
        try: db.add(m.JobLock(name="followup_digest", value="")); db.commit()
        except Exception: db.rollback()
    won = db.query(m.JobLock).filter(m.JobLock.name == "followup_digest", (m.JobLock.value.is_(None)) | (m.JobLock.value != today)).update(
        {"value": today, "updated_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit(); return won == 1


def send_digests(db: Session, now: datetime | None = None, force: bool = False) -> int | None:
    """Morning summaries. None = not due / already sent today; else the number of people emailed (or logged as skipped)."""
    cfg = get(db)
    if not cfg["enabled"] or not cfg["digest"]: return None
    now = now or flow.now()
    if not claim_digest(db, now, force): return None
    uids = {r[0] for r in db.query(m.LeadFollowUp.assigned_to).filter(m.LeadFollowUp.status == "OPEN", m.LeadFollowUp.assigned_to.isnot(None)).distinct()}
    n = 0
    for u in db.query(m.User).filter(m.User.id.in_(uids)).order_by(m.User.full_name).all() if uids else []:
        if u.is_active is False: continue
        d = digest(db, u, now)
        if not d: continue
        _queue(db, "FOLLOWUP_DIGEST", u.id, u, d[0], d[1]); n += 1
    db.commit(); return n


def tick(db: Session, now: datetime | None = None) -> dict:
    return {"due_soon": send_due(db, now), "digests": send_digests(db, now)}


_started = [False]


def start_scheduler(session_factory, interval: float = 60):
    """TASK_BACKEND=thread: one daemon thread per API process (claims make several processes safe). Celery: the worker sweep calls tick()."""
    if _started[0]: return
    _started[0] = True
    def loop():
        time.sleep(15)
        while True:
            try:
                db = session_factory()
                try: tick(db)
                finally: db.close()
            except Exception: log.exception("follow-up reminders")
            time.sleep(interval)
    threading.Thread(target=loop, name="followup-reminders", daemon=True).start()
