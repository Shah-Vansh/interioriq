"""M16: purchase cost vs selling price, cost-priced POs and stock, expenses, project profitability (hand-checked numbers), role gating, AI margin rules."""
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
        for e, r in (("des16@test.com", "INTERIOR_DESIGNER"), ("inv16@test.com", "INVENTORY_MANAGER"), ("est16@test.com", "ESTIMATOR"), ("site16@test.com", "SITE_ENGINEER")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=r.title(), role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def item(c, h, **kw):
    n = u(); body = {"sku": f"PF-{n}", "name": f"Profit chair {n}", "category": "Chair", "price": "2000", "length_mm": 500, "width_mm": 500, "height_mm": 800} | kw
    r = c.post("/api/catalogue/items", json=body, headers=h); assert r.status_code == 201, r.text; return r.json()


# ── cost price ────────────────────────────────────────────────────────────────
def test_cost_price_margin_history_and_who_sees_it(client):
    h = hdr(client); it = item(client, h, cost_price="1200.00")
    assert it["cost_price"] == "1200.00" and it["margin_pct"] == "40.0" and it["cost_visible"] is True
    for e in ("des16@test.com", "inv16@test.com"):
        o = client.get(f"/api/catalogue/items/{it['id']}", headers=hdr(client, e)).json()
        assert o["cost_price"] is None and o["margin_pct"] is None and all(p["field"] == "PRICE" for p in o["price_history"])
        assert all(x["cost_price"] is None for x in client.get("/api/catalogue/items", params={"q": it["sku"]}, headers=hdr(client, e)).json())
    assert client.get(f"/api/catalogue/items/{it['id']}", headers=hdr(client, "est16@test.com")).json()["cost_price"] == "1200.00"
    url = f"/api/catalogue/items/{it['id']}/cost"
    assert client.post(url, json={"cost": "1200", "reason": "same"}, headers=h).status_code == 409
    assert client.post(url, json={"cost": "-1", "reason": "neg"}, headers=h).status_code == 422
    assert client.post(url, json={"cost": "1300", "reason": "x"}, headers=h).status_code == 422
    assert client.post(url, json={"cost": "1300"}, headers=hdr(client, "est16@test.com")).status_code in (403, 422)
    r = client.post(url, json={"cost": "1300.50", "reason": "Supplier revision"}, headers=h).json()
    assert r["cost_price"] == "1300.50" and r["margin_pct"] == "35.0"
    hist = client.get(f"/api/catalogue/items/{it['id']}", headers=h).json()["price_history"]
    assert [(p["field"], p["old_price"], p["new_price"]) for p in hist if p["field"] == "COST"] == [("COST", "1200.00", "1300.50"), ("COST", None, "1200.00")]


def test_csv_cost_column_round_trip_and_hidden_from_others(client):
    h = hdr(client); n = u()
    text = f"sku,name,category,price,cost price,length_mm,width_mm,height_mm\nCSV-PF-{n},CSV chair {n},Chair,2500,1500,500,500,800\n"
    r = client.post("/api/catalogue/import", params={"apply": True}, files={"file": ("c.csv", text.encode(), "text/csv")}, headers=h).json()
    assert r["applied"]
    it = client.get("/api/catalogue/items", params={"q": f"CSV-PF-{n}"}, headers=h).json()[0]; assert it["cost_price"] == "1500.00"
    upd = text.replace(",1500,", ",1600,")
    prev = client.post("/api/catalogue/import", files={"file": ("c.csv", upd.encode(), "text/csv")}, headers=h).json()
    assert prev["rows"][0]["changes"] == [{"field": "cost", "from": "1500.00", "to": "1600.00"}]
    client.post("/api/catalogue/import", params={"apply": True}, files={"file": ("c.csv", upd.encode(), "text/csv")}, headers=h)
    hist = client.get(f"/api/catalogue/items/{it['id']}", headers=h).json()["price_history"]
    assert hist[0]["field"] == "COST" and hist[0]["new_price"] == "1600.00" and hist[0]["reason"].startswith("CSV import")
    admin_csv = client.get("/api/catalogue/export.csv", headers=h).text; des_csv = client.get("/api/catalogue/export.csv", headers=hdr(client, "des16@test.com")).text
    assert ",price,cost,stock," in admin_csv.splitlines()[0] and "cost" not in des_csv.splitlines()[0] and "1600.00" not in des_csv


# ── a costed job ──────────────────────────────────────────────────────────────
def job(c, h, cost="1200", stock=1, gst=True):
    n = u()
    sup = c.post("/api/suppliers", json={"name": f"PF supplier {n}", "phone": f"9{n + 30000000:09d}"}, headers=h).json()
    it = item(c, h, cost_price=cost, stock=stock, supplier_id=sup["id"]) if cost else item(c, h, stock=stock, supplier_id=sup["id"])
    pid = c.post("/api/projects", json={"project_number": f"IQ-PF-{n}", "name": "Profit flat"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id=f"c{i}", name=it["name"], category="Chair", sku=it["sku"], price=2000, x=300 + i * 700, y=300, length=500, width=500, height=800) for i in range(2)]
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": gst}, headers=h).json()
    c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    return pid, b, it


def test_profit_numbers_match_a_hand_calculation(client):
    h = hdr(client); pid, b, it = job(client, h)
    p0 = client.get(f"/api/projects/{pid}/profit", headers=h).json()
    revenue = D(b["totals"]["after_discount"])
    assert p0["revenue"] == f"{revenue:.2f}" and D(p0["gst"]) == D(b["totals"]["gst"]) > 0 and D(p0["contract_value"]) == D(b["totals"]["grand_total"])
    # estimate: 2 × cost 1200 + labour 8% of the 2000 selling rate × 2 = 2400 + 320
    assert p0["estimate"] == {"materials": "2400.00", "labour": "320.00", "lump_sums": "0.00", "total": "2720.00",
                              "profit": f"{revenue - D('2720'):.2f}", "margin_pct": f"{((revenue - D('2720')) * 100 / revenue).quantize(D('0.1'))}"}
    assert p0["actual"]["total"] == "0.00" and p0["missing_cost"] == []
    res = client.post(f"/api/boqs/{b['id']}/procure", json={"use_stock": True}, headers=h).json()       # 1 from stock @1200, 1 on a PO @1200
    po = client.get(f"/api/purchase-orders/{res['created'][0]['id']}", headers=h).json()
    assert po["lines"][0]["rate"] == "1200.00"                                                               # PO uses COST, not the selling price
    client.post(f"/api/projects/{pid}/expenses", json={"category": "LABOUR", "amount": "500", "spent_on": date.today().isoformat(), "vendor": "Ramesh carpenter"}, headers=h)
    p = client.get(f"/api/projects/{pid}/profit", headers=h).json()
    assert p["actual"]["purchase_orders"] == "1200.00" and p["actual"]["from_stock"] == "1200.00" and p["actual"]["expenses"] == {"LABOUR": "500.00"}
    assert p["actual"]["total"] == "2900.00" and p["actual"]["profit"] == f"{revenue - D('2900'):.2f}" and p["variance"] == "180.00"
    assert p["actual"]["purchase_received"] == "0.00" and p["by_supplier"][0]["amount"] == "1200.00"


def test_po_rate_falls_back_to_price_and_draft_rates_are_editable(client):
    h = hdr(client); pid, b, it = job(client, h, cost=None, stock=0)
    created = client.post(f"/api/boqs/{b['id']}/procure", json={}, headers=h).json()["created"]
    po = client.get(f"/api/purchase-orders/{created[0]['id']}", headers=h).json()
    line = po["lines"][0]; assert line["rate"] == "2000.00"                                                 # no cost known → selling price, flagged in profit
    assert client.get(f"/api/projects/{pid}/profit", headers=h).json()["missing_cost"] == [it["name"]]
    assert client.patch(f"/api/purchase-orders/{po['id']}", json={"lines": [{"id": line["id"], "rate": "12.345"}]}, headers=h).status_code == 422
    assert client.patch(f"/api/purchase-orders/{po['id']}", json={"lines": [{"id": line["id"], "rate": "-5"}]}, headers=h).status_code == 422
    r = client.patch(f"/api/purchase-orders/{po['id']}", json={"lines": [{"id": line["id"], "rate": "1,450.00"}]}, headers=h).json()
    assert r["lines"][0]["rate"] == "1450.00" and r["lines"][0]["qty"] == 2 and r["total"] == "2900.00"
    client.post(f"/api/purchase-orders/{po['id']}/issue", headers=h)
    assert client.patch(f"/api/purchase-orders/{po['id']}", json={"lines": [{"id": line["id"], "rate": "1"}]}, headers=h).status_code == 409
    assert client.get(f"/api/projects/{pid}/profit", headers=h).json()["actual"]["purchase_orders"] == "2900.00"


def test_gst_off_revenue_equals_contract_value(client):
    h = hdr(client); pid, b, _ = job(client, h, gst=False)
    p = client.get(f"/api/projects/{pid}/profit", headers=h).json()
    assert p["gst"] == "0.00" and p["revenue"] == p["contract_value"] == b["totals"]["grand_total"]


def test_expenses_validation_void_and_roles(client):
    h = hdr(client); pid, b, _ = job(client, h)
    base = {"category": "TRANSPORT", "amount": "750.50", "spent_on": date.today().isoformat()}
    assert client.post(f"/api/projects/{pid}/expenses", json={**base, "category": "PARTY"}, headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/expenses", json={**base, "amount": "0"}, headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/expenses", json={**base, "spent_on": (date.today() + timedelta(days=1)).isoformat()}, headers=h).status_code == 422
    site = hdr(client, "site16@test.com")
    e = client.post(f"/api/projects/{pid}/expenses", json={**base, "vendor": "Tempo"}, headers=site); assert e.status_code == 201; e = e.json()
    assert client.get(f"/api/projects/{pid}/profit", headers=site).status_code == 403                    # records costs, doesn't see margins
    assert client.post(f"/api/projects/{pid}/expenses", json=base, headers=hdr(client, "des16@test.com")).status_code == 403
    assert client.get(f"/api/projects/{pid}/profit", headers=h).json()["actual"]["expenses"] == {"TRANSPORT": "750.50"}
    assert client.post(f"/api/expenses/{e['id']}/void", json={"reason": "no"}, headers=h).status_code == 422
    assert client.post(f"/api/expenses/{e['id']}/void", json={"reason": "Duplicate bill"}, headers=h).json()["status"] == "VOID"
    assert client.post(f"/api/expenses/{e['id']}/void", json={"reason": "again"}, headers=h).status_code == 409
    assert client.get(f"/api/projects/{pid}/profit", headers=h).json()["actual"]["expenses_total"] == "0.00"
    assert any("voided: Duplicate bill" in t["text"] for t in client.get(f"/api/projects/{pid}/timeline", headers=h).json())


def test_report_and_ai_margin_rules_are_for_managers_only(client):
    h = hdr(client); pid, b, _ = job(client, h)
    client.post(f"/api/projects/{pid}/expenses", json={"category": "CONTRACTOR", "amount": "999999", "spent_on": date.today().isoformat()}, headers=h)
    rep = client.get("/api/reports/profitability", headers=h).json()
    row = next(r for r in rep["projects"] if r["id"] == pid)
    assert D(row["profit"]) < 0 and any("loss" in f for f in row["flags"]) and rep["totals"]["revenue"]
    assert client.get("/api/reports/profitability", headers=hdr(client, "est16@test.com")).status_code == 403
    mine = [a for a in client.get("/api/ai/alerts", headers=h).json()["alerts"] if a["project_id"] == pid]
    assert {"LOW_MARGIN", "COST_OVERRUN"} <= {a["rule"] for a in mine} and next(a for a in mine if a["rule"] == "LOW_MARGIN")["severity"] == "HIGH"
    des = [a for a in client.get("/api/ai/alerts", headers=hdr(client, "des16@test.com")).json()["alerts"] if a["project_id"] == pid]
    assert not {"LOW_MARGIN", "COST_OVERRUN"} & {a["rule"] for a in des}
