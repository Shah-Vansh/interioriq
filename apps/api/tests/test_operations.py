"""M10–M11 end to end: quotation approval → payments → procurement (stock allocation + POs + boards from cutting lists) → goods receipt →
work orders → delivery → installation → QC + snags → handover. Every gate is tested from both sides."""
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import cutting


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for email, role in (("des10@test.com", "INTERIOR_DESIGNER"), ("inv10@test.com", "INVENTORY_MANAGER"), ("cli10@test.com", "CLIENT"),
                            ("qc10@test.com", "QC_MANAGER"), ("site10@test.com", "SITE_ENGINEER")):
            if not db.query(m.User).filter_by(email=email).first():
                db.add(m.User(email=email, full_name=role.title(), role=role, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}


def pdf_text(b: bytes) -> str:
    d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def setup_job(c, h, chair_stock=1):
    n = u()
    sup = c.post("/api/suppliers", json={"name": f"Ops Supplier {n}", "phone": f"9{n + 600000000:09d}"}, headers=h).json()
    mk = lambda **kw: c.post("/api/catalogue/items", json=kw, headers=h).json()
    chair = mk(sku=f"OPS-CHR-{n}", name=f"Ops chair {n}", category="Chair", price="2000", stock=chair_stock, length_mm=500, width_mm=500, height_mm=800, supplier_id=sup["id"])
    ward = mk(sku=f"OPS-WRD-{n}", name=f"Ops wardrobe {n}", category="Wardrobe", price="90000", length_mm=1800, width_mm=600, height_mm=2100)
    ply = mk(sku=f"OPS-PLY-{n}", name="BWP ply 18mm", kind="MATERIAL", category="Plywood", unit="sheet", price="2850", supplier_id=sup["id"])
    back = mk(sku=f"OPS-BCK-{n}", name="HDHMR 8mm", kind="MATERIAL", category="Board", unit="sheet", price="1450", supplier_id=sup["id"])
    edge = mk(sku=f"OPS-EDG-{n}", name="Edge band 0.8mm", kind="MATERIAL", category="Edge band", unit="r.m", price="12", supplier_id=sup["id"])
    db = SessionLocal()
    for k, v in (("board_sku_18", ply["sku"]), ("board_sku_8", back["sku"]), ("edge_band_sku", edge["sku"])):
        row = db.get(m.CompanySetting, k)
        if row: row.value = v
        else: db.add(m.CompanySetting(key=k, value=v))
    db.commit(); db.close()
    pid = c.post("/api/projects", json={"project_number": f"IQ-OPS-{n}", "name": "Ops flat", "site_address": "Flat 4, Satellite, Ahmedabad"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id="w", name=ward["name"], category="Wardrobe", sku=ward["sku"], price=90000, x=50, y=50, length=1800, width=600, height=2100),
            dict(id="c1", name=chair["name"], category="Chair", sku=chair["sku"], price=2000, x=2600, y=1500, length=500, width=500, height=800),
            dict(id="c2", name=chair["name"], category="Chair", sku=chair["sku"], price=2000, x=3300, y=1500, length=500, width=500, height=800)]
    d = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json(); assert d["is_valid"], d
    boq = c.post(f"/api/rooms/{rid}/designs/{d['version']}/boq", json={}, headers=h).json()
    return dict(n=n, sup=sup, chair=chair, ward=ward, ply=ply, back=back, edge=edge, pid=pid, rid=rid, boq=boq, version=d["version"])


def test_cutting_list_is_sane():
    cl = cutting.cut_list(2700, 600, 2200)
    names = {p["name"].split(" (")[0] for p in cl["panels"]}
    assert {"Side", "Top", "Bottom", "Partition", "Shelf", "Shutter", "Back"} <= names
    assert all(p["length"] <= cutting.SHEET_L and p["width"] <= cutting.SHEET_W for p in cl["panels"])     # every piece fits a sheet
    area = sum(p["length"] * p["width"] * p["qty"] for p in cl["panels"] if p["thickness"] == 18)
    assert cl["sheets"]["18"]["sheets"] >= area / (cutting.SHEET_L * cutting.SHEET_W)                      # can't use fewer sheets than the area needs
    assert cutting.nest([(2400, 1200)] * 3) == (3, pytest.approx(3 * 2400 * 1200 / (3 * 2440 * 1220)))
    assert cutting.nest([(1200, 600)] * 4)[0] == 1
    assert not cutting.is_manufactured("Chair", 500, 500, 800) and cutting.is_manufactured("Wardrobe", 1800, 600, 2100)


def test_full_flow_from_quotation_to_handover(client):
    h = hdr(client); j = setup_job(client, h); pid, boq = j["pid"], j["boq"]; bid = boq["id"]
    ov = lambda: client.get(f"/api/projects/{pid}/overview", headers=h).json()
    assert ov()["status"] == "QUOTATION"

    # nothing executes before approval
    assert client.post(f"/api/boqs/{bid}/procure", json={}, headers=h).status_code == 409
    assert client.post(f"/api/projects/{pid}/payments", json={"boq_id": bid, "amount": "1000", "received_on": "2026-11-01", "mode": "UPI"}, headers=h).status_code == 409
    assert client.post(f"/api/boqs/{bid}/work-orders", headers=h).status_code == 409

    # quotation status rules
    assert client.post(f"/api/boqs/{bid}/status", json={"status": "SENT"}, headers=h).json()["status"] == "SENT"
    assert client.post(f"/api/boqs/{bid}/status", json={"status": "REJECTED"}, headers=h).status_code == 422          # reason required
    assert client.post(f"/api/boqs/{bid}/status", json={"status": "BOGUS"}, headers=h).status_code == 409
    assert client.post(f"/api/boqs/{bid}/status", json={"status": "APPROVED", "note": "Signed 17 Nov"}, headers=h).json()["status"] == "APPROVED"
    assert client.post(f"/api/boqs/{bid}/status", json={"status": "REJECTED", "note": "x"}, headers=h).status_code == 409    # approved is final
    assert ov()["status"] == "PROCUREMENT"

    # payments: never more than the quotation, schedule fills in order
    total = boq["totals"]["grand_total"]
    r = client.post(f"/api/projects/{pid}/payments", json={"boq_id": bid, "amount": str(float(total) + 1), "received_on": "2026-11-01", "mode": "UPI"}, headers=h)
    assert r.status_code == 409 and "more than the quotation total" in r.json()["detail"]
    assert client.post(f"/api/projects/{pid}/payments", json={"boq_id": bid, "amount": "100", "received_on": "2999-01-01", "mode": "UPI"}, headers=h).status_code == 422
    first = client.get(f"/api/projects/{pid}/payments", headers=h).json()["schedule"][0]["amount"]
    pay = client.post(f"/api/projects/{pid}/payments", json={"boq_id": bid, "amount": first, "received_on": "2026-11-10", "mode": "BANK", "reference": "UTR123"}, headers=h).json()
    assert pay["schedule"][0]["status"] == "PAID" and pay["schedule"][1]["status"] == "DUE" and pay["paid"] == first

    # procurement: 1 chair from stock, 1 on a PO, boards from the cutting list on the same supplier's PO
    res = client.post(f"/api/boqs/{bid}/procure", json={"use_stock": True}, headers=h).json()
    assert res["allocated_from_stock"] == [{"sku": j["chair"]["sku"], "qty": 1}] and len(res["created"]) == 1 and not res["unassigned"]
    po = client.get(f"/api/purchase-orders/{res['created'][0]['id']}", headers=h).json()
    lines = {l["sku"]: l for l in po["lines"]}
    need = cutting.cut_list(1800, 600, 2100)
    assert lines[j["chair"]["sku"]]["qty"] == 1
    assert lines[j["ply"]["sku"]]["qty"] == need["sheets"]["18"]["sheets"] and lines[j["back"]["sku"]]["qty"] == need["sheets"]["8"]["sheets"]
    assert lines[j["edge"]["sku"]]["qty"] == int(-(-need["edge_band_m"] // 1))
    assert j["ward"]["sku"] not in lines                                                     # made in-house, never purchased
    assert client.post(f"/api/boqs/{bid}/procure", json={}, headers=h).json()["nothing_to_do"] is True   # re-running orders nothing twice
    assert client.get(f"/api/catalogue/items/{j['chair']['id']}", headers=h).json()["stock"] == 0

    # delivery is gated by what is actually ready
    sched = {"boq_id": bid, "scheduled_on": "2026-11-20", "vehicle": "GJ01AB1234", "lines": [{"sku": j["chair"]["sku"], "qty": 2}]}
    r = client.post(f"/api/projects/{pid}/deliveries", json=sched, headers=h); assert r.status_code == 409 and "only 1 can be delivered" in r.json()["detail"]

    # receive the PO
    assert client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": [{"line_id": po["lines"][0]["id"], "qty": 1}]}, headers=h).status_code == 409   # not issued
    assert client.post(f"/api/purchase-orders/{po['id']}/issue", headers=h).json()["status"] == "ISSUED"
    big = [{"line_id": l["id"], "qty": l["qty"] + 1} for l in po["lines"][:1]]
    assert client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": big}, headers=h).status_code == 409
    inv = hdr(client, "inv10@test.com")
    part = client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": [{"line_id": lines[j["chair"]["sku"]]["id"], "qty": 1}]}, headers=inv).json()
    assert part["status"] == "PARTIAL"
    rest = [{"line_id": l["id"], "qty": l["qty"]} for l in po["lines"] if l["sku"] != j["chair"]["sku"]]
    assert client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": rest}, headers=inv).json()["status"] == "RECEIVED"
    assert client.post(f"/api/purchase-orders/{po['id']}/cancel", headers=h).status_code == 409
    mv = client.get("/api/inventory/movements", params={"item_id": j["chair"]["id"]}, headers=h).json()
    assert [x["delta"] for x in mv][:2] == [-1, 1] and mv[0]["balance"] == 0                 # received in, allocated out
    ptxt = pdf_text(client.get(f"/api/purchase-orders/{po['id']}/pdf", headers=h).content)
    assert po["po_number"] in ptxt and "PURCHASE ORDER" in ptxt and j["sup"]["name"] in ptxt and "Flat 4, Satellite" in ptxt

    # manufacturing
    wos = client.post(f"/api/boqs/{bid}/work-orders", headers=h).json()["created"]
    assert len(wos) == 1 and wos[0]["cut_list"]["sheets"]["18"]["sheets"] == need["sheets"]["18"]["sheets"]
    assert client.post(f"/api/boqs/{bid}/work-orders", headers=h).json()["created"] == []
    r = client.post(f"/api/projects/{pid}/deliveries", json={**sched, "lines": [{"sku": j["ward"]["sku"], "qty": 1}]}, headers=h)
    assert r.status_code == 409 and "0 of 1 made" in r.json()["detail"]
    assert client.post(f"/api/work-orders/{wos[0]['id']}/stage", json={"stage": "NOPE"}, headers=h).status_code == 422
    for st in ("CUTTING", "EDGEBANDING", "ASSEMBLY", "FINISHING", "READY"):
        assert client.post(f"/api/work-orders/{wos[0]['id']}/stage", json={"stage": st}, headers=h).json()["stage"] == st
    assert ov()["status"] == "MANUFACTURING"

    # delivery
    dn = client.post(f"/api/projects/{pid}/deliveries", json={**sched, "lines": [{"sku": j["chair"]["sku"], "qty": 2}, {"sku": j["ward"]["sku"], "qty": 1}]}, headers=h)
    assert dn.status_code == 201, dn.text; dn = dn.json()
    assert client.post(f"/api/projects/{pid}/deliveries", json=sched, headers=h).status_code == 409          # already booked
    assert client.post(f"/api/work-orders/{wos[0]['id']}/stage", json={"stage": "ASSEMBLY"}, headers=h).status_code == 409   # booked unit can't go back
    assert client.post(f"/api/deliveries/{dn['id']}/deliver", json={"received_by": "Mr Shah"}, headers=h).status_code == 409  # dispatch first
    client.post(f"/api/deliveries/{dn['id']}/dispatch", headers=h)
    assert client.post(f"/api/deliveries/{dn['id']}/deliver", json={"received_by": "Mr Shah"}, headers=h).json()["status"] == "DELIVERED"
    assert client.post(f"/api/deliveries/{dn['id']}/cancel", headers=h).status_code == 409
    assert dn["dn_number"] in pdf_text(client.get(f"/api/deliveries/{dn['id']}/pdf", headers=h).content)
    assert ov()["status"] == "DELIVERY"

    # handover is blocked, with reasons
    r = client.post(f"/api/projects/{pid}/handover", json={"received_by": "Mr Shah"}, headers=h)
    assert r.status_code == 409 and "installation task" in r.json()["detail"] and "QC inspection not started" in r.json()["detail"]

    # installation
    tasks = client.get(f"/api/projects/{pid}/install-tasks", headers=h).json()
    assert sorted(t["qty"] for t in tasks) == [1, 2]
    assert client.post(f"/api/projects/{pid}/qc/start", headers=h).status_code == 409
    site = hdr(client, "site10@test.com")
    for t in tasks:
        assert client.patch(f"/api/install-tasks/{t['id']}", json={"status": "DONE", "note": "Fixed and levelled"}, headers=site).json()["status"] == "DONE"
    assert ov()["status"] == "QC"

    # QC + snags
    qc = client.post(f"/api/projects/{pid}/qc/start", headers=hdr(client, "qc10@test.com")).json()
    assert len(qc["checks"]) == 2 + 6 and qc["readiness"]["ready"] is False
    q = hdr(client, "qc10@test.com"); c0 = qc["checks"][0]["id"]
    assert client.post(f"/api/qc-checks/{c0}", json={"status": "FAIL"}, headers=q).status_code == 422
    qc = client.post(f"/api/qc-checks/{c0}", json={"status": "FAIL", "note": "Left shutter rubs"}, headers=q).json()
    snag = qc["snags"][0]; assert snag["status"] == "OPEN"
    assert client.post(f"/api/qc-checks/{c0}", json={"status": "PASS"}, headers=q).status_code == 409
    qc = client.post(f"/api/snags/{snag['id']}/fix", json={"note": "Hinge adjusted"}, headers=site).json()
    assert next(x for x in qc["checks"] if x["id"] == c0)["status"] == "PENDING"
    for ch in qc["checks"]: qc = client.post(f"/api/qc-checks/{ch['id']}", json={"status": "PASS"}, headers=q).json()
    assert qc["readiness"]["ready"] is True

    # handover
    assert client.post(f"/api/projects/{pid}/handover", json={"received_by": "Mr Shah"}, headers=q).status_code == 403
    ho = client.post(f"/api/projects/{pid}/handover", json={"received_by": "Mr Shah", "notes": "Keys handed over"}, headers=h).json()
    assert ho["handover"]["warranty_months"] == 12 and ov()["status"] == "COMPLETED" and ov()["progress"] == 100
    txt = pdf_text(client.get(f"/api/projects/{pid}/handover.pdf", headers=h).content)
    assert "Mr Shah" in txt and "HANDOVER CERTIFICATE" in txt and j["ward"]["name"] in txt
    assert client.patch(f"/api/install-tasks/{tasks[0]['id']}", json={"status": "PENDING"}, headers=h).status_code == 409   # closed
    assert client.post(f"/api/projects/{pid}/handover", json={"received_by": "x y"}, headers=h).status_code == 409

    # timeline tells the whole story, newest first
    tl = [e["text"] for e in client.get(f"/api/projects/{pid}/timeline", headers=h).json()]
    for needle in ("Handed over to Mr Shah", "QC failed", "Snag fixed", "delivered, received by Mr Shah", "work order(s) created", "issued to", "APPROVED", "drafted from design"):
        assert any(needle in t for t in tl), needle
    assert tl.index(next(t for t in tl if "Handed over" in t)) < tl.index(next(t for t in tl if "APPROVED" in t))
    assert any(p["id"] == pid for p in client.get("/api/projects", params={"view": "completed"}, headers=h).json())


def test_unassigned_supplier_and_manual_lines_are_reported(client):
    h = hdr(client); j = setup_job(client, h, chair_stock=0)
    db = SessionLocal(); it = db.get(m.FurnitureItem, j["chair"]["id"]); it.supplier_id = None; db.commit(); db.close()
    client.post(f"/api/boqs/{j['boq']['id']}/status", json={"status": "APPROVED"}, headers=h)
    res = client.post(f"/api/boqs/{j['boq']['id']}/procure", json={}, headers=h).json()
    assert any(j["chair"]["sku"] in x and "× 2" in x for x in res["unassigned"])


def test_second_version_cannot_be_approved_once_the_first_is_in_execution(client):
    h = hdr(client); j = setup_job(client, h)
    client.post(f"/api/boqs/{j['boq']['id']}/status", json={"status": "APPROVED"}, headers=h)
    b2 = client.post(f"/api/rooms/{j['rid']}/designs/{j['version']}/boq", json={"discount_pct": "10"}, headers=h).json()
    client.post(f"/api/boqs/{j['boq']['id']}/procure", json={}, headers=h)
    r = client.post(f"/api/boqs/{b2['id']}/status", json={"status": "APPROVED"}, headers=h)
    assert r.status_code == 409 and "purchase orders" in r.json()["detail"]
    for po in client.get("/api/purchase-orders", params={"project_id": j["pid"]}, headers=h).json(): client.post(f"/api/purchase-orders/{po['id']}/cancel", headers=h)
    db = SessionLocal()
    for mv in db.query(m.StockMovement).filter_by(ref_type="ALLOC", ref_id=j["boq"]["id"]): mv.ref_id = "released"   # simulate the allocation being returned
    db.commit(); db.close()
    assert client.post(f"/api/boqs/{b2['id']}/status", json={"status": "APPROVED"}, headers=h).json()["status"] == "APPROVED"
    qs = {q["id"]: q["status"] for q in client.get("/api/quotations", params={"project_id": j["pid"]}, headers=h).json()}
    assert qs == {j["boq"]["id"]: "SUPERSEDED", b2["id"]: "APPROVED"}


def test_roles_and_client_visibility(client):
    h = hdr(client); j = setup_job(client, h)
    des, cli = hdr(client, "des10@test.com"), hdr(client, "cli10@test.com")
    assert client.post(f"/api/boqs/{j['boq']['id']}/status", json={"status": "SENT"}, headers=des).status_code == 403
    client.post(f"/api/boqs/{j['boq']['id']}/status", json={"status": "APPROVED"}, headers=h)
    assert client.post(f"/api/boqs/{j['boq']['id']}/procure", json={}, headers=des).status_code == 403
    for url in ("/api/quotations", "/api/purchase-orders", f"/api/projects/{j['pid']}/overview", "/api/inventory/movements"):
        assert client.get(url, headers=cli).status_code == 403
    assert client.get("/api/projects", headers=cli).json() == []          # a client user with no linked client sees nothing


def test_manual_status_and_archive(client):
    h = hdr(client); j = setup_job(client, h); pid = j["pid"]
    assert client.patch(f"/api/projects/{pid}", json={"status": "COMPLETED"}, headers=h).status_code == 409
    assert client.patch(f"/api/projects/{pid}", json={"status": "WHATEVER"}, headers=h).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"status": "DESIGN"}, headers=h).json()["status"] == "DESIGN"
    client.patch(f"/api/projects/{pid}", json={"archived": True}, headers=h)
    assert any(p["id"] == pid for p in client.get("/api/projects", params={"view": "archived"}, headers=h).json())
    assert all(p["id"] != pid for p in client.get("/api/projects", params={"view": "active"}, headers=h).json())
    tl = [e["text"] for e in client.get(f"/api/projects/{pid}/timeline", headers=h).json()]
    assert any("set by hand" in t for t in tl) and any("archived" in t for t in tl)
