"""M17 payables: supplier bills (3-way match with goods received), payment terms, payments allocated oldest-first or by hand, voids,
ageing, supplier statement, the project's real cash position, the overdue-bill alert and roles."""
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
        for e, r in (("des17@test.com", "INTERIOR_DESIGNER"), ("proc17@test.com", "PROCUREMENT_MANAGER")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=r.title(), role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]
TODAY = date.today()
iso = lambda d: d.isoformat()


def supplier(c, h, terms=15):
    n = u(); return c.post("/api/suppliers", json={"name": f"Bill supplier {n}", "phone": f"9{n + 20000000:09d}", "payment_terms_days": terms}, headers=h).json()


def job(c, h, sup):
    """Approved quotation with 3 chairs (cost 1000) → PO for 3 from this supplier (no stock)."""
    n = u()
    it = c.post("/api/catalogue/items", json={"sku": f"PB-{n}", "name": f"Bill chair {n}", "category": "Chair", "price": "1500", "cost_price": "1000",
                                              "length_mm": 500, "width_mm": 500, "height_mm": 800, "supplier_id": sup["id"]}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": f"IQ-PB-{n}", "name": "Payables flat"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id=f"c{i}", name=it["name"], category="Chair", sku=it["sku"], price=1500, x=300 + i * 700, y=300, length=500, width=500, height=800) for i in range(3)]
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    created = c.post(f"/api/boqs/{b['id']}/procure", json={}, headers=h).json()["created"]
    po = c.get(f"/api/purchase-orders/{created[0]['id']}", headers=h).json()
    return pid, b, po


def bill(c, h, **kw):
    return c.post("/api/bills", json={"bill_no": f"B-{u()}", "bill_date": iso(TODAY), "taxable": "100"} | kw, headers=h)


def test_bills_match_goods_received_and_get_a_due_date_from_the_terms(client):
    h = hdr(client); sup = supplier(client, h, terms=15); pid, b, po = job(client, h, sup)
    assert bill(client, h, po_id=po["id"], taxable="3000").status_code == 409                       # draft PO
    client.post(f"/api/purchase-orders/{po['id']}/issue", headers=h)
    r = bill(client, h, po_id=po["id"], taxable="3000")
    assert r.status_code == 409 and "only Rs. 0.00 of goods were received" in r.json()["detail"]
    client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": [{"line_id": po["lines"][0]["id"], "qty": 2}]}, headers=h)
    chk = client.get("/api/bills/po-check", params={"po_id": po["id"], "taxable": "2000"}, headers=h).json()
    assert chk["received"] == "2000.00" and chk["status"] == "MATCHED" and chk["payment_terms_days"] == 15
    ok = bill(client, h, po_id=po["id"], bill_no="INV-77", taxable="2000", gst="360").json()
    assert ok["match"] == "MATCHED" and ok["total"] == "2360.00" and ok["supplier_id"] == sup["id"] and ok["project_id"] == pid
    assert ok["due_date"] == iso(TODAY + timedelta(days=15)) and ok["status"] == "OPEN" and ok["po_number"] == po["po_number"]
    assert bill(client, h, po_id=po["id"], bill_no="inv-77", taxable="1").status_code == 409            # duplicate, any case
    over = bill(client, h, po_id=po["id"], taxable="900")
    assert over.status_code == 409 and "approval reason" in over.json()["detail"]
    acc = bill(client, h, po_id=po["id"], taxable="900", approve_reason="Freight agreed by phone").json()
    assert acc["match"] == "OVER_BILLED" and acc["approve_reason"] == "Freight agreed by phone"
    assert any("Supplier bill INV-77" in e["text"] for e in client.get(f"/api/projects/{pid}/timeline", headers=h).json())


def test_bill_validation(client):
    h = hdr(client); sup = supplier(client, h); other = supplier(client, h); pid, b, po = job(client, h, sup)
    client.post(f"/api/purchase-orders/{po['id']}/issue", headers=h)
    assert bill(client, h, po_id=po["id"], supplier_id=other["id"]).status_code == 422
    assert bill(client, h).status_code == 422                                                            # no supplier, no PO
    assert bill(client, h, supplier_id=sup["id"], bill_date=iso(TODAY + timedelta(days=1))).status_code == 422
    assert bill(client, h, supplier_id=sup["id"], taxable="0", gst="0").status_code == 422
    assert bill(client, h, supplier_id=sup["id"], due_date=iso(TODAY - timedelta(days=1))).status_code == 422
    assert bill(client, h, supplier_id=sup["id"], taxable="10.555").status_code == 422
    assert bill(client, h, supplier_id=sup["id"]).json()["match"] == "NO_PO"
    assert client.post("/api/bills", json={"supplier_id": sup["id"], "bill_no": "X", "bill_date": iso(TODAY), "taxable": "1"}, headers=hdr(client, "des17@test.com")).status_code == 403
    assert client.post("/api/bills", json={"supplier_id": sup["id"], "bill_no": f"P{u()}", "bill_date": iso(TODAY), "taxable": "1"}, headers=hdr(client, "proc17@test.com")).status_code == 201


def test_payment_allocates_oldest_due_first_and_never_overpays(client):
    h = hdr(client); sup = supplier(client, h)
    b1 = bill(client, h, supplier_id=sup["id"], taxable="1000", bill_date=iso(TODAY - timedelta(days=20)), due_date=iso(TODAY - timedelta(days=5))).json()
    b2 = bill(client, h, supplier_id=sup["id"], taxable="2000", bill_date=iso(TODAY - timedelta(days=2))).json()
    base = {"supplier_id": sup["id"], "paid_on": iso(TODAY), "mode": "BANK"}
    r = client.post("/api/supplier-payments", json={**base, "amount": "3000.01"}, headers=h)
    assert r.status_code == 409 and "only Rs. 3,000.00" in r.json()["detail"]
    assert client.post("/api/supplier-payments", json={**base, "amount": "100"}, headers=hdr(client, "proc17@test.com")).status_code == 403
    p = client.post("/api/supplier-payments", json={**base, "amount": "1500", "reference": "NEFT1"}, headers=h).json()
    assert [(a["bill_no"], a["amount"]) for a in p["allocations"]] == [(b1["bill_no"], "1000.00"), (b2["bill_no"], "500.00")]
    st = {x["id"]: (x["status"], x["outstanding"]) for x in client.get("/api/bills", params={"supplier_id": sup["id"]}, headers=h).json()}
    assert st == {b1["id"]: ("PAID", "0.00"), b2["id"]: ("PARTIAL", "1500.00")}
    assert client.post("/api/supplier-payments", json={**base, "amount": "100", "allocations": [{"bill_id": b2["id"], "amount": "50"}]}, headers=h).status_code == 422
    assert client.post("/api/supplier-payments", json={**base, "amount": "100", "allocations": [{"bill_id": b1["id"], "amount": "100"}]}, headers=h).status_code == 409
    other = bill(client, h, supplier_id=supplier(client, h)["id"], taxable="100").json()
    assert client.post("/api/supplier-payments", json={**base, "amount": "100", "allocations": [{"bill_id": other["id"], "amount": "100"}]}, headers=h).status_code == 422
    p2 = client.post("/api/supplier-payments", json={**base, "amount": "1500", "allocations": [{"bill_id": b2["id"], "amount": "1500"}]}, headers=h).json()
    assert p2["allocations"][0]["amount"] == "1500.00"
    assert client.get(f"/api/bills/{b2['id']}", headers=h).json()["status"] == "PAID"
    assert client.post("/api/supplier-payments", json={**base, "amount": "1"}, headers=h).status_code == 409   # nothing owed now


def test_voids_reverse_cleanly(client):
    h = hdr(client); sup = supplier(client, h)
    b1 = bill(client, h, supplier_id=sup["id"], taxable="1000").json()
    p = client.post("/api/supplier-payments", json={"supplier_id": sup["id"], "amount": "400", "paid_on": iso(TODAY), "mode": "UPI"}, headers=h).json()
    assert client.post(f"/api/bills/{b1['id']}/void", json={"reason": "Wrong bill"}, headers=h).status_code == 409
    assert client.post(f"/api/supplier-payments/{p['id']}/void", json={"reason": "x"}, headers=h).status_code == 422
    assert client.post(f"/api/supplier-payments/{p['id']}/void", json={"reason": "Bounced cheque"}, headers=h).json()["status"] == "VOID"
    assert client.get(f"/api/bills/{b1['id']}", headers=h).json()["status"] == "OPEN"
    assert client.post(f"/api/supplier-payments/{p['id']}/void", json={"reason": "again"}, headers=h).status_code == 409
    assert client.post(f"/api/bills/{b1['id']}/void", json={"reason": "Wrong bill"}, headers=h).json()["status"] == "VOID"
    assert bill(client, h, supplier_id=sup["id"], bill_no=b1["bill_no"], taxable="900").status_code == 201    # a void bill's number can be re-entered
    stt = client.get(f"/api/suppliers/{sup['id']}/statement", headers=h).json()
    assert stt["balance"] == "900.00" and [e["void"] for e in stt["entries"]] == [True, True, False]


def test_ageing_buckets_due_soon_and_statement(client):
    h = hdr(client); sup = supplier(client, h, terms=30)
    old = bill(client, h, supplier_id=sup["id"], taxable="700", bill_date=iso(TODAY - timedelta(days=100))).json()      # due 70 days ago
    soon = bill(client, h, supplier_id=sup["id"], taxable="300", bill_date=iso(TODAY - timedelta(days=27))).json()      # due in 3 days
    s = client.get("/api/payables/summary", headers=h).json()
    row = next(r for r in s["suppliers"] if r["supplier_id"] == sup["id"])
    assert row["outstanding"] == "1000.00" and row["overdue"] == "700.00" and row["d61_90"] == "700.00" and row["not_due"] == "300.00"
    assert any(d["bill_id"] == soon["id"] and d["days"] == 3 for d in s["due_soon"])
    assert {b["key"] for b in s["buckets"]} == {"not_due", "d0_30", "d31_60", "d61_90", "d90_plus"}
    assert [x["id"] for x in client.get("/api/bills", params={"overdue": True, "supplier_id": sup["id"]}, headers=h).json()] == [old["id"]]
    client.post("/api/supplier-payments", json={"supplier_id": sup["id"], "amount": "200", "paid_on": iso(TODAY), "mode": "CASH"}, headers=h)
    st = client.get(f"/api/suppliers/{sup['id']}/statement", headers=h).json()
    assert [e["balance"] for e in st["entries"]] == ["700.00", "1000.00", "800.00"] and st["balance"] == "800.00"
    assert client.get(f"/api/suppliers/{sup['id']}/statement", headers=hdr(client, "des17@test.com")).status_code == 403
    al = client.get("/api/ai/alerts", headers=h).json()["alerts"]
    assert any(a["rule"] == "BILL_OVERDUE" and old["bill_no"] in a["text"] and a["severity"] == "HIGH" for a in al)
    assert not any(a["rule"] == "BILL_OVERDUE" for a in client.get("/api/ai/alerts", headers=hdr(client, "des17@test.com")).json()["alerts"])


def test_project_cash_position_uses_real_payments(client):
    h = hdr(client); sup = supplier(client, h); pid, b, po = job(client, h, sup)
    client.post(f"/api/purchase-orders/{po['id']}/issue", headers=h)
    client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": [{"line_id": po["lines"][0]["id"], "qty": 3}]}, headers=h)
    bl = bill(client, h, po_id=po["id"], taxable="3000").json()
    client.post(f"/api/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "4000", "received_on": iso(TODAY), "mode": "UPI"}, headers=h)
    client.post("/api/supplier-payments", json={"supplier_id": sup["id"], "amount": "1200", "paid_on": iso(TODAY), "mode": "BANK",
                                                "allocations": [{"bill_id": bl["id"], "amount": "1200"}]}, headers=h)
    client.post(f"/api/projects/{pid}/expenses", json={"category": "TRANSPORT", "amount": "300", "spent_on": iso(TODAY)}, headers=h)
    cash = client.get(f"/api/projects/{pid}/profit", headers=h).json()["cash"]
    assert cash["received"] == "4000.00" and cash["supplier_bills"] == "3000.00" and cash["paid_to_suppliers"] == "1200.00" and cash["expenses_paid"] == "300.00"
    assert cash["position"] == "2500.00"
