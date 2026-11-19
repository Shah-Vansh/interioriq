"""M34 accounting export: Tally XML vouchers (Sales, Credit Note, Receipt, Purchase, Payment) that each balance to zero with Tally's sign
convention, party + configured ledgers as masters, configurable ledger names (validated), date range in company local days, day-book CSV
whose debits equal credits, kinds filter, roles."""
import csv
import io
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="sales34@test.com").first():
            db.add(m.User(email="sales34@test.com", full_name="Sales", role="SALES", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        h = hdr(c); c.put("/api/settings/company", json={"gstin": "27AAPFU0939F1ZV", "gst_enabled": True, "invoice_prefix": "TLY"}, headers=h)
        yield c
        c.put("/api/settings/company", json={"gstin": "", "gst_enabled": True, "invoice_prefix": "INV"}, headers=h)
        c.put("/api/settings/tally", json={k: v for k, v in __import__("app.services.tally", fromlist=["DEFAULTS"]).DEFAULTS.items()}, headers=h)


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def setup(c, h):
    cl = c.post("/api/clients", json={"name": "Tally Trivedi", "phone": "9341000001"}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": "IQ-TLY-1", "name": "Tally flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": True}, headers=h).json()
    c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    inv = c.post(f"/api/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "118000.00", "description": "Advance"}, headers=h).json()
    c.post(f"/api/invoices/{inv['id']}/credit-notes", json={"amount": "5900.00", "reason": "Handles changed"}, headers=h)
    c.post(f"/api/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "50000.00", "received_on": date.today().isoformat(), "mode": "UPI", "reference": "UTR123"}, headers=h).raise_for_status()
    s = c.post("/api/suppliers", json={"name": "Shree Plywood", "phone": "9341000002"}, headers=h).json()
    c.post("/api/bills", json={"supplier_id": s["id"], "bill_no": "SP/77", "bill_date": date.today().isoformat(), "taxable": "10000.00", "gst": "1800.00"}, headers=h).raise_for_status()
    c.post("/api/supplier-payments", json={"supplier_id": s["id"], "amount": "5000.00", "paid_on": date.today().isoformat(), "mode": "CASH"}, headers=h).raise_for_status()
    return inv


def test_tally_xml_vouchers_balance_and_masters(client):
    h = hdr(client); inv = setup(client, h); t = date.today()
    r = client.get("/api/exports/tally.xml", params={"date_from": (t - timedelta(days=1)).isoformat(), "date_to": t.isoformat()}, headers=h)
    assert r.status_code == 200 and int(r.headers["x-voucher-count"]) >= 5
    root = ET.fromstring(r.content)
    vs = root.findall(".//VOUCHER"); types = {v.get("VCHTYPE") for v in vs}
    assert {"Sales", "Credit Note", "Receipt", "Purchase", "Payment"} <= types
    for v in vs:
        amounts = [D(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")]
        assert sum(amounts) == 0, (v.findtext("VOUCHERNUMBER"), amounts)
        for e in v.findall("ALLLEDGERENTRIES.LIST"):                                       # Tally: debit = Yes + negative
            assert (e.findtext("ISDEEMEDPOSITIVE") == "Yes") == (D(e.findtext("AMOUNT")) < 0)
    sale = next(v for v in vs if v.findtext("VOUCHERNUMBER") == inv["invoice_no"])
    led = {e.findtext("LEDGERNAME"): D(e.findtext("AMOUNT")) for e in sale.findall("ALLLEDGERENTRIES.LIST")}
    assert led["Tally Trivedi"] == D("-118000.00") and led["Output CGST"] > 0 and led["Output SGST"] == led["Output CGST"] and led["Sales - Interior Works"] > 0
    pay = next(v for v in vs if v.get("VCHTYPE") == "Payment" and v.findtext("PARTYLEDGERNAME") == "Shree Plywood")
    assert "Cash" in [e.findtext("LEDGERNAME") for e in pay.findall("ALLLEDGERENTRIES.LIST")]
    masters = {l.get("NAME"): l.findtext("PARENT") for l in root.findall(".//LEDGER")}
    assert masters["Tally Trivedi"] == "Sundry Debtors" and masters["Shree Plywood"] == "Sundry Creditors" and masters["Output IGST"] == "Duties & Taxes"
    # outside the range → nothing
    old = client.get("/api/exports/tally.xml", params={"date_from": "2020-04-01", "date_to": "2020-04-30"}, headers=h)
    assert old.headers["x-voucher-count"] == "0"


def test_settings_kinds_daybook_and_roles(client):
    h = hdr(client); t = date.today()
    s = client.put("/api/settings/tally", json={"sales": "Interior Sales", "bank": "HDFC Current A/c", "company": "Mehta Interiors 2026"}, headers=h).json()
    assert s["values"]["sales"] == "Interior Sales"
    for bad in ({"sales": ""}, {"bank": "A <b>"}, {"nope": "x"}):
        assert client.put("/api/settings/tally", json=bad, headers=h).status_code == 422
    r = client.get("/api/exports/tally.xml", params={"date_from": t.isoformat(), "date_to": t.isoformat(), "kinds": "receipt"}, headers=h)
    root = ET.fromstring(r.content)
    assert {v.get("VCHTYPE") for v in root.findall(".//VOUCHER")} == {"Receipt"} and root.findtext(".//SVCURRENTCOMPANY") == "Mehta Interiors 2026"
    assert "HDFC Current A/c" in r.text
    csvr = client.get("/api/exports/daybook.csv", params={"date_from": t.isoformat(), "date_to": t.isoformat()}, headers=h)
    rows = list(csv.DictReader(io.StringIO(csvr.content.decode("utf-8-sig"))))
    assert rows and sum(D(r["debit"] or 0) for r in rows) == sum(D(r["credit"] or 0) for r in rows)
    sm = client.get("/api/exports/summary", params={"date_from": t.isoformat(), "date_to": t.isoformat()}, headers=h).json()
    assert sm["vouchers"] >= 5 and sm["by_type"].get("Sales", 0) >= 1
    assert client.get("/api/exports/tally.xml", params={"date_from": t.isoformat(), "date_to": t.isoformat(), "kinds": "bogus"}, headers=h).status_code == 422
    assert client.get("/api/exports/tally.xml", params={"date_from": t.isoformat(), "date_to": (t - timedelta(days=1)).isoformat()}, headers=h).status_code == 422
    assert client.get("/api/exports/tally.xml", params={"date_from": t.isoformat(), "date_to": t.isoformat()}, headers=hdr(client, "sales34@test.com")).status_code == 403
