"""M34 per-supplier prices: quotes per item (price, min qty, validity, lead time), the cheapest VALID quote from an active supplier wins
(min qty respected, expired / future / ended / inactive ignored), procurement drafts the PO with that supplier at that rate and says so,
no quote → default supplier at cost (unchanged behaviour), roles (costs hidden from non-cost roles)."""
from datetime import date, timedelta

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
        if not db.query(m.User).filter_by(email="des34@test.com").first():
            db.add(m.User(email="des34@test.com", full_name="Designer", role="INTERIOR_DESIGNER", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def sup(c, h, name):
    _n[0] += 1; return c.post("/api/suppliers", json={"name": f"{name} {_n[0]}", "phone": f"9{_n[0] + 344000000:09d}"}, headers=h).json()


def test_best_quote_rules(client):
    h = hdr(client); t = date.today()
    a, b, x = sup(client, h, "Default Ply"), sup(client, h, "Cheap Ply"), sup(client, h, "Bulk Ply")
    it = client.post("/api/catalogue/items", json={"sku": f"PLY-SP-{_n[0]}", "name": "BWP ply 18mm", "kind": "MATERIAL", "category": "Plywood", "unit": "sheet",
                                                  "price": "3200", "cost_price": "2800", "supplier_id": a["id"]}, headers=h).json()
    best = lambda qty=1: client.get(f"/api/catalogue/items/{it['id']}/supplier-prices", params={"qty": qty}, headers=h).json()["best"]
    assert best()["source"] == "COST" and best()["supplier_id"] == a["id"] and best()["rate"] == "2800.00"
    P = lambda **kw: client.post(f"/api/catalogue/items/{it['id']}/supplier-prices", json=kw, headers=h)
    assert P(supplier_id=b["id"], price="2650.00", lead_days=5).status_code == 201
    P(supplier_id=x["id"], price="2400.00", min_qty=50)                                                     # only for 50+
    P(supplier_id=a["id"], price="2100.00", valid_from=(t - timedelta(days=60)).isoformat(), valid_to=(t - timedelta(days=1)).isoformat())   # expired
    P(supplier_id=a["id"], price="2000.00", valid_from=(t + timedelta(days=5)).isoformat())                 # not yet valid
    assert best()["supplier_id"] == b["id"] and best()["rate"] == "2650.00" and best()["source"] == "QUOTE"
    assert best(60)["supplier_id"] == x["id"] and best(60)["rate"] == "2400.00"
    q = client.get(f"/api/catalogue/items/{it['id']}/supplier-prices", headers=h).json()["quotes"]
    assert sum(1 for r in q if r["valid_today"]) == 2 and len(q) == 4
    # end the cheap quote → back to cost
    cheap = next(r for r in q if r["supplier_id"] == b["id"])
    assert client.post(f"/api/supplier-prices/{cheap['id']}/end", json={"reason": "Rates revised"}, headers=h).json()["valid_today"] is False
    assert client.post(f"/api/supplier-prices/{cheap['id']}/end", json={"reason": "Again"}, headers=h).status_code == 409
    assert best()["source"] == "COST"
    # validation + roles
    assert P(supplier_id=b["id"], price="0").status_code == 422
    assert P(supplier_id=b["id"], price="10", valid_from=t.isoformat(), valid_to=(t - timedelta(days=1)).isoformat()).status_code == 422
    assert client.get(f"/api/catalogue/items/{it['id']}/supplier-prices", headers=hdr(client, "des34@test.com")).status_code == 403
    client.patch(f"/api/suppliers/{x['id']}", json={"is_active": False}, headers=h)
    assert best(60)["source"] == "COST"                                                                      # inactive supplier's quote ignored


def test_procurement_uses_the_best_quote(client):
    h = hdr(client)
    dflt, cheap = sup(client, h, "Wardrobe works"), sup(client, h, "Better wardrobes")
    wid = next(i for i in client.get("/api/catalogue/items?kind=FURNITURE", headers=h).json() if i["sku"] == "BED-KNG-WLT-001")["id"]
    db = SessionLocal()
    try: w = db.get(m.FurnitureItem, wid); old = (w.supplier_id, w.stock, w.cost_price); w.supplier_id, w.stock = dflt["id"], 0; db.commit()
    finally: db.close()
    client.post(f"/api/catalogue/items/{wid}/supplier-prices", json={"supplier_id": cheap["id"], "price": "61000.00", "lead_days": 21}, headers=h)
    cl = client.post("/api/clients", json={"name": "Quote client", "phone": "9344990001"}, headers=h).json()
    pid = client.post("/api/projects", json={"project_number": "IQ-SPQ-1", "name": "Quote flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): client.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="b", name="King Bed", category="Bed", sku="BED-KNG-WLT-001", price=95000, x=500, y=500, length=1830, width=2130, height=1100)]}, headers=h).json()["version"]
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    r = client.post(f"/api/boqs/{b['id']}/procure", json={}, headers=h).json()
    pos = [client.get(f"/api/purchase-orders/{p['id']}", headers=h).json() for p in r["created"]]
    po = next(p for p in pos if any(l["sku"] == "BED-KNG-WLT-001" for l in p["lines"]))
    line = next(l for l in po["lines"] if l["sku"] == "BED-KNG-WLT-001")
    assert po["supplier_id"] == cheap["id"] and line["rate"] == "61000.00" and any("best valid quote" in s for s in r["supplier_quotes_used"])
    db = SessionLocal()
    try: w = db.get(m.FurnitureItem, wid); w.supplier_id, w.stock, w.cost_price = old; db.query(m.SupplierPrice).filter_by(item_id=wid).delete(); db.commit()
    finally: db.close()
