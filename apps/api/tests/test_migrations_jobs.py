"""M23: Alembic migrations (fresh / pre-Alembic / CLI / downgrade) and background jobs (atomic claims, stale recovery, Celery eager,
and a REAL Celery worker process on a free database broker reading a document and sending an email over real SMTP)."""
import os, shutil, socketserver, subprocess, sys, threading, time
from datetime import timedelta
from pathlib import Path

import pytest
import sqlite3
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.core.config import settings
from app.core.database import Base, SessionLocal, migrate
from app.main import app
from app.models import models as m
from app.services import documents as docs, flow, jobs, notify

API_DIR = Path(__file__).resolve().parents[1]
HEAD = "0009"


def rev(eng):
    with eng.connect() as c: return MigrationContext.configure(c).get_current_revision()


def diffs(eng):
    with eng.connect() as c: return compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


# ── migrations ────────────────────────────────────────────────────────────────
def test_fresh_database_matches_the_models_exactly(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert migrate(eng) == [] and rev(eng) == HEAD and diffs(eng) == []
    assert migrate(eng) == [] and rev(eng) == HEAD                                     # idempotent
    eng.dispose()


def test_pre_alembic_database_is_filled_in_stamped_and_upgraded(tmp_path):
    path = tmp_path / "m22.db"
    con = sqlite3.connect(path)                                                       # as left by an older InteriorIQ (create_all + add-column upgrades)
    con.execute("CREATE TABLE messages (id VARCHAR PRIMARY KEY, channel VARCHAR NOT NULL, kind VARCHAR NOT NULL, trigger VARCHAR NOT NULL, "
                "\"to\" VARCHAR NOT NULL, body TEXT NOT NULL, status VARCHAR NOT NULL, attempts INTEGER NOT NULL)")
    con.execute("INSERT INTO messages VALUES ('m1','EMAIL','QUOTATION','MANUAL','a@b.com','hello','SENT',1)")
    con.execute("CREATE TABLE clients (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, phone VARCHAR)")
    con.execute("INSERT INTO clients VALUES ('c1','Old Client','98765 43210')"); con.commit(); con.close()
    eng = create_engine(f"sqlite:///{path}")
    added = migrate(eng)
    assert "clients.phone_norm" in added and "messages.created_at" in added and rev(eng) == HEAD
    insp = inspect(eng)
    assert "claimed_at" in {c["name"] for c in insp.get_columns("messages")}                       # revision 0002 ran after the stamp
    assert {"project_members", "lead_followups", "openings"} <= set(insp.get_table_names())
    assert "ix_clients_phone_norm" in {i["name"] for i in insp.get_indexes("clients")}
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT id, status, attempts FROM messages").fetchall() == [("m1", "SENT", 1)]
        assert c.exec_driver_sql("SELECT name FROM clients").fetchall() == [("Old Client",)]
    left = [d for d in diffs(eng) if d[0] in ("add_table", "add_column", "remove_column", "remove_table")]
    assert left == []                                                                              # nothing missing (old NOT NULLs may stay looser)
    assert migrate(eng) == []
    eng.dispose()


def test_cli_and_downgrade(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}", "PYTHONIOENCODING": "utf-8"}
    alembic = [sys.executable, "-m", "alembic"]
    run = lambda *a: subprocess.run(alembic + list(a), cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)
    r = run("upgrade", "head"); assert r.returncode == 0, r.stderr
    assert HEAD in run("current").stdout
    eng = create_engine(env["DATABASE_URL"])
    r = run("downgrade", "0001"); assert r.returncode == 0, r.stderr
    assert "claimed_at" not in {c["name"] for c in inspect(eng).get_columns("messages")} and rev(eng) == "0001"
    assert run("upgrade", "head").returncode == 0 and rev(eng) == HEAD and diffs(eng) == []
    hist = run("history").stdout; assert "0001" in hist and "0002" in hist
    eng.dispose()


def test_system_status_reports_schema_and_jobs(client):
    s = client.get("/api/settings/system", headers=hdr(client)).json()
    assert s["schema"] == {"revision": HEAD, "head": HEAD, "up_to_date": True, "tool": "alembic"}
    assert s["jobs"]["backend"] == "thread" and s["jobs"]["broker"] is None and "queued_emails" in s["jobs"]


# ── atomic claims + stale recovery ──────────────────────────────────────────
def _queued_email(to="x@y.com"):
    db = SessionLocal()
    msg = notify.queue_email(db, "TEST", None, None, [to], "Hi", "Body", None); db.commit(); i = msg.id; db.close(); return i


def test_two_senders_racing_send_an_email_once(client, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "smtp_send", lambda *a, **k: (time.sleep(0.2), sent.append(a[0])))
    mid = _queued_email()
    def go():
        db = SessionLocal()
        try: notify.deliver(db, db.get(m.Message, mid))
        finally: db.close()
    ts = [threading.Thread(target=go) for _ in range(4)]
    for t in ts: t.start()
    for t in ts: t.join()
    db = SessionLocal(); msg = db.get(m.Message, mid)
    assert len(sent) == 1 and msg.status == "SENT" and msg.attempts == 1 and msg.claimed_at is not None
    db.close()


def test_only_stale_sending_emails_go_back_to_the_queue(client):
    db = SessionLocal()
    fresh, old, legacy = (m.Message(channel="EMAIL", kind="TEST", trigger="MANUAL", to="a@b.c", body="x", status="SENDING", attempts=1) for _ in range(3))
    fresh.claimed_at = flow.now(); old.claimed_at = flow.now() - timedelta(minutes=settings.EMAIL_STALE_MINUTES + 5)
    db.add_all([fresh, old, legacy]); db.commit()
    notify.requeue_stale(db)
    for x in (fresh, old, legacy): db.refresh(x)
    assert (fresh.status, old.status, legacy.status) == ("SENDING", "QUEUED", "QUEUED")          # another server's send is left alone
    db.close()


def test_a_document_is_read_once_and_stale_reads_can_be_retried(client, monkeypatch):
    h = hdr(client); pid = client.post("/api/projects", json={"project_number": "IQ-JOB-1", "name": "Jobs"}, headers=h).json()["id"]
    reads = []
    monkeypatch.setattr(docs.ocr, "extract", lambda path, kind: (time.sleep(0.2), reads.append(path))[1] or ([], "fake", 1))
    db = SessionLocal(); d = m.Document(project_id=pid, original_name="a.png", kind="png", size_bytes=1, sha256="job-1", storage_path="x", status="UPLOADED")
    db.add(d); db.commit(); did = d.id; db.close()
    ts = [threading.Thread(target=docs.process_document, args=(did,)) for _ in range(3)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(reads) == 1 and client.get(f"/api/documents/{did}", headers=h).json()["status"] == "OCR_DONE"
    db = SessionLocal(); d = db.get(m.Document, did); d.status, d.processing_started_at = "PROCESSING", flow.now(); db.commit()
    assert client.post(f"/api/documents/{did}/ocr", headers=h).status_code == 409                   # someone is reading it right now
    d.processing_started_at = flow.now() - timedelta(minutes=settings.OCR_STALE_MINUTES + 1); db.commit(); db.close()
    assert client.post(f"/api/documents/{did}/ocr", headers=h).status_code == 202                   # ...but a dead read can be retried
    db = SessionLocal(); d2 = m.Document(project_id=pid, original_name="b.png", kind="png", size_bytes=1, sha256="job-2", storage_path="x", status="PROCESSING",
                                         processing_started_at=flow.now() - timedelta(hours=2)); db.add(d2); db.commit()
    assert jobs.stale_documents(db) >= 1; db.refresh(d2); assert d2.status == "FAILED" and "longer than" in d2.error
    db.close()


# ── Celery ──────────────────────────────────────────────────────────────────
def test_celery_backend_eager(client, monkeypatch):
    from app import worker
    monkeypatch.setattr(settings, "TASK_BACKEND", "celery")
    worker.celery_app.conf.task_always_eager = True
    sent = []
    monkeypatch.setattr(notify, "smtp_send", lambda *a, **k: sent.append(a[0])); monkeypatch.setattr(notify, "email_ready", lambda: True)
    try:
        mid = _queued_email("eager@x.com")                                                 # dispatched after COMMIT, run eagerly
        db = SessionLocal(); assert db.get(m.Message, mid).status == "SENT" and sent == [["eager@x.com"]]; db.close()
        db = SessionLocal(); x = m.Message(channel="EMAIL", kind="TEST", trigger="MANUAL", to="r@x.com", body="b", status="QUEUED", attempts=0)
        db.add(x); db.rollback(); db.close()                                                # rolled back → nothing dispatched
        assert len(sent) == 1
    finally:
        worker.celery_app.conf.task_always_eager = False


class _SMTP(socketserver.StreamRequestHandler):
    got: list = []
    def w(self, s): self.wfile.write((s + "\r\n").encode())
    def handle(self):
        self.w("220 test"); rcpts = []
        while True:
            line = self.rfile.readline().decode(errors="replace").strip()
            if not line: return
            up = line.upper()
            if up.startswith(("EHLO", "HELO")): self.w("250-test"); self.w("250 8BITMIME")
            elif up.startswith("MAIL"): self.w("250 ok")
            elif up.startswith("RCPT"): rcpts.append(line.split(":", 1)[1].strip(" <>")); self.w("250 ok")
            elif up == "DATA":
                self.w("354 go"); data = []
                while (l := self.rfile.readline().decode(errors="replace")) not in (".\r\n", ".\n", ""): data.append(l)
                _SMTP.got.append((rcpts[:], "".join(data))); rcpts.clear(); self.w("250 queued")
            elif up == "QUIT": self.w("221 bye"); return
            else: self.w("250 ok")


def _wait(fn, secs=150):
    end = time.time() + secs
    while time.time() < end:
        if fn(): return True
        time.sleep(1)
    return False


@pytest.mark.skipif(shutil.which("celery") is None and not (Path(sys.executable).parent / "celery.exe").exists(), reason="celery not installed")
def test_real_celery_worker_reads_a_document_and_sends_an_email(client, tmp_path):
    from tests.test_documents import text_pdf
    from app import worker
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    broker = os.environ.get("IQ_TEST_BROKER") or f"sqla+sqlite:///{(tmp_path / 'broker.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": settings.DATABASE_URL, "STORAGE_PATH": settings.STORAGE_PATH, "TASK_BACKEND": "celery", "CELERY_BROKER_URL": broker,
           "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_SECURITY": "none", "SMTP_FROM": "Studio <studio@iq.test>", "PYTHONIOENCODING": "utf-8"}
    log = open(tmp_path / "worker.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "celery", "-A", "app.worker", "worker", "--pool=solo", "--loglevel=info"], cwd=API_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    old = worker.celery_app.conf.broker_url
    try:
        worker.celery_app.conf.broker_url = broker
        h = hdr(client); pid = client.post("/api/projects", json={"project_number": "IQ-CELERY-1", "name": "Celery"}, headers=h).json()["id"]
        data = text_pdf(["MASTER BEDROOM", "Length 4250 mm", "Width 3600 mm"])
        db = SessionLocal()
        d = m.Document(project_id=pid, original_name="plan.pdf", kind="pdf", size_bytes=len(data), sha256="celery-1", storage_path="", status="UPLOADED")
        db.add(d); db.flush(); d.storage_path = docs.store(pid, d.id, "pdf", data); db.commit(); did = d.id; db.close()
        worker.ocr_document.delay(did)
        def done():
            db = SessionLocal()
            try: return db.get(m.Document, did).status in ("OCR_DONE", "FAILED")
            finally: db.close()
        assert _wait(done), (tmp_path / "worker.log").read_text()[-2000:]
        got = client.get(f"/api/documents/{did}", headers=h).json()
        assert got["status"] == "OCR_DONE" and 4250.0 in {c["value_mm"] for c in got["candidates"]}, got.get("error")
        mid = _queued_email("client@iq.test")
        worker.send_email.delay(mid); worker.send_email.delay(mid)                       # handed over twice → sent once
        def sent():
            db = SessionLocal()
            try: return db.get(m.Message, mid).status == "SENT"
            finally: db.close()
        assert _wait(sent), (tmp_path / "worker.log").read_text()[-2000:]
        time.sleep(3)
        assert [r for r, _ in _SMTP.got].count(["client@iq.test"]) == 1
    finally:
        worker.celery_app.conf.broker_url = old
        if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else: proc.terminate()
        proc.wait(timeout=30); log.close(); srv.shutdown()
