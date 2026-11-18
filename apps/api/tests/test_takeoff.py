"""M18 material & services take-off: quantities from the saved design (hand-checked), unit conversion + waste + rounding up,
rules validation, BOQ lines (switchable), what-if preview, procurement of take-off items, profit estimate, roles."""
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import takeoff


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="des18@test.com").first():
            db.add(m.User(email="des18@test.com", full_name="Designer", role="INTERIOR_DESIGNER", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        yield c
        c.put("/api/takeoff/rules", json={k: {"sku": None} for k in takeoff.KEYS}, headers=hdr(c))     # leave no rules behind for other tests


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]


OBJS = [dict(id="bed", name="King Bed — Walnut", category="Bed", sku="BED-KNG-WLT-001", price=124000, x=1110, y=1520, length=1930, width=2030, height=1200),
        dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]


def test_quantities_match_a_hand_measurement():
    q = takeoff.quantities(4250, 3600, 2900, OBJS)
    assert q["CEILING_GYPSUM"]["qty"] == D("15.3") and q["COVE_STRIP"]["qty"] == D("12.1")             # 2 × (3350 + 2700) mm inside a 450 mm cove
    assert q["DOWNLIGHT"]["qty"] == 6 and q["SPOTLIGHT"]["qty"] == 1 and q["FAN_POINT"]["qty"] == 1
    assert (q["SOCKET"]["qty"], q["SWITCH"]["qty"], q["SWITCHBOARD"]["qty"], q["AC_POINT"]["qty"], q["LIGHT_POINT"]["qty"]) == (2, 1, 1, 1, 1)
    # walls 15.70 m × 2.90 m = 45.53 m²; the corner wardrobe hides 2.70 m (south) + 0.60 m (west) × 2.20 m = 7.26 m²
    assert q["WALL_PAINT"]["qty"] == D("38.27") and q["FLOORING"]["qty"] == D("15.3") and q["SKIRTING"]["qty"] == D("12.4")


def test_conversion_and_rounding():
    assert takeoff.purchase_qty(takeoff.convert(D("15.3") * D("1.08"), "sq.m", "sq.ft"), "sq.ft") == 178
    assert takeoff.purchase_qty(D("16.065"), "sq.m") == D("16.07") and takeoff.convert(D(1), "sq.m", "box") is None and takeoff.convert(D(3), "No.", "set") == 3


def items(c, h):
    n = u(); mk = lambda **kw: c.post("/api/catalogue/items", json=kw, headers=h).json()
    sup = c.post("/api/suppliers", json={"name": f"Takeoff supplier {n}", "phone": f"9{n + 10000000:09d}"}, headers=h).json()
    return {"gyp": mk(sku=f"TK-GYP-{n}", name="Gypsum ceiling", kind="MATERIAL", category="Ceiling", unit="sq.m", price="85", cost_price="60", supplier_id=sup["id"]),
            "cove": mk(sku=f"TK-COVE-{n}", name="LED strip warm", kind="LIGHTING", category="LED strip", unit="r.ft", price="40", cost_price="25", supplier_id=sup["id"]),
            "dl": mk(sku=f"TK-DL-{n}", name="Downlight 7W", kind="LIGHTING", category="Downlight", unit="No.", price="450", cost_price="300", supplier_id=sup["id"]),
            "sock": mk(sku=f"TK-SOC-{n}", name="Socket point", kind="HARDWARE", category="Electrical", unit="No.", price="350", supplier_id=sup["id"]),
            "paint": mk(sku=f"TK-PNT-{n}", name="Royale paint", kind="MATERIAL", category="Paint", unit="sq.ft", price="22", supplier_id=sup["id"]),
            "tile": mk(sku=f"TK-TILE-{n}", name="Floor tiles", kind="MATERIAL", category="Flooring", unit="box", price="1200"), "sup": sup}


def room(c, h):
    n = u(); pid = c.post("/api/projects", json={"project_number": f"IQ-TK-{n}", "name": "Take-off flat"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2900)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": OBJS}, headers=h).json()["version"]
    return pid, rid, v


def test_rules_are_validated(client):
    h = hdr(client); it = items(client, h)
    assert client.put("/api/takeoff/rules", json={"NOPE": {"sku": "X"}}, headers=h).status_code == 422
    assert client.put("/api/takeoff/rules", json={"DOWNLIGHT": {"sku": "NO-SUCH"}}, headers=h).status_code == 404
    r = client.put("/api/takeoff/rules", json={"FLOORING": {"sku": it["tile"]["sku"]}}, headers=h)
    assert r.status_code == 422 and "sold per box" in r.json()["detail"]                                  # an area can't be priced per box
    assert client.put("/api/takeoff/rules", json={"WALL_PAINT": {"sku": it["paint"]["sku"], "waste_pct": "60"}}, headers=h).status_code == 422
    assert client.put("/api/takeoff/rules", json={"WALL_PAINT": {"sku": it["paint"]["sku"], "waste_pct": "5.55"}}, headers=h).status_code == 422
    assert client.put("/api/takeoff/rules", json={"DOWNLIGHT": {"sku": it["dl"]["sku"]}}, headers=hdr(client, "des18@test.com")).status_code == 403
    assert client.get("/api/takeoff/rules", headers=hdr(client, "des18@test.com")).status_code == 200


def test_boq_includes_priced_takeoff_and_it_flows_into_procurement_and_profit(client):
    h = hdr(client); it = items(client, h)
    client.put("/api/takeoff/rules", json={"CEILING_GYPSUM": {"sku": it["gyp"]["sku"]}, "COVE_STRIP": {"sku": it["cove"]["sku"].lower()}, "DOWNLIGHT": {"sku": it["dl"]["sku"]},
                                           "SOCKET": {"sku": it["sock"]["sku"]}, "WALL_PAINT": {"sku": it["paint"]["sku"]}, "FLOORING": {"sku": None}}, headers=h)
    rules = {r["key"]: r for r in client.get("/api/takeoff/rules", headers=h).json()}
    assert rules["COVE_STRIP"]["sku"] == it["cove"]["sku"] and rules["COVE_STRIP"]["unit_ok"] is True and rules["WALL_PAINT"]["waste_pct"] == "10"
    assert client.get("/api/estimation/defaults", headers=h).json()["include_takeoff"] is True
    pid, rid, v = room(client, h)
    pv = client.get(f"/api/rooms/{rid}/designs/{v}/takeoff", headers=h).json()
    st = {r["key"]: r for r in pv["rows"]}
    assert st["CEILING_GYPSUM"]["status"] == "ADDED" and st["CEILING_GYPSUM"]["buy_qty"] == "16.07"        # 15.3 m² + 5% → 16.065 → 16.07
    assert st["COVE_STRIP"]["buy_qty"] == "42" and st["COVE_STRIP"]["buy_unit"] == "r.ft"                # 12.1 m + 5% = 12.705 m = 41.68 ft → 42
    assert st["WALL_PAINT"]["buy_qty"] == "454"                                                         # 38.27 m² + 10% = 42.097 m² = 453.1 sq.ft → 454
    assert st["FLOORING"]["status"] == "UNMAPPED" and pv["lines"] == 4 + 1
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    tk = {i["sku"]: i for i in b["items"] if "TAKEOFF" in i["flags"]}
    assert set(tk) == {it[k]["sku"] for k in ("gyp", "cove", "dl", "sock", "paint")}
    assert tk[it["gyp"]["sku"]]["qty"] == "16.07" and tk[it["gyp"]["sku"]]["unit"] == "sq.m" and tk[it["gyp"]["sku"]]["rate"] == "85.00"
    assert tk[it["gyp"]["sku"]]["total"] == f"{(D('16.07') * (D('85') + D('6.80'))).quantize(D('0.01'))}"   # labour 8% of rate, same as furniture
    assert tk[it["dl"]["sku"]]["qty"] == "6" and "downlights: 6 No." in tk[it["dl"]["sku"]]["description"]
    assert any("Take-off: Flooring" in w for w in b["warnings"]) and b["include_takeoff"] is True
    assert [i["sku"] for i in b["items"]][:2] == ["BED-KNG-WLT-001", "WAR-SLD-WLT-001"]                  # furniture first, take-off after
    off = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False, "include_takeoff": False}, headers=h).json()
    assert not any("TAKEOFF" in i["flags"] for i in off["items"]) and D(off["totals"]["grand_total"]) < D(b["totals"]["grand_total"])
    pv2 = client.post(f"/api/boqs/{b['id']}/preview", json={"gst_enabled": False}, headers=h).json()
    assert pv2["totals"]["grand_total"] == b["totals"]["grand_total"]                                  # what-if follows the BOQ's own take-off choice
    assert D(client.post(f"/api/boqs/{b['id']}/preview", json={"gst_enabled": False, "include_takeoff": False}, headers=h).json()["delta"]["grand_total"]) < 0
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    res = client.post(f"/api/boqs/{b['id']}/procure", json={}, headers=h).json()
    po = client.get(f"/api/purchase-orders/{res['created'][0]['id']}", headers=h).json()
    lines = {l["sku"]: l for l in po["lines"]}
    assert lines[it["gyp"]["sku"]]["qty"] == 17 and lines[it["gyp"]["sku"]]["rate"] == "60.00"            # whole units to buy, at cost
    assert lines[it["dl"]["sku"]]["qty"] == 6 and lines[it["paint"]["sku"]]["qty"] == 454
    pr = client.get(f"/api/projects/{pid}/profit", headers=h).json()
    assert any(x.startswith(it["sock"]["name"]) for x in pr["missing_cost"]) and D(pr["estimate"]["materials"]) > 0     # socket has no cost price


def test_archived_or_missing_items_are_reported_not_guessed(client):
    h = hdr(client); it = items(client, h)
    client.put("/api/takeoff/rules", json={"DOWNLIGHT": {"sku": it["dl"]["sku"]}}, headers=h)
    client.patch(f"/api/catalogue/items/{it['dl']['id']}", json={"is_active": False}, headers=h)
    pid, rid, v = room(client, h)
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    assert not any(i["sku"] == it["dl"]["sku"] for i in b["items"]) and any("archived" in w and "Downlights" in w for w in b["warnings"])
