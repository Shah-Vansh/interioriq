"""Notifications: email through an SMTP outbox (with a fake mail server here), WhatsApp click-to-chat links, templates, automatic emails, roles."""
import email
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import notify


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL: records what would have been sent."""
    sent: list = []; calls: list = []; fail_with: Exception | None = None
    def __init__(self, host, port, timeout=None, context=None): FakeSMTP.calls.append(("connect", host, port, type(self).__name__))
    def starttls(self, context=None): FakeSMTP.calls.append(("starttls",))
    def login(self, u, p): FakeSMTP.calls.append(("login", u))
    def send_message(self, msg):
        if FakeSMTP.fail_with: raise FakeSMTP.fail_with
        FakeSMTP.sent.append(email.message_from_bytes(msg.as_bytes()))
    def quit(self): pass


class FakeSMTPSSL(FakeSMTP): pass


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, r in (("des15@test.com", "INTERIOR_DESIGNER"), ("proc15@test.com", "PROCUREMENT_MANAGER"), ("sales15@test.com", "SALES")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=r.title(), role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


@pytest.fixture
def mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.calls, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP); monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTPSSL)
    for k, v in (("SMTP_HOST", "smtp.test"), ("SMTP_PORT", 587), ("SMTP_USER", "studio@test.com"), ("SMTP_PASSWORD", "x"), ("SMTP_FROM", ""), ("SMTP_SECURITY", "starttls")):
        monkeypatch.setattr(settings, k, v)
    return FakeSMTP


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def drain():
    db = SessionLocal()
    try: return notify.process_outbox(db)
    finally: db.close()


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def job(c, h, email_addr="client@example.com", approve=False):
    n = u()
    cl = c.post("/api/clients", json={"name": f"Notify client {n}", "phone": f"9{n + 100000000:09d}", **({"email": email_addr} if email_addr else {})}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": f"IQ-NT-{n}", "name": "Notify flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    if approve: c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    return pid, b, cl


def test_whatsapp_link_works_without_any_setup_and_can_mark_the_quote_sent(client):
    h = hdr(client); pid, b, cl = job(client, h)
    d = client.get("/api/notifications/draft", params={"kind": "QUOTATION", "ref_id": b["id"]}, headers=h).json()
    assert d["email_ready"] is False and d["phone"] == cl["phone"] and b["quotation_no"] in d["subject"] and "/client-portal" in d["body"]
    r = client.post("/api/notifications/send", json={"kind": "QUOTATION", "ref_id": b["id"], "channel": "EMAIL", "to": "a@b.com", "subject": "x", "body": "y"}, headers=h)
    assert r.status_code == 409 and "not set up" in r.json()["detail"]
    r = client.post("/api/notifications/send", json={"kind": "QUOTATION", "ref_id": b["id"], "channel": "WHATSAPP", "to": "098765 43210", "body": d["body"], "mark_sent": True}, headers=h).json()
    assert r["whatsapp_url"].startswith("https://wa.me/919876543210?text=") and b["quotation_no"] in unquote(r["whatsapp_url"]) and r["status"] == "LINK"
    assert client.get(f"/api/boqs/{b['id']}", headers=h).json() and [q for q in client.get("/api/quotations", params={"project_id": pid}, headers=h).json()][0]["status"] == "SENT"
    assert client.post("/api/notifications/send", json={"kind": "QUOTATION", "ref_id": b["id"], "channel": "WHATSAPP", "to": "call me", "body": "x"}, headers=h).status_code == 422
    assert [x["status"] for x in client.get("/api/messages", params={"ref_id": b["id"]}, headers=h).json()] == ["LINK"]


def test_email_goes_through_the_outbox_with_the_pdf_attached(client, mail):
    h = hdr(client); pid, b, cl = job(client, h)
    d = client.get("/api/notifications/draft", params={"kind": "QUOTATION", "ref_id": b["id"]}, headers=h).json()
    assert d["email_ready"] is True and d["email"] == "client@example.com" and d["attachment"] == "Quotation PDF"
    r = client.post("/api/notifications/send", json={"kind": "QUOTATION", "ref_id": b["id"], "channel": "EMAIL", "to": "client@example.com, accounts@example.com",
                                                     "subject": d["subject"], "body": d["body"]}, headers=h).json()
    assert r["status"] == "QUEUED" and r["attachment"] == "Quotation PDF"
    assert drain() >= 1
    sent = [s for s in mail.sent if b["quotation_no"] in s["Subject"]][-1]
    assert sent["To"] == "client@example.com, accounts@example.com" and "studio@test.com" in sent["From"]
    parts = [p for p in sent.walk() if p.get_content_type() == "application/pdf"]
    assert len(parts) == 1 and parts[0].get_payload(decode=True)[:4] == b"%PDF" and parts[0].get_filename().startswith("QT-")
    assert ("starttls",) in mail.calls and ("login", "studio@test.com") in mail.calls
    msgs = client.get("/api/messages", params={"ref_id": b["id"]}, headers=h).json(); assert msgs[0]["status"] == "SENT" and msgs[0]["sent_at"]
    assert any("Email sent to client@example.com" in e["text"] for e in client.get(f"/api/projects/{pid}/timeline", headers=h).json())


def test_failed_email_retries_then_fails_with_the_reason_and_can_be_retried(client, mail):
    h = hdr(client); pid, b, _ = job(client, h)
    mail.fail_with = ConnectionRefusedError("mail server down")
    m_ = client.post("/api/notifications/send", json={"kind": "QUOTATION", "ref_id": b["id"], "channel": "EMAIL", "to": "x@example.com", "subject": "Q", "body": "B", "attach": False}, headers=h).json()
    for _ in range(3): drain()
    row = next(x for x in client.get("/api/messages", params={"ref_id": b["id"]}, headers=h).json() if x["id"] == m_["id"])
    assert row["status"] == "FAILED" and row["attempts"] == 3 and "mail server down" in row["error"]
    mail.fail_with = None
    assert client.post(f"/api/messages/{m_['id']}/retry", headers=h).json()["status"] == "QUEUED"
    drain()
    assert next(x for x in client.get("/api/messages", params={"ref_id": b["id"]}, headers=h).json() if x["id"] == m_["id"])["status"] == "SENT"
    assert client.post(f"/api/messages/{m_['id']}/retry", headers=h).status_code == 409


def test_recipient_validation(client, mail):
    h = hdr(client); _, b, _ = job(client, h)
    base = {"kind": "QUOTATION", "ref_id": b["id"], "channel": "EMAIL", "subject": "Q", "body": "B"}
    assert client.post("/api/notifications/send", json={**base, "to": "not-an-email"}, headers=h).status_code == 422
    assert client.post("/api/notifications/send", json={**base, "to": ",".join(f"a{i}@x.com" for i in range(6))}, headers=h).status_code == 422
    assert client.post("/api/notifications/send", json={**base, "to": "a@x.com", "subject": "  "}, headers=h).status_code == 422
    assert client.post("/api/notifications/send", json={**base, "to": "a@x.com", "channel": "PIGEON"}, headers=h).status_code == 422
    assert client.post("/api/notifications/send", json={**base, "to": "a@x.com", "kind": "QUOTATION", "ref_id": "nope"}, headers=h).status_code == 404


def test_templates_are_editable_checked_and_resettable(client):
    h = hdr(client); _, b, _ = job(client, h)
    assert client.put("/api/notifications/templates/QUOTATION", json={"subject": "Hi $nobody", "body": "x"}, headers=h).status_code == 422
    assert client.put("/api/notifications/templates/QUOTATION", json={"subject": "Hi", "body": "x"}, headers=hdr(client, "sales15@test.com")).status_code == 403
    client.put("/api/notifications/templates/QUOTATION", json={"subject": "Your quote $quotation_no", "body": "Namaste $client, total Rs. $amount."}, headers=h)
    d = client.get("/api/notifications/draft", params={"kind": "QUOTATION", "ref_id": b["id"]}, headers=h).json()
    assert d["subject"] == f"Your quote {b['quotation_no']}" and d["body"].startswith("Namaste Notify client")
    client.delete("/api/notifications/templates/QUOTATION", headers=h)
    assert client.get("/api/notifications/templates", headers=h).json()["QUOTATION"]["customised"] is False
    assert client.delete("/api/notifications/templates/NOPE", headers=h).status_code == 404


def test_automatic_emails_are_off_by_default_and_explain_why_when_skipped(client, mail):
    h = hdr(client); pid, b, _ = job(client, h, approve=True)
    pay = lambda: client.post(f"/api/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "1000", "received_on": "2026-11-01", "mode": "UPI", "reference": "UTR1"}, headers=h)
    pay(); assert client.get("/api/messages", params={"project_id": pid}, headers=h).json() == []        # off → nothing
    assert client.put("/api/notifications/auto", json={"PAYMENT": "yes"}, headers=h).status_code == 422
    assert client.put("/api/notifications/auto", json={"PAYMENT": True, "INVOICE": True}, headers=h).json()["PAYMENT"] is True
    try:
        pay(); drain()
        msg = client.get("/api/messages", params={"project_id": pid}, headers=h).json()[0]
        assert msg["trigger"] == "AUTO" and msg["status"] == "SENT" and "Rs. 1,000.00" in msg["body"] and "(ref. UTR1)" in msg["body"]
        assert any("Payment received" in s["Subject"] for s in mail.sent)
        inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "500"}, headers=h).json(); drain()
        assert any(inv["invoice_no"] in s["Subject"] and any(p.get_content_type() == "application/pdf" for p in s.walk()) for s in mail.sent)
        pid2, b2, _ = job(client, h, email_addr=None, approve=True)                                        # client without email
        client.post(f"/api/projects/{pid2}/payments", json={"boq_id": b2["id"], "amount": "10", "received_on": "2026-11-01", "mode": "CASH"}, headers=h)
        sk = client.get("/api/messages", params={"project_id": pid2}, headers=h).json()[0]
        assert sk["status"] == "SKIPPED" and "no email" in sk["error"]
    finally:
        client.put("/api/notifications/auto", json={"PAYMENT": False, "INVOICE": False}, headers=h)


def test_auto_email_skipped_when_email_is_not_set_up(client):
    h = hdr(client); pid, b, _ = job(client, h, approve=True)
    client.put("/api/notifications/auto", json={"PAYMENT": True}, headers=h)
    try:
        client.post(f"/api/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "10", "received_on": "2026-11-01", "mode": "CASH"}, headers=h)
        sk = client.get("/api/messages", params={"project_id": pid}, headers=h).json()[0]
        assert sk["status"] == "SKIPPED" and "not set up" in sk["error"]
    finally:
        client.put("/api/notifications/auto", json={"PAYMENT": False}, headers=h)


def test_purchase_orders_go_to_the_supplier_and_roles_are_enforced(client, mail):
    h = hdr(client); n = u()
    sup = client.post("/api/suppliers", json={"name": f"Notify supplier {n}", "phone": f"9{n + 50000000:09d}", "email": "orders@supplier.test", "contact_person": "Mahesh"}, headers=h).json()
    it = client.post("/api/catalogue/items", json={"sku": f"NT-CHR-{n}", "name": "Chair", "category": "Chair", "price": "1000", "length_mm": 500, "width_mm": 500, "height_mm": 800, "supplier_id": sup["id"]}, headers=h).json()
    pid, b, _ = job(client, h)
    rid = client.get(f"/api/projects/{pid}/rooms", headers=h).json()[0]["id"]
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="c", name="Chair", category="Chair", sku=it["sku"], price=1000, x=500, y=500, length=500, width=500, height=800)]}, headers=h).json()["version"]
    b2 = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json(); client.post(f"/api/boqs/{b2['id']}/status", json={"status": "APPROVED"}, headers=h)
    po = client.post(f"/api/boqs/{b2['id']}/procure", json={}, headers=h).json()["created"][0]
    d = client.get("/api/notifications/draft", params={"kind": "PO", "ref_id": po["id"]}, headers=hdr(client, "proc15@test.com")).json()
    assert d["email"] == "orders@supplier.test" and d["body"].startswith("Dear Mahesh") and po["po_number"] in d["subject"]
    assert client.get("/api/notifications/draft", params={"kind": "PO", "ref_id": po["id"]}, headers=hdr(client, "sales15@test.com")).status_code == 403
    assert client.get("/api/notifications/draft", params={"kind": "QUOTATION", "ref_id": b["id"]}, headers=hdr(client, "des15@test.com")).status_code == 403
    client.post("/api/notifications/send", json={"kind": "PO", "ref_id": po["id"], "channel": "EMAIL", "to": d["email"], "subject": d["subject"], "body": d["body"]}, headers=hdr(client, "proc15@test.com"))
    drain()
    assert any(po["po_number"] in s["Subject"] and s["To"] == "orders@supplier.test" for s in mail.sent)


def test_test_email_reports_the_server_answer(client, mail, monkeypatch):
    h = hdr(client)
    assert client.post("/api/notifications/test", json={"to": "me@example.com"}, headers=h).json()["ok"] is True
    assert any("Test email" in s["Subject"] for s in mail.sent)
    mail.fail_with = OSError("535 Authentication failed")
    r = client.post("/api/notifications/test", json={"to": "me@example.com"}, headers=h)
    assert r.status_code == 502 and "Authentication failed" in r.json()["detail"]
    mail.fail_with = None
    monkeypatch.setattr(settings, "SMTP_SECURITY", "ssl"); FakeSMTP.calls.clear()
    client.post("/api/notifications/test", json={"to": "me@example.com"}, headers=h)
    assert ("connect", "smtp.test", 587, "FakeSMTPSSL") in FakeSMTP.calls and ("starttls",) not in FakeSMTP.calls
    assert client.post("/api/notifications/test", json={"to": "me@example.com"}, headers=hdr(client, "sales15@test.com")).status_code == 403
    s = client.get("/api/notifications/status", headers=h).json(); assert s["email_ready"] is True and "SMTP_PASSWORD" not in str(s.get("from"))
