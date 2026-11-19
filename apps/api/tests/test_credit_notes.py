"""M33 credit notes: against an ISSUED invoice only, never more than is left to credit, GST split like the invoice (CGST/SGST or IGST,
parts sum exactly; none on a plain invoice), own number series per financial year, net invoiced drops so the amount can be invoiced
again, receivable = invoiced − credited − paid, cancel with reason (number kept), an invoice with credit notes can't be cancelled, PDF,
client portal sees issued ones, roles."""
from datetime import date, timedelta
from decimal import Decimal as D

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m

GSTIN = "27AAPFU0939F1ZV"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="des33@test.com").first():
            db.add(m.User(email="des33@test.com", full_name="Designer", role="INTERIOR_DESIGNER", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        h = hdr(c); c.put("/api/settings/company", json={"gstin": GSTIN, "gst_enabled": True, "invoice_prefix": "INV"}, headers=h)
        yield c
        c.put("/api/settings/company", json={"gstin": "", "gst_enabled": True}, headers=h)


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


_n = [0]
def job(c, h, gst=True):
    _n[0] += 1; n = _n[0]
    cl = c.post("/api/clients", json={"name": f"CN client {n}", "phone": f"9{n + 330000000:09d}"}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": f"IQ-CN-{n}", "name": "Credit flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": gst}, headers=h).json()
    c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    return pid, b


def test_credit_a_tax_invoice_and_reinvoice(client):
    h = hdr(client); pid, b = job(client, h)
    inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "118000.00", "description": "Advance"}, headers=h).json()
    r = client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "11800.00", "reason": "Laminate changed to a cheaper finish"}, headers=h)
    assert r.status_code == 201, r.text
    cn = r.json(); assert cn["note_no"].startswith("INV/CN/") and cn["invoice_no"] == inv["invoice_no"]
    assert D(cn["taxable"]) + D(cn["cgst"]) + D(cn["sgst"]) + D(cn["igst"]) == D("11800.00") and D(cn["cgst"]) == D(cn["sgst"]) > 0   # same state as the company
    s = client.get(f"/api/projects/{pid}/invoices", headers=h).json()
    i = next(x for x in s["invoices"] if x["id"] == inv["id"])
    assert i["credited"] == "11800.00" and i["net"] == "106200.00" and s["totals"]["credited"] == "11800.00"
    assert s["totals"]["receivable"] == "106200.00"
    q = next(x for x in s["quotations"] if x["boq_id"] == b["id"])
    assert D(q["invoiced"]) == D("106200.00")                                  # net: the credited part can be invoiced again
    # more than is left → refused; dated before the invoice / in the future → refused
    assert client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "106200.01", "reason": "Too much credit"}, headers=h).status_code == 409
    assert client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "1.00", "reason": "Future dated", "issue_date": (date.today() + timedelta(days=2)).isoformat()}, headers=h).status_code == 422
    assert client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "1.00", "reason": "x"}, headers=h).status_code == 422          # reason too short
    assert client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "1.00", "reason": "Not allowed"}, headers=hdr(client, "des33@test.com")).status_code == 403
    pdf = text(client.get(f"/api/credit-notes/{cn['id']}/pdf", headers=h).content)
    assert "CREDIT NOTE" in pdf and inv["invoice_no"] in pdf and "Laminate changed" in pdf and "CGST" in pdf
    # the invoice can't be cancelled while it has a credit note; cancel the note first
    assert client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Wrong client"}, headers=h).status_code == 409
    c2 = client.post(f"/api/credit-notes/{cn['id']}/cancel", json={"reason": "Issued by mistake"}, headers=h).json()
    assert c2["status"] == "CANCELLED" and client.get(f"/api/projects/{pid}/invoices", headers=h).json()["totals"]["credited"] == "0.00"
    assert client.post(f"/api/credit-notes/{cn['id']}/cancel", json={"reason": "Again please"}, headers=h).status_code == 409
    nxt = client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "500.00", "reason": "Small goodwill discount"}, headers=h).json()
    assert int(nxt["note_no"].rsplit("/", 1)[1]) == int(cn["note_no"].rsplit("/", 1)[1]) + 1                   # numbers never reused


def test_plain_invoice_credit_has_no_gst_and_client_sees_it(client):
    h = hdr(client); pid, b = job(client, h, gst=False)
    inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "50000.00"}, headers=h).json()
    cn = client.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "2500.00", "reason": "Handle set returned"}, headers=h).json()
    assert cn["taxable"] == "2500.00" and cn["cgst"] == cn["sgst"] == cn["igst"] == "0.00"
    assert "GST" not in text(client.get(f"/api/credit-notes/{cn['id']}/pdf", headers=h).content).replace("GSTIN", "")
    # cancelled invoice: no credit notes
    inv2 = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "1000.00"}, headers=h).json()
    client.post(f"/api/invoices/{inv2['id']}/cancel", json={"reason": "Raised twice"}, headers=h)
    assert client.post(f"/api/invoices/{inv2['id']}/credit-notes", json={"amount": "10.00", "reason": "Should fail"}, headers=h).status_code == 409
    # client portal lists the issued credit note and gets its PDF
    p = client.get(f"/api/projects/{pid}", headers=h).json()
    db = SessionLocal()
    try:
        cid = db.get(m.Project, pid).client_id
        if not db.query(m.User).filter_by(email="cli33@test.com").first():
            db.add(m.User(email="cli33@test.com", full_name="Client", role="CLIENT", client_id=cid, password_hash=hash_password("ChangeMe123!"))); db.commit()
    finally: db.close()
    hc = hdr(client, "cli33@test.com")
    port = client.get(f"/api/portal/projects/{pid}", headers=hc)
    assert port.status_code == 200 and any(n["note_no"] == cn["note_no"] for n in port.json().get("credit_notes", []))
    assert client.get(f"/api/portal/credit-notes/{cn['id']}/pdf", headers=hc).status_code == 200
