"""Notifications — zero cost, all optional.
EMAIL: any SMTP account configured in .env (SMTP_*); messages go to an outbox and a background worker sends them (retries up to 3 times).
WHATSAPP: a free click-to-chat link (https://wa.me/<number>?text=…) — WhatsApp opens with the message typed and the USER presses send. No paid API.
AUTO: per-event switches (off by default); if an automatic email can't go out it is logged as SKIPPED with the reason — never silently dropped."""
import logging
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from string import Template
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m
from app.services import company as companylib, flow
from app.services.cost_engine import D, inr
from app.services.phone import PhoneError, normalize_phone

log = logging.getLogger("interioriq.notify")
KINDS = ["QUOTATION", "INVOICE", "PO", "DELIVERY", "HANDOVER", "PAYMENT"]
AUTO_KINDS = ["QUOTATION", "PAYMENT", "INVOICE", "DELIVERY", "HANDOVER"]      # POs go to suppliers: always sent by hand
AUTO_LABEL = {"QUOTATION": "Email the quotation PDF when a quotation is marked Sent", "PAYMENT": "Email a payment receipt when a payment is recorded",
              "INVOICE": "Email the invoice PDF when an invoice is issued", "DELIVERY": "Email the client when a delivery is dispatched",
              "HANDOVER": "Email the handover certificate when the project is handed over"}
MAX_ATTEMPTS = 3

DEFAULTS = {
    "QUOTATION": ("Quotation $quotation_no from $company",
                  "Dear $client,\n\nPlease find attached our quotation $quotation_no for $project, amounting to Rs. $amount. It is valid for $valid_days days.\n"
                  "You can also review and approve it in your client portal: $portal_url\n\nRegards,\n$company"),
    "INVOICE": ("$invoice_title $invoice_no from $company",
                "Dear $client,\n\nPlease find attached $invoice_title $invoice_no dated $date for $description: Rs. $amount.\n\nRegards,\n$company"),
    "PO": ("Purchase order $po_number from $company",
           "Dear $supplier,\n\nPlease find attached purchase order $po_number (Rs. $amount before tax) for project $project_number.\n"
           "Expected delivery: $expected. Please confirm the delivery date and quote the PO number on your invoice.\n\nRegards,\n$company"),
    "DELIVERY": ("Delivery $dn_number for $project",
                 "Dear $client,\n\nYour delivery $dn_number is scheduled for $date ($status).\nItems: $items\nVehicle: $vehicle\n\nRegards,\n$company"),
    "HANDOVER": ("Handover certificate — $project",
                 "Dear $client,\n\nThank you for choosing us. $project was handed over on $date to $received_by. Your warranty is $warranty months.\n"
                 "The handover certificate is attached.\n\nRegards,\n$company"),
    "PAYMENT": ("Payment received — Rs. $amount",
                "Dear $client,\n\nWe have received Rs. $amount on $date by $mode$reference_text towards $project. Balance due: Rs. $balance.\n\nThank you,\n$company"),
}
VARIABLES = {"QUOTATION": ["client", "company", "project", "quotation_no", "amount", "valid_days", "portal_url"],
             "INVOICE": ["client", "company", "project", "invoice_title", "invoice_no", "date", "description", "amount"],
             "PO": ["supplier", "company", "project_number", "po_number", "amount", "expected"],
             "DELIVERY": ["client", "company", "project", "dn_number", "date", "status", "items", "vehicle"],
             "HANDOVER": ["client", "company", "project", "date", "received_by", "warranty"],
             "PAYMENT": ["client", "company", "project", "amount", "date", "mode", "reference_text", "balance"]}

# M25 follow-up reminders: templates only (they are not documents — no Send drawer, no attachment)
FOLLOWUP_KINDS = ["FOLLOWUP_REMINDER", "FOLLOWUP_DIGEST", "FOLLOWUP_WHATSAPP"]
DEFAULTS.update({
    "FOLLOWUP_REMINDER": ("Reminder: $kind with $lead at $due",
                          "Hi $name,\n\n$kind with $lead is due at $due.\nPhone: $phone\nStage: $stage\nNote: $note\n\nWhatsApp the lead: $whatsapp_link\n"
                          "Record the outcome: $app_url\n\n— $company"),
    "FOLLOWUP_DIGEST": ("Your follow-ups for $date: $overdue_count overdue, $today_count today",
                        "Hi $name,\n\nHere are your follow-ups for $date.\n\n$items\n\nOpen your list and record the outcomes: $app_url\n\n— $company"),
    "FOLLOWUP_WHATSAPP": ("WhatsApp message to the lead",
                          "Hello $lead, this is $user from $company. I'm following up about your interior project — is this a good time to talk?"),
})
VARIABLES.update({"FOLLOWUP_REMINDER": ["name", "lead", "kind", "due", "phone", "stage", "note", "whatsapp_link", "app_url", "company"],
                  "FOLLOWUP_DIGEST": ["name", "date", "overdue_count", "today_count", "items", "app_url", "company"],
                  "FOLLOWUP_WHATSAPP": ["lead", "user", "company", "kind", "due"]})
TEMPLATE_KINDS = KINDS + FOLLOWUP_KINDS


class NotifyError(Exception):
    def __init__(self, status: int, detail: str): self.status, self.detail = status, detail


# ── configuration ─────────────────────────────────────────────────────────────
def email_ready() -> bool: return bool(settings.SMTP_HOST)


def sender_address(company_name: str) -> str:
    raw = settings.SMTP_FROM or settings.SMTP_USER or f"no-reply@{settings.SMTP_HOST or 'localhost'}"
    name, addr = parseaddr(raw)
    return formataddr((name or company_name, addr or raw))


def templates(db: Session) -> dict:
    out = {}
    for k in TEMPLATE_KINDS:
        row = db.get(m.CompanySetting, f"tpl:{k}")
        s, b = DEFAULTS[k]
        out[k] = {"subject": (row.value or {}).get("subject", s) if row else s, "body": (row.value or {}).get("body", b) if row else b,
                  "variables": VARIABLES[k], "customised": bool(row)}
    return out


def auto_settings(db: Session) -> dict:
    row = db.get(m.CompanySetting, "notify_auto")
    v = (row.value if row else None) or {}
    return {k: bool(v.get(k, False)) for k in AUTO_KINDS}


def render(text: str, ctx: dict) -> str:
    return Template(text).safe_substitute({k: ("" if v is None else str(v)) for k, v in ctx.items()})


EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def clean_emails(raw: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,;]", raw or "") if p.strip()]
    if not parts: raise NotifyError(422, "Enter at least one email address")
    if len(parts) > 5: raise NotifyError(422, "At most 5 recipients")
    bad = [p for p in parts if not EMAIL_RE.match(p)]
    if bad: raise NotifyError(422, f"Not a valid email address: {', '.join(bad)}")
    return parts


def whatsapp_url(phone: str, text: str) -> str:
    try: n = normalize_phone(phone)
    except PhoneError as e: raise NotifyError(422, f"WhatsApp number: {e}")
    if not n: raise NotifyError(422, "Enter a WhatsApp number")
    return f"https://wa.me/{n.lstrip('+')}?text={quote(text)}"


# ── what a message is about ───────────────────────────────────────────────────
def context(db: Session, kind: str, ref_id: str) -> dict:
    """Returns {project_id, email, phone, ctx, attachment: (fn) -> (bytes, filename) | None} for a document."""
    from app.routers import estimation as r_est, invoices as r_inv, operations as ops   # lazy: routers import this module
    comp = companylib.get(db); base = {"company": comp.get("name"), "portal_url": settings.PUBLIC_URL.rstrip("/") + "/client-portal"}
    def client_of(p): return db.get(m.Client, p.client_id) if p and p.client_id else None
    def resp(r): return r.body, re.search(r'filename="([^"]+)"', r.headers.get("content-disposition", "")).group(1)
    if kind == "QUOTATION":
        b = db.get(m.Boq, ref_id)
        if not b: raise NotifyError(404, "Quotation not found")
        p = flow.project_of_boq(db, b); c = client_of(p)
        return {"project_id": p.id, "email": c.email if c else None, "phone": c.phone if c else None,
                "ctx": {**base, "client": c.name if c else "Sir/Madam", "project": p.name, "quotation_no": flow.quote_no(p.project_number, b),
                        "amount": inr(b.totals["grand_total"]), "valid_days": comp.get("quote_valid_days")},
                "attachment": lambda: resp(r_est.quotation(b.id, db=db, user={}))}
    if kind == "INVOICE":
        i = db.get(m.Invoice, ref_id)
        if not i: raise NotifyError(404, "Invoice not found")
        p = db.get(m.Project, i.project_id); c = client_of(p)
        return {"project_id": p.id, "email": c.email if c else None, "phone": c.phone if c else None,
                "ctx": {**base, "client": c.name if c else (i.buyer or {}).get("name"), "project": p.name, "invoice_title": "Tax invoice" if i.kind == "TAX" else "Invoice",
                        "invoice_no": i.invoice_no, "date": i.issue_date.date().isoformat(), "description": i.description, "amount": inr(i.amount)},
                "attachment": lambda: (r_inv.render_pdf(i), i.invoice_no.replace("/", "-") + ".pdf")}
    if kind == "PO":
        po = db.get(m.PurchaseOrder, ref_id)
        if not po: raise NotifyError(404, "Purchase order not found")
        s = db.get(m.Supplier, po.supplier_id); p = db.get(m.Project, po.project_id); o = ops.po_out(db, po, False)
        return {"project_id": p.id, "email": s.email, "phone": s.phone,
                "ctx": {**base, "supplier": s.contact_person or s.name, "project_number": p.project_number, "po_number": po.po_number, "amount": inr(o["total"]),
                        "expected": o["expected_on"] or "to be confirmed"},
                "attachment": lambda: resp(ops.po_pdf(po.id, db, {}))}
    if kind == "DELIVERY":
        d = db.get(m.DeliveryNote, ref_id)
        if not d: raise NotifyError(404, "Delivery note not found")
        p = db.get(m.Project, d.project_id); c = client_of(p); o = ops.dn_out(db, d)
        return {"project_id": p.id, "email": c.email if c else None, "phone": c.phone if c else None,
                "ctx": {**base, "client": c.name if c else "Sir/Madam", "project": p.name, "dn_number": d.dn_number, "date": o["scheduled_on"] or "",
                        "status": d.status.lower(), "items": ", ".join(f"{l['description']} x {l['qty']}" for l in o["lines"]), "vehicle": d.vehicle or "to be confirmed"},
                "attachment": lambda: resp(ops.dn_pdf(d.id, db, {}))}
    if kind == "HANDOVER":
        p = db.get(m.Project, ref_id); h = db.query(m.Handover).filter_by(project_id=ref_id).first() if p else None
        if not h: raise NotifyError(409, "This project has not been handed over yet")
        c = client_of(p)
        return {"project_id": p.id, "email": c.email if c else None, "phone": c.phone if c else None,
                "ctx": {**base, "client": c.name if c else "Sir/Madam", "project": p.name, "date": h.handed_over_on.date().isoformat(), "received_by": h.received_by,
                        "warranty": h.warranty_months},
                "attachment": lambda: resp(ops.handover_pdf(p.id, db, {}))}
    if kind == "PAYMENT":
        pay = db.get(m.Payment, ref_id)
        if not pay: raise NotifyError(404, "Payment not found")
        p = db.get(m.Project, pay.project_id); c = client_of(p); summ = ops.payment_summary(db, p.id)
        return {"project_id": p.id, "email": c.email if c else None, "phone": c.phone if c else None,
                "ctx": {**base, "client": c.name if c else "Sir/Madam", "project": p.name, "amount": inr(pay.amount), "date": pay.received_on.date().isoformat(),
                        "mode": pay.mode, "reference_text": f" (ref. {pay.reference})" if pay.reference else "", "balance": inr(summ["balance"])},
                "attachment": None}
    raise NotifyError(422, f"kind must be one of {', '.join(KINDS)}")


def draft(db: Session, kind: str, ref_id: str) -> dict:
    """Default recipient, subject and body for the Send drawer (templates applied)."""
    c = context(db, kind, ref_id); t = templates(db)[kind]
    att = None
    if c["attachment"]:
        att = {"QUOTATION": "Quotation PDF", "INVOICE": "Invoice PDF", "PO": "Purchase order PDF", "DELIVERY": "Delivery challan PDF", "HANDOVER": "Handover certificate PDF"}[kind]
    return {"kind": kind, "ref_id": ref_id, "project_id": c["project_id"], "email": c["email"], "phone": c["phone"],
            "subject": render(t["subject"], c["ctx"]), "body": render(t["body"], c["ctx"]), "attachment": att, "email_ready": email_ready()}


# ── sending ───────────────────────────────────────────────────────────────────
def smtp_send(to: list[str], subject: str, body: str, from_name: str, attachment: tuple[bytes, str] | None = None):
    msg = EmailMessage()
    msg["From"] = sender_address(from_name); msg["To"] = ", ".join(to); msg["Subject"] = subject
    msg.set_content(body)
    if attachment: msg.add_attachment(attachment[0], maintype="application", subtype="pdf", filename=attachment[1])
    sec = (settings.SMTP_SECURITY or "starttls").lower()
    if sec == "ssl":
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
        if sec == "starttls": server.starttls(context=ssl.create_default_context())
    try:
        if settings.SMTP_USER: server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        try: server.quit()
        except Exception: pass


def queue_email(db: Session, kind: str, ref_id: str | None, project_id: str | None, to: list[str], subject: str, body: str, user: dict | None,
                trigger="MANUAL", attachment_name: str | None = None) -> m.Message:
    msg = m.Message(channel="EMAIL", kind=kind, trigger=trigger, project_id=project_id, ref_id=ref_id, to=", ".join(to), subject=subject, body=body,
                    attachment=attachment_name, status="QUEUED", user_id=(user or {}).get("sub"), user_name=(user or {}).get("name"))
    db.add(msg); return msg


def claim(db: Session, msg_id: str) -> bool:
    """QUEUED → SENDING in ONE conditional UPDATE: of several servers / workers racing for the same email exactly one wins."""
    n = db.query(m.Message).filter(m.Message.id == msg_id, m.Message.status == "QUEUED").update(
        {"status": "SENDING", "attempts": m.Message.attempts + 1, "claimed_at": flow.now()}, synchronize_session=False)
    db.commit(); return n == 1


def requeue_stale(db: Session) -> int:
    """A sender that died mid-send leaves SENDING rows. Only rows claimed longer ago than EMAIL_STALE_MINUTES go back to the queue —
    a row another server is sending right now is left alone."""
    from datetime import timedelta
    cut = flow.now() - timedelta(minutes=settings.EMAIL_STALE_MINUTES)
    n = db.query(m.Message).filter(m.Message.status == "SENDING", (m.Message.claimed_at.is_(None)) | (m.Message.claimed_at < cut)).update(
        {"status": "QUEUED"}, synchronize_session=False)
    db.commit(); return n


def deliver(db: Session, msg: m.Message):
    """Send one queued email now (used by the worker). Attachment PDF is regenerated from the document at send time."""
    if not claim(db, msg.id): return                                       # someone else is sending / sent it
    db.refresh(msg)
    try:
        att = None
        if msg.attachment and msg.kind in KINDS and msg.ref_id:
            fn = context(db, msg.kind, msg.ref_id)["attachment"]; att = fn() if fn else None
        smtp_send([x.strip() for x in msg.to.split(",")], msg.subject or "", msg.body, companylib.get(db).get("name") or "InteriorIQ", att)
        msg.status, msg.sent_at, msg.error = "SENT", flow.now(), None
        if msg.project_id: flow.event(db, msg.project_id, "MESSAGE", f"Email sent to {msg.to}: {msg.subject}", {"sub": msg.user_id, "name": msg.user_name or "System"}, "MESSAGE", msg.id)
    except Exception as e:                                                  # network/auth/refused: keep the reason, retry later
        msg.error = f"{type(e).__name__}: {str(e)[:300]}"
        msg.status = "FAILED" if msg.attempts >= MAX_ATTEMPTS else "QUEUED"
        log.warning("Email %s attempt %s failed: %s", msg.id, msg.attempts, msg.error)
    db.commit()


def process_outbox(db: Session, limit: int = 20) -> int:
    if not email_ready(): return 0
    rows = db.query(m.Message).filter(m.Message.channel == "EMAIL", m.Message.status == "QUEUED").order_by(m.Message.created_at).limit(limit).all()
    for r in rows: deliver(db, r)
    return len(rows)


_worker_started = [False]


def start_worker(session_factory, interval: float = 3.0):
    """TASK_BACKEND=thread: one daemon thread per API process polls the outbox. Claims are atomic, so even several API processes
    never send an email twice; with TASK_BACKEND=celery this thread isn't started and Celery workers send instead (app/worker.py)."""
    if _worker_started[0]: return
    _worker_started[0] = True
    def loop():
        while True:
            try:
                db = session_factory()
                try:
                    requeue_stale(db)                  # a crash mid-send leaves SENDING rows: re-queue them once they're stale
                    process_outbox(db)
                finally: db.close()
            except Exception: log.exception("notification worker")
            time.sleep(interval)
    threading.Thread(target=loop, name="notify-worker", daemon=True).start()


def auto(db: Session, kind: str, ref_id: str, user: dict | None):
    """Called after an event. Queues an automatic email when that switch is on; otherwise does nothing. If it can't be sent, logs SKIPPED + reason."""
    if not auto_settings(db).get(kind): return
    try: d = draft(db, kind, ref_id)
    except NotifyError: return
    base = dict(channel="EMAIL", kind=kind, trigger="AUTO", project_id=d["project_id"], ref_id=ref_id, subject=d["subject"], body=d["body"],
                user_id=(user or {}).get("sub"), user_name=(user or {}).get("name"))
    if not email_ready():
        db.add(m.Message(**base, to=d["email"] or "—", status="SKIPPED", error="Email is not set up (SMTP_HOST in apps/api/.env)")); return
    if not d["email"] or not EMAIL_RE.match(d["email"]):
        db.add(m.Message(**base, to="—", status="SKIPPED", error="The client has no email address")); return
    queue_email(db, kind, ref_id, d["project_id"], [d["email"]], d["subject"], d["body"], user, trigger="AUTO",
                attachment_name=None if kind == "PAYMENT" else d["attachment"])
