"""Background work — reading uploaded documents (OCR) and sending queued emails — on one of two backends (TASK_BACKEND):

  thread (default, zero setup): OCR runs in a FastAPI background task / thread inside the API process; a daemon thread in the API sends
          queued emails every few seconds. Right for one API server.
  celery: the API only records the work and hands it to Celery; separate worker processes (`celery -A app.worker worker`) do it, so you can
          run several API servers and several workers. The broker can be a plain database (CELERY_BROKER_URL=sqla+sqlite:///… or
          sqla+postgresql://…, free, no extra server) or Redis / RabbitMQ.

Either way the work itself is the same code (documents.process_document, notify.deliver), every job is CLAIMED atomically in the database
first (so two servers / workers never read the same document or send the same email twice), and stale claims are recovered by time."""
import logging
import threading
from datetime import timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import models as m

log = logging.getLogger("interioriq.jobs")


def celery_on() -> bool: return settings.TASK_BACKEND.strip().lower() == "celery"


def backend() -> str: return "celery" if celery_on() else "thread"


def ocr(doc_id: str, bg=None):
    """Queue a document for reading (its status is UPLOADED = waiting)."""
    from app.services import documents as docs
    if celery_on():
        from app.worker import ocr_document
        ocr_document.delay(doc_id)
    elif bg is not None: bg.add_task(docs.process_document, doc_id)
    else: threading.Thread(target=docs.process_document, args=(doc_id,), name=f"ocr-{doc_id[:8]}", daemon=True).start()


def send_emails(ids):
    if not ids or not celery_on(): return            # thread backend: the notify worker thread polls the outbox
    from app.worker import send_email
    for i in ids: send_email.delay(i)


# Emails are queued (status QUEUED) inside request transactions all over the app (manual sends, automatic notifications, retries).
# Hand them to Celery only AFTER the transaction commits — otherwise a fast worker could look before the row exists.
@event.listens_for(Session, "after_flush")
def _collect(session, ctx):
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, m.Message) and obj.channel == "EMAIL" and obj.status == "QUEUED":
            session.info.setdefault("iq_emails", set()).add(obj.id)


@event.listens_for(Session, "after_commit")
def _dispatch(session):
    ids = session.info.pop("iq_emails", None)
    if ids and celery_on():
        try: send_emails(sorted(ids))
        except Exception: log.exception("Could not hand %s email(s) to Celery; the worker's sweep will pick them up", len(ids))


@event.listens_for(Session, "after_rollback")
def _forget(session): session.info.pop("iq_emails", None)


# ── recovery (time based, safe with several servers) ─────────────────────────
def stale_documents(db: Session, now=None) -> int:
    from app.services import flow
    now = now or flow.now(); cut = now - timedelta(minutes=settings.OCR_STALE_MINUTES)
    rows = db.query(m.Document).filter(m.Document.status == "PROCESSING").all()
    n = 0
    for d in rows:
        started = d.processing_started_at
        if started is not None and started.tzinfo is None: started = started.replace(tzinfo=now.tzinfo)
        if started is None or started < cut:
            d.status, d.error = "FAILED", f"Reading took longer than {settings.OCR_STALE_MINUTES} minutes and was stopped. Click Re-read to try again."; n += 1
    db.commit(); return n


def is_stale(d: m.Document, now=None) -> bool:
    from app.services import flow
    if d.status != "PROCESSING": return False
    now = now or flow.now(); started = d.processing_started_at
    if started is None: return True
    if started.tzinfo is None: started = started.replace(tzinfo=now.tzinfo)
    return started < now - timedelta(minutes=settings.OCR_STALE_MINUTES)
