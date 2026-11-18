"""GST is optional: a company default + a per-quotation switch. Invoices follow their quotation:
GST on → TAX invoice (taxable + CGST/SGST or IGST), GST off → PLAIN invoice with no GST anywhere."""
import re
from datetime import date, timedelta
from decimal import Decimal as D

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import invoicing
from app.services.catalogue import gstin_check_char

COMPANY_GSTIN = "27AAPFU0939F1ZV"       # Maharashtra (27)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="des14@test.com").first():
            db.add(m.User(email="des14@test.com", full_name="Designer", role="INTERIOR_DESIGNER", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        h = hdr(c); c.put("/api/settings/company", json={"gstin": COMPANY_GSTIN, "gst_enabled": True, "invoice_prefix": "INV"}, headers=h)
        yield c
        c.put("/api/settings/company", json={"gstin": "", "gst_enabled": True}, headers=h)


def hdr(c, email="admin@interioriq.com", pw="ChangeMe123!"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": pw}).json()["access_token"]}


def pdf_text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def gstin(state: str) -> str:
    body = f"{state}AAACB{u():04d}C1Z"; return body + gstin_check_char(body)


def job(c, h, client_gstin=None, approve=True, **params):
    n = u()
    cl = c.post("/api/clients", json={"name": f"Inv client {n}", "phone": f"9{n + 200000000:09d}", **({"gstin": client_gstin} if client_gstin else {})}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": f"IQ-INV-{n}", "name": "Invoice flat", "client_id": cl["id"], "site_address": "Andheri, Mumbai"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json=params, headers=h).json()
    if approve: c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    return pid, b, rid, v


# ── the GST switch ────────────────────────────────────────────────────────────
def test_gst_off_quotation_has_no_gst_anywhere(client):
    h = hdr(client); pid, b, _, _ = job(client, h, approve=False, gst_enabled=False, gst_pct="18")
    assert b["gst_enabled"] is False and b["params"]["gst_pct"] == "0" and b["totals"]["gst"] == "0.00"
    assert b["totals"]["grand_total"] == b["totals"]["after_discount"]
    txt = pdf_text(client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content)
    assert "GST is not charged" in txt and "GST (" not in txt and "incl. GST" not in txt


def test_gst_on_quotation_prints_gst(client):
    h = hdr(client); pid, b, _, _ = job(client, h, approve=False, gst_enabled=True)
    assert b["gst_enabled"] is True and b["totals"]["gst"] != "0.00"
    txt = pdf_text(client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content)
    assert "GST (18%)" in txt and "Grand total (incl. GST)" in txt


def test_company_default_decides_when_the_quotation_doesnt_say(client):
    h = hdr(client)
    client.put("/api/settings/company", json={"gst_enabled": "off", "default_gst_pct": "12"}, headers=h)
    d = client.get("/api/estimation/defaults", headers=h).json(); assert d["gst_enabled"] is False and d["gst_pct"] == "12"
    _, b, _, _ = job(client, h, approve=False); assert b["gst_enabled"] is False and b["totals"]["gst"] == "0.00"
    client.put("/api/settings/company", json={"gst_enabled": True, "default_gst_pct": 18}, headers=h)
    _, b2, _, _ = job(client, h, approve=False); assert b2["gst_enabled"] is True
    assert client.put("/api/settings/company", json={"gst_enabled": "maybe"}, headers=h).status_code == 422
    assert client.put("/api/settings/company", json={"default_gst_pct": "40"}, headers=h).status_code == 422
    assert client.put("/api/settings/company", json={"invoice_prefix": "IN V!"}, headers=h).status_code == 422


def test_what_if_preview_respects_the_switch(client):
    h = hdr(client); _, b, _, _ = job(client, h, approve=False)
    pv = client.post(f"/api/boqs/{b['id']}/preview", json={"gst_enabled": False}, headers=h).json()
    assert pv["totals"]["gst"] == "0.00" and D(pv["delta"]["gst"]) < 0


def test_old_boqs_without_the_switch_count_by_rate():
    from app.services.boq import gst_on
    assert gst_on({"gst_pct": "18"}) and not gst_on({"gst_pct": "0"}) and not gst_on({"gst_pct": "18", "gst_enabled": "false"})


# ── invoices ──────────────────────────────────────────────────────────────────
def test_tax_invoice_same_state_splits_cgst_sgst_and_numbers_by_financial_year(client):
    h = hdr(client); pid, b, _, _ = job(client, h)
    s = client.get(f"/api/projects/{pid}/invoices", headers=h).json()
    ms = s["quotations"][0]["milestones"]; assert s["quotations"][0]["gst_enabled"] is True
    inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Agreement signing"}, headers=h)
    assert inv.status_code == 201, inv.text; inv = inv.json()
    fy = invoicing.financial_year(date.today())
    assert re.fullmatch(rf"INV/{fy}/\d{{4}}", inv["invoice_no"]) and inv["kind"] == "TAX" and inv["amount"] == ms[0]["amount"]
    assert inv["place_of_supply"] == "27" and D(inv["igst"]) == 0 and D(inv["cgst"]) > 0
    assert D(inv["taxable"]) + D(inv["cgst"]) + D(inv["sgst"]) == D(inv["amount"])               # exact to the paisa
    assert abs(D(inv["cgst"]) - D(inv["sgst"])) <= D("0.01")
    again = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Agreement signing"}, headers=h)
    assert again.status_code == 409 and "already fully invoiced" in again.json()["detail"]
    nxt = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Design approval"}, headers=h).json()
    assert int(nxt["invoice_no"].rsplit("/", 1)[1]) == int(inv["invoice_no"].rsplit("/", 1)[1]) + 1
    txt = pdf_text(client.get(f"/api/invoices/{inv['id']}/pdf", headers=h).content)
    assert "TAX INVOICE" in txt and COMPANY_GSTIN in txt and "CGST 9%" in txt and "SGST 9%" in txt and "27 - Maharashtra" in txt and "Rupees" in txt and "9954" in txt


def test_tax_invoice_to_another_state_is_igst(client):
    h = hdr(client); pid, b, _, _ = job(client, h, client_gstin=gstin("24"))
    inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "10000.00", "description": "Advance"}, headers=h).json()
    assert inv["place_of_supply"] == "24" and D(inv["cgst"]) == 0 and D(inv["igst"]) == D("10000.00") - D(inv["taxable"]) and inv["taxable"] == "8474.58"
    txt = pdf_text(client.get(f"/api/invoices/{inv['id']}/pdf", headers=h).content)
    assert "IGST 18%" in txt and "GSTIN" in txt
    o = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "100", "place_of_supply": "27"}, headers=h).json()
    assert D(o["cgst"]) > 0 and D(o["igst"]) == 0                                                    # place of supply can be overridden
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "100", "place_of_supply": "99"}, headers=h).status_code == 422


def test_plain_invoice_when_gst_is_off(client):
    h = hdr(client); pid, b, _, _ = job(client, h, gst_enabled=False)
    client.put("/api/settings/company", json={"gstin": ""}, headers=h)                     # an unregistered firm can still bill
    try:
        inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Agreement signing"}, headers=h).json()
        assert inv["kind"] == "PLAIN" and inv["taxable"] == inv["amount"] and inv["cgst"] == inv["sgst"] == inv["igst"] == "0.00" and inv["place_of_supply"] is None
        txt = pdf_text(client.get(f"/api/invoices/{inv['id']}/pdf", headers=h).content)
        assert "INVOICE" in txt and "TAX INVOICE" not in txt and "GST is not charged" in txt and "CGST" not in txt and "GSTIN" not in txt
    finally:
        client.put("/api/settings/company", json={"gstin": COMPANY_GSTIN}, headers=h)


def test_gst_quotation_needs_company_gstin_for_a_tax_invoice(client):
    h = hdr(client); pid, b, _, _ = job(client, h)
    client.put("/api/settings/company", json={"gstin": ""}, headers=h)
    try:
        r = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Agreement signing"}, headers=h)
        assert r.status_code == 409 and "set your GSTIN" in r.json()["detail"]
    finally:
        client.put("/api/settings/company", json={"gstin": COMPANY_GSTIN}, headers=h)


def test_limits_cancel_and_issued_snapshot(client):
    h = hdr(client); pid, b, _, _ = job(client, h)
    total = D(b["totals"]["grand_total"])
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"]}, headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Bribe"}, headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "0"}, headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "10.001"}, headers=h).status_code == 422
    r = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": str(total + 1)}, headers=h)
    assert r.status_code == 409 and "left to invoice" in r.json()["detail"]
    fut = (date.today() + timedelta(days=2)).isoformat()
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "100", "issue_date": fut}, headers=h).status_code == 422
    full = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": str(total), "description": "Full value"}, headers=h).json()
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "1"}, headers=h).status_code == 409
    client.put("/api/settings/company", json={"name": "Renamed Studio"}, headers=h)
    assert "Renamed Studio" not in pdf_text(client.get(f"/api/invoices/{full['id']}/pdf", headers=h).content)    # issued = frozen
    client.put("/api/settings/company", json={"name": "InteriorIQ Design Studio"}, headers=h)
    assert client.post(f"/api/invoices/{full['id']}/cancel", json={"reason": "x"}, headers=h).status_code == 422
    cx = client.post(f"/api/invoices/{full['id']}/cancel", json={"reason": "Wrong amount"}, headers=h).json()
    assert cx["status"] == "CANCELLED" and client.post(f"/api/invoices/{full['id']}/cancel", json={"reason": "again"}, headers=h).status_code == 409
    assert "CANCELLED" in pdf_text(client.get(f"/api/invoices/{full['id']}/pdf", headers=h).content)
    re_ = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "5000"}, headers=h).json()
    assert re_["invoice_no"] != full["invoice_no"]                                                   # numbers are never reused
    tl = [e["text"] for e in client.get(f"/api/projects/{pid}/timeline", headers=h).json()]
    assert any("cancelled: Wrong amount" in t for t in tl) and any("Tax invoice" in t for t in tl)


def test_only_approved_quotations_and_roles(client):
    h = hdr(client); pid, b, _, _ = job(client, h, approve=False)
    r = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "100"}, headers=h)
    assert r.status_code == 409 and "APPROVED" in r.json()["detail"]
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    assert client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "100"}, headers=hdr(client, "des14@test.com")).status_code == 403
    assert client.get("/api/invoices", headers=hdr(client, "des14@test.com")).status_code == 200


def test_client_portal_sees_own_invoices(client):
    h = hdr(client); pid, b, _, _ = job(client, h); n = u()
    cl_id = client.get(f"/api/projects/{pid}/overview", headers=h).json()
    proj = [p for p in client.get("/api/projects", headers=h).json() if p["id"] == pid][0]
    inv = client.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "milestone": "Agreement signing"}, headers=h).json()
    client.post("/api/users", json={"email": f"invportal{n}@test.com", "full_name": "P", "role": "CLIENT", "password": "Client123", "client_id": proj["client_id"]}, headers=h)
    ch = hdr(client, f"invportal{n}@test.com", "Client123")
    o = client.get(f"/api/portal/projects/{pid}", headers=ch).json()
    assert [i["invoice_no"] for i in o["invoices"]] == [inv["invoice_no"]] and any("Tax invoice" in e["text"] for e in o["timeline"])
    assert client.get(f"/api/portal/invoices/{inv['id']}/pdf", headers=ch).status_code == 200
    other_pid, other_b, _, _ = job(client, h)
    other = client.post(f"/api/projects/{other_pid}/invoices", json={"boq_id": other_b["id"], "amount": "100"}, headers=h).json()
    assert client.get(f"/api/portal/invoices/{other['id']}/pdf", headers=ch).status_code == 404
    assert client.get(f"/api/invoices/{inv['id']}/pdf", headers=ch).status_code == 403


def test_words_and_split_helpers():
    assert invoicing.words("125430.50") == "Rupees One Lakh Twenty Five Thousand Four Hundred Thirty and Fifty Paise Only"
    assert invoicing.words("1000000000") == "Rupees One Hundred Crore Only"
    p = invoicing.split("69430.08", 18, True); assert p["taxable"] + p["cgst"] + p["sgst"] == D("69430.08")
    assert invoicing.financial_year(date(2027, 3, 31)) == "2026-27" and invoicing.financial_year(date(2027, 4, 1)) == "2027-28"


def test_two_rooms_never_share_a_quotation_number(client):
    h = hdr(client); pid, b1, rid1, v1 = job(client, h, approve=False)
    rid2 = client.post(f"/api/projects/{pid}/rooms", json={"name": "Kids room", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): client.put(f"/api/rooms/{rid2}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]
    v2 = client.post(f"/api/rooms/{rid2}/designs", json={"objects": objs}, headers=h).json()["version"]
    b2 = client.post(f"/api/rooms/{rid2}/designs/{v2}/boq", json={}, headers=h).json()
    b3 = client.post(f"/api/rooms/{rid1}/designs/{v1}/boq", json={}, headers=h).json()
    nos = [b1["quotation_no"], b2["quotation_no"], b3["quotation_no"]]
    assert len(set(nos)) == 3 and [n[-2:] for n in nos] == ["01", "02", "03"]
    assert {q["quotation_no"] for q in client.get("/api/quotations", params={"project_id": pid}, headers=h).json()} == set(nos)


def test_backfill_numbers_old_boqs_in_creation_order(client):
    from app.services.flow import backfill_quote_seq
    h = hdr(client); pid, b1, rid1, v1 = job(client, h, approve=False)
    b2 = client.post(f"/api/rooms/{rid1}/designs/{v1}/boq", json={}, headers=h).json()
    db = SessionLocal()
    for x in db.query(m.Boq).filter(m.Boq.id.in_([b1["id"], b2["id"]])): x.quote_seq = None     # as saved before the column existed
    db.commit(); backfill_quote_seq(db); db.commit()
    seqs = {x.id: x.quote_seq for x in db.query(m.Boq).filter(m.Boq.id.in_([b1["id"], b2["id"]]))}; db.close()
    assert seqs == {b1["id"]: 1, b2["id"]: 2}
