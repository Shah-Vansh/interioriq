"""Celery worker for InteriorIQ (only used with TASK_BACKEND=celery).

Start one or more (each needs the same .env as the API: DATABASE_URL, STORAGE_PATH, SMTP_*, CELERY_BROKER_URL):
    cd apps/api && celery -A app.worker worker --loglevel=info              # Linux / macOS
    cd apps/api && celery -A app.worker worker --pool=solo --loglevel=info  # Windows (prefork isn't supported there)

Tasks: iq.ocr_document(doc_id), iq.send_email(message_id), iq.sweep(token). The sweep runs every SWEEP_SECONDS from the newest worker:
it re-queues emails whose sender died (SENDING too long), hands still-QUEUED emails and still-UPLOADED documents to the queue again (the
database is the source of truth; atomic claims make duplicates harmless), and fails documents that have been 'reading' too long."""
import logging
import uuid
from datetime import timedelta

from celery import Celery
from celery.signals import worker_ready

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import models as m

log = logging.getLogger("interioriq.worker")
SWEEP_SECONDS = 60
EMAIL_RETRY_SECONDS = 30

celery_app = Celery("interioriq", broker=settings.CELERY_BROKER_URL or "sqla+sqlite:///./celery-broker.db")
celery_app.conf.update(task_ignore_result=True, task_acks_late=True, worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
                       task_default_queue="interioriq", worker_hijack_root_logger=False)


@celery_app.task(name="iq.ocr_document")
def ocr_document(doc_id: str):
    from app.services import documents as docs
    docs.process_document(doc_id)


@celery_app.task(name="iq.send_email")
def send_email(message_id: str):
    from app.services import notify
    db = SessionLocal()
    try:
        msg = db.get(m.Message, message_id)
        if not msg or msg.status != "QUEUED": return
        if not notify.email_ready(): log.warning("Email %s waits: SMTP is not set up for this worker", message_id); return
        notify.deliver(db, msg)
        db.refresh(msg)
        if msg.status == "QUEUED": send_email.apply_async((message_id,), countdown=EMAIL_RETRY_SECONDS)     # failed attempt, tries left
    finally:
        db.close()


@celery_app.task(name="iq.sweep")
def sweep(token: str):
    from app.services import flow, jobs, notify
    db = SessionLocal()
    try:
        row = db.get(m.CompanySetting, "_worker_sweep_token")
        if not row or row.value != token: return                                    # a newer worker took over the sweep
        notify.requeue_stale(db)
        now = flow.now()
        queued = [x.id for x in db.query(m.Message.id).filter(m.Message.channel == "EMAIL", m.Message.status == "QUEUED")]
        if queued and notify.email_ready(): jobs.send_emails(queued)
        waiting = [d.id for d in db.query(m.Document.id, m.Document.created_at).filter(m.Document.status == "UPLOADED")
                   if d.created_at is None or (d.created_at.replace(tzinfo=now.tzinfo) if d.created_at.tzinfo is None else d.created_at) < now - timedelta(minutes=2)]
        for i in waiting: ocr_document.delay(i)
        jobs.stale_documents(db, now)
    except Exception:
        log.exception("sweep failed")
    finally:
        db.close()
    sweep.apply_async((token,), countdown=SWEEP_SECONDS)


@worker_ready.connect
def _start_sweep(sender=None, **kw):
    token = uuid.uuid4().hex
    db = SessionLocal()
    try:
        row = db.get(m.CompanySetting, "_worker_sweep_token")
        if row: row.value = token
        else: db.add(m.CompanySetting(key="_worker_sweep_token", value=token, updated_by="worker"))
        db.commit()
    finally:
        db.close()
    sweep.apply_async((token,), countdown=2)
