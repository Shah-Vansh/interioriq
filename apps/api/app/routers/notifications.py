"""Send documents by email (SMTP outbox) or WhatsApp (click-to-chat link), templates, automatic-email switches, message history."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_roles
from app.models import models as m
from app.services import access
from app.services import company as companylib, flow, notify

router = APIRouter(tags=["Notifications"])
STAFF = tuple(r for r in m.ROLES if r not in ("CLIENT", "SUPER_ADMIN"))
ADMIN = ("ADMIN",)
# who may send which document (same people who may act on it)
SENDERS = {"QUOTATION": ("ADMIN", "PROJECT_MANAGER", "SALES", "ESTIMATOR"), "INVOICE": ("ADMIN", "PROJECT_MANAGER", "SALES"),
           "PO": ("ADMIN", "PROJECT_MANAGER", "PROCUREMENT_MANAGER"), "DELIVERY": ("ADMIN", "PROJECT_MANAGER", "INVENTORY_MANAGER", "INSTALLATION_MANAGER"),
           "HANDOVER": ("ADMIN", "PROJECT_MANAGER"), "PAYMENT": ("ADMIN", "PROJECT_MANAGER", "SALES")}


def _fail(e: notify.NotifyError): raise HTTPException(e.status, e.detail)


def _can(user: dict, kind: str):
    if user.get("role") != "SUPER_ADMIN" and user.get("role") not in SENDERS.get(kind, ()):
        raise HTTPException(403, f"Requires one of: {', '.join(SENDERS.get(kind, ()))}")


def msg_out(x: m.Message) -> dict:
    return {"id": x.id, "channel": x.channel, "kind": x.kind, "trigger": x.trigger, "project_id": x.project_id, "ref_id": x.ref_id, "to": x.to, "subject": x.subject,
            "body": x.body, "attachment": x.attachment, "status": x.status, "error": x.error, "attempts": x.attempts, "user_name": x.user_name,
            "created_at": x.created_at.isoformat() if x.created_at else None, "sent_at": x.sent_at.isoformat() if x.sent_at else None}


@router.get("/notifications/status")
def status(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    return {"email_ready": notify.email_ready(), "smtp_host": settings.SMTP_HOST or None, "smtp_port": settings.SMTP_PORT, "smtp_security": settings.SMTP_SECURITY,
            "from": notify.sender_address(companylib.get(db).get("name") or "InteriorIQ") if notify.email_ready() else None,
            "public_url": settings.PUBLIC_URL, "auto": notify.auto_settings(db), "auto_labels": notify.AUTO_LABEL,
            "queued": db.query(m.Message).filter_by(status="QUEUED").count(), "failed": db.query(m.Message).filter_by(status="FAILED").count(),
            "how_to": "Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM and SMTP_SECURITY (starttls/ssl/none) to apps/api/.env and restart the API. "
                      "Gmail: smtp.gmail.com, 587, starttls, your address and a Google 'App password'."}


@router.get("/notifications/draft")
def get_draft(kind: str, ref_id: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _can(user, kind)
    try: d = notify.draft(db, kind, ref_id)
    except notify.NotifyError as e: _fail(e)
    access.check(db, user, d.get("project_id")); return d


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    ref_id: str
    channel: str
    to: str = Field(min_length=3, max_length=500)
    subject: str | None = Field(None, max_length=300)
    body: str = Field(min_length=1, max_length=10000)
    attach: bool = True
    mark_sent: bool = False          # quotations: also mark a DRAFT quotation as SENT


@router.post("/notifications/send", status_code=201)
def send(b: SendIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    _can(user, b.kind)
    try:
        d = notify.draft(db, b.kind, b.ref_id)                     # also proves the document exists
        access.check(db, user, d.get("project_id"))
        if b.channel == "EMAIL":
            if not notify.email_ready(): raise notify.NotifyError(409, "Email is not set up yet — see Settings → Notifications (or use WhatsApp).")
            if not (b.subject or "").strip(): raise notify.NotifyError(422, "Enter a subject")
            to = notify.clean_emails(b.to)
            msg = notify.queue_email(db, b.kind, b.ref_id, d["project_id"], to, b.subject.strip(), b.body, user, attachment_name=d["attachment"] if b.attach else None)
            url = None
        elif b.channel == "WHATSAPP":
            url = notify.whatsapp_url(b.to, b.body)
            msg = m.Message(channel="WHATSAPP", kind=b.kind, trigger="MANUAL", project_id=d["project_id"], ref_id=b.ref_id, to=b.to.strip(), subject=None, body=b.body,
                            status="LINK", user_id=user.get("sub"), user_name=user.get("name"))
            db.add(msg)
            if d["project_id"]: flow.event(db, d["project_id"], "MESSAGE", f"WhatsApp opened for {b.to.strip()} ({b.kind.lower()})", user, "MESSAGE", None)
        else: raise notify.NotifyError(422, "channel must be EMAIL or WHATSAPP")
    except notify.NotifyError as e: db.rollback(); _fail(e)
    if b.mark_sent and b.kind == "QUOTATION":
        from app.routers import operations as ops
        bq = db.get(m.Boq, b.ref_id)
        if flow.boq_status(bq) in ("DRAFT", "REJECTED"): ops.set_quote_status(db, bq, "SENT", f"Sent by {b.channel.lower()} to {b.to.strip()}", user)
    db.commit()
    return {**msg_out(msg), "whatsapp_url": url}


@router.get("/messages")
def messages(project_id: str | None = None, ref_id: str | None = None, status: str | None = None, limit: int = 200, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    q = access.scope(db.query(m.Message), m.Message.project_id, db, user)
    if project_id: q = q.filter_by(project_id=project_id)
    if ref_id: q = q.filter_by(ref_id=ref_id)
    if status: q = q.filter_by(status=status)
    return [msg_out(x) for x in q.order_by(m.Message.created_at.desc()).limit(max(1, min(limit, 1000)))]


@router.post("/messages/{mid}/retry")
def retry(mid: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    x = db.get(m.Message, mid)
    if not x: raise HTTPException(404, "Message not found")
    _can(user, x.kind) if x.kind in notify.KINDS else None
    if x.channel != "EMAIL" or x.status not in ("FAILED", "SKIPPED"): raise HTTPException(409, "Only a failed or skipped email can be retried")
    if not notify.email_ready(): raise HTTPException(409, "Email is not set up yet — see Settings → Notifications")
    if x.status == "SKIPPED" and not notify.EMAIL_RE.match(x.to or ""): raise HTTPException(409, "There is no valid recipient; send it again from the document with an address")
    x.status, x.attempts, x.error = "QUEUED", 0, None; db.commit(); return msg_out(x)


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=3, max_length=200)


@router.post("/notifications/test")
def test_email(b: TestIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMIN))):
    """Send a test email right now (not via the queue) and report exactly what the mail server said."""
    if not notify.email_ready(): raise HTTPException(409, "Email is not set up: add SMTP_HOST etc. to apps/api/.env and restart the API")
    try: to = notify.clean_emails(b.to)
    except notify.NotifyError as e: _fail(e)
    name = companylib.get(db).get("name") or "InteriorIQ"
    try: notify.smtp_send(to, f"Test email from {name}", f"This is a test from InteriorIQ. If you can read this, email is working.\n\n— {name}", name)
    except Exception as e:
        db.add(m.Message(channel="EMAIL", kind="TEST", to=", ".join(to), subject="Test email", body="(test)", status="FAILED", error=f"{type(e).__name__}: {str(e)[:300]}",
                         attempts=1, user_id=user.get("sub"), user_name=user.get("name"))); db.commit()
        raise HTTPException(502, f"The mail server refused or could not be reached: {type(e).__name__}: {str(e)[:200]}")
    db.add(m.Message(channel="EMAIL", kind="TEST", to=", ".join(to), subject="Test email", body="(test)", status="SENT", attempts=1, sent_at=flow.now(),
                     user_id=user.get("sub"), user_name=user.get("name"))); db.commit()
    return {"ok": True, "to": to}


@router.get("/notifications/templates")
def get_templates(db: Session = Depends(get_db), user: dict = Depends(require_roles(*STAFF))):
    return notify.templates(db)


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


@router.put("/notifications/templates/{kind}")
def put_template(kind: str, b: TemplateIn, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMIN))):
    if kind not in notify.KINDS: raise HTTPException(404, "Unknown template")
    import re
    unknown = sorted(set(re.findall(r"\$\{?([a-z_]+)\}?", b.subject + " " + b.body)) - set(notify.VARIABLES[kind]))
    if unknown: raise HTTPException(422, f"Unknown placeholder(s): {', '.join('$' + u for u in unknown)}. Allowed: {', '.join('$' + v for v in notify.VARIABLES[kind])}")
    row = db.get(m.CompanySetting, f"tpl:{kind}")
    if row: row.value, row.updated_by = {"subject": b.subject, "body": b.body}, user.get("name")
    else: db.add(m.CompanySetting(key=f"tpl:{kind}", value={"subject": b.subject, "body": b.body}, updated_by=user.get("name")))
    db.commit(); return notify.templates(db)[kind]


@router.delete("/notifications/templates/{kind}")
def reset_template(kind: str, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMIN))):
    if kind not in notify.KINDS: raise HTTPException(404, "Unknown template")
    row = db.get(m.CompanySetting, f"tpl:{kind}")
    if row: db.delete(row); db.commit()
    return notify.templates(db)[kind]


@router.put("/notifications/auto")
def put_auto(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles(*ADMIN))):
    bad = [k for k in body if k not in notify.AUTO_KINDS]
    if bad: raise HTTPException(422, f"Unknown event(s): {', '.join(bad)}")
    if any(not isinstance(v, bool) for v in body.values()): raise HTTPException(422, "Each switch must be true or false")
    cur = notify.auto_settings(db); cur.update(body)
    row = db.get(m.CompanySetting, "notify_auto")
    if row: row.value, row.updated_by = cur, user.get("name")
    else: db.add(m.CompanySetting(key="notify_auto", value=cur, updated_by=user.get("name")))
    db.commit(); return notify.auto_settings(db)
