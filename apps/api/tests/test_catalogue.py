"""M9 catalogue: items of every kind, suppliers, price/stock ledgers, CSV import/export, and how the designer / editor / BOQ use the catalogue."""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.database import SessionLocal, upgrade_schema
from app.core.security import hash_password
from app.main import app, seed
from app.models import models as m
from app.services.catalogue import gstin_check_char, normalize_gstin


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for email, role in (("client9@test.com", "CLIENT"), ("inv@test.com", "INVENTORY_MANAGER"), ("designer9@test.com", "INTERIOR_DESIGNER"),
                            ("proc@test.com", "PROCUREMENT_MANAGER")):
            if not db.query(m.User).filter_by(email=email).first():
                db.add(m.User(email=email, full_name=role.title(), role=role, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def gstin(state="24", pan_seq=None):
    body = f"{state}AAACB{(pan_seq or u()) % 10000:04d}C1Z"
    return body + gstin_check_char(body)


def item(c, h, **kw):
    n = u()
    body = {"sku": f"TST-{n:04d}", "name": f"Test chair {n}", "category": "Chair", "price": "1000.00", "length_mm": 500, "width_mm": 500, "height_mm": 800} | kw
    return c.post("/api/catalogue/items", json=body, headers=h)


def supplier(c, h, **kw):
    n = u(); return c.post("/api/suppliers", json={"name": f"Supplier {n}", "phone": f"9{n + 700000000:09d}"} | kw, headers=h)


# ── GSTIN ──────────────────────────────────────────────────────────────────────
def test_gstin_checksum_matches_a_real_published_gstin():
    assert normalize_gstin("27aapfu0939f1zv") == "27AAPFU0939F1ZV"       # widely published example; lower case and spaces accepted
    assert normalize_gstin(" 27AAPFU 0939F1ZV ") == "27AAPFU0939F1ZV"


@pytest.mark.parametrize("bad, why", [("27AAPFU0939F1ZW", "check digit"), ("27AAPFU0939F1Z", "15 characters"), ("27AAPFU09391FZV", "format"),
                                      ("99AAPFU0939F1ZV", "check digit"), ("00AAPFU0939F1ZV", "state code")])
def test_bad_gstins_are_refused_with_a_reason(bad, why):
    with pytest.raises(ValueError, match=why): normalize_gstin(bad)


# ── Items ──────────────────────────────────────────────────────────────────────
def test_create_item_logs_opening_price_and_stock(client):
    h = hdr(client)
    r = item(client, h, sku="  bed-new 001 ", stock=4, min_stock=2, kind="furniture", unit="no.")
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["sku"] == "BED-NEW-001" and it["kind"] == "FURNITURE" and it["unit"] == "No." and it["price"] == "1000.00" and it["stock_status"] == "OK"
    d = client.get(f"/api/catalogue/items/{it['id']}", headers=h).json()
    assert [p["reason"] for p in d["price_history"]] == ["Item created"] and d["price_history"][0]["old_price"] is None
    assert [(s["delta"], s["balance"], s["reason"]) for s in d["stock_history"]] == [(4, 4, "Opening stock")]
    assert d["price_history"][0]["user_name"] == "Admin User"


def test_duplicate_sku_is_refused_whatever_the_case(client):
    h = hdr(client); item(client, h, sku="DUP-SKU-1")
    r = item(client, h, sku="dup-sku-1"); assert r.status_code == 409 and "already exists" in r.json()["detail"]


@pytest.mark.parametrize("body, field", [({"price": "-1"}, "price"), ({"price": "12.345"}, "price"), ({"price": "abc"}, "price"), ({"sku": "#bad"}, "sku"),
                                         ({"kind": "TOYS"}, "kind"), ({"unit": "bucket"}, "unit"), ({"length_mm": 0}, "length_mm"),
                                         ({"stock": -3}, "stock"), ({"name": ""}, "name"), ({"surprise": 1}, "surprise")])
def test_bad_item_input_is_422_not_500(client, body, field):
    r = item(client, hdr(client), **body)
    assert r.status_code == 422 and field in str(r.json()["detail"])


def test_furniture_needs_a_size_but_materials_do_not(client):
    h = hdr(client)
    r = item(client, h, length_mm=None); assert r.status_code == 422 and "length, width and height" in str(r.json()["detail"])
    r = item(client, h, kind="MATERIAL", category="Plywood", unit="sheet", length_mm=None, width_mm=None, height_mm=None, price="2850.50")
    assert r.status_code == 201 and r.json()["price"] == "2850.50"


def test_edit_cannot_change_sku_price_or_stock(client):
    h = hdr(client); it = item(client, h).json()
    for k, v in (("sku", "NEW"), ("price", "5"), ("stock", 99)):
        assert client.patch(f"/api/catalogue/items/{it['id']}", json={k: v}, headers=h).status_code == 422
    r = client.patch(f"/api/catalogue/items/{it['id']}", json={"name": "Renamed chair", "material": "Teak", "min_stock": 1}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Renamed chair" and r.json()["material"] == "Teak"
    assert client.patch(f"/api/catalogue/items/{it['id']}", json={"length_mm": None}, headers=h).status_code == 422   # furniture keeps its size
    assert client.patch(f"/api/catalogue/items/{it['id']}", json={"name": None}, headers=h).status_code == 422


def test_price_change_needs_a_reason_and_is_kept_in_history(client):
    h = hdr(client); it = item(client, h, price="1000").json(); url = f"/api/catalogue/items/{it['id']}"
    assert client.post(url + "/price", json={"price": "1100"}, headers=h).status_code == 422
    assert client.post(url + "/price", json={"price": "1000.00", "reason": "same"}, headers=h).status_code == 409
    r = client.post(url + "/price", json={"price": "1150.50", "reason": "Supplier increase Nov"}, headers=h)
    assert r.status_code == 200 and r.json()["price"] == "1150.50"
    hist = client.get(url, headers=h).json()["price_history"]
    assert [(p["old_price"], p["new_price"], p["reason"]) for p in hist] == [("1000.00", "1150.50", "Supplier increase Nov"), (None, "1000.00", "Item created")]


def test_stock_ledger_never_goes_negative(client):
    h = hdr(client); it = item(client, h, stock=3, min_stock=2).json(); url = f"/api/catalogue/items/{it['id']}/stock"
    assert client.post(url, json={"delta": -1, "reason": "Issued to site"}, headers=h).json()["stock_status"] == "LOW"
    r = client.post(url, json={"delta": -5, "reason": "Issued"}, headers=h); assert r.status_code == 409 and "Only 2" in r.json()["detail"]
    assert client.post(url, json={"delta": 0, "reason": "nothing"}, headers=h).status_code == 422
    assert client.post(url, json={"delta": -2, "reason": "Issued"}, headers=h).json()["stock_status"] == "OUT"
    assert client.post(url, json={"delta": 10, "reason": "PO received"}, headers=h).json()["stock"] == 10
    hist = client.get(f"/api/catalogue/items/{it['id']}", headers=h).json()["stock_history"]
    assert [(s["delta"], s["balance"]) for s in hist] == [(10, 10), (-2, 0), (-1, 2), (3, 3)]


def test_list_filters_by_kind_search_stock_and_archive(client):
    h = hdr(client); tag = f"Z{u()}"
    a = item(client, h, name=f"{tag} lamp", kind="LIGHTING", category="Downlight", length_mm=None, width_mm=None, height_mm=None, stock=0).json()
    b = item(client, h, name=f"{tag} hinge", kind="HARDWARE", category="Hinge", stock=50, material="SS 304").json()
    L = lambda **q: [i["id"] for i in client.get("/api/catalogue/items", params={"q": tag} | q, headers=h).json()]
    assert L() == [b["id"], a["id"]] or set(L()) == {a["id"], b["id"]}
    assert L(kind="LIGHTING") == [a["id"]] and L(kind="HARDWARE") == [b["id"]]
    assert L(stock="OUT") == [a["id"]] and L(stock="ATTENTION") == [a["id"]]
    assert client.get("/api/catalogue/items", params={"q": "ss 304"}, headers=h).json()[0]["id"] == b["id"]         # search by material
    client.patch(f"/api/catalogue/items/{a['id']}", json={"is_active": False}, headers=h)
    assert L() == [b["id"]] and L(status="archived") == [a["id"]] and set(L(status="all")) == {a["id"], b["id"]}


def test_meta_lists_kinds_units_and_categories(client):
    h = hdr(client); item(client, h, kind="MATERIAL", category="Laminate", unit="sheet", length_mm=None, width_mm=None, height_mm=None)
    meta = client.get("/api/catalogue/meta", headers=h).json()
    assert meta["kinds"] == ["FURNITURE", "MATERIAL", "LIGHTING", "HARDWARE"] and "sheet" in meta["units"] and "Laminate" in meta["categories"]["MATERIAL"]


# ── Roles ──────────────────────────────────────────────────────────────────────
def test_roles(client):
    it = item(client, hdr(client)).json()
    inv, des, cli, proc = (hdr(client, e) for e in ("inv@test.com", "designer9@test.com", "client9@test.com", "proc@test.com"))
    assert client.post(f"/api/catalogue/items/{it['id']}/stock", json={"delta": 2, "reason": "Received"}, headers=inv).status_code == 200
    assert client.post(f"/api/catalogue/items/{it['id']}/price", json={"price": "1", "reason": "nope"}, headers=inv).status_code == 403
    assert client.get("/api/catalogue/items", headers=des).status_code == 200
    assert item(client, des).status_code == 403 and supplier(client, des).status_code == 403
    assert item(client, proc).status_code == 201 and supplier(client, proc).status_code == 201
    for url in ("/api/catalogue/items", "/api/suppliers", "/api/catalogue/meta"): assert client.get(url, headers=cli).status_code == 403
    assert client.get("/api/catalogue/items").status_code == 401


# ── Suppliers ──────────────────────────────────────────────────────────────────
def test_supplier_duplicates_are_caught_by_phone_gstin_and_name(client):
    h = hdr(client); n = u(); g = gstin(pan_seq=n)
    s = supplier(client, h, name=f"Shree Ply {n}", phone=f"+91 99{n:03d}-12345"[:16], gstin=g.lower(), lead_time_days=7, city="Surat")
    assert s.status_code == 201, s.text; s = s.json(); assert s["gstin"] == g
    assert "phone" in supplier(client, h, phone="0" + s["phone"].replace("+91", "").replace(" ", "").replace("-", "")).json()["detail"]
    assert "GSTIN" in supplier(client, h, gstin=g).json()["detail"]
    assert "named" in supplier(client, h, name=f"shree ply {n}").json()["detail"]
    r = supplier(client, h, gstin=g[:14] + ("A" if g[14] != "A" else "B")); assert r.status_code == 422 and "check digit" in str(r.json()["detail"])
    assert supplier(client, h, phone="not a phone").status_code == 422


def test_supplier_edit_search_deactivate_and_item_link(client):
    h = hdr(client); s = supplier(client, h, city="Vadodara", contact_person="Ramesh Patel").json()
    assert client.patch(f"/api/suppliers/{s['id']}", json={"lead_time_days": 10, "city": "Anand"}, headers=h).json()["lead_time_days"] == 10
    assert any(x["id"] == s["id"] for x in client.get("/api/suppliers", params={"q": "ramesh"}, headers=h).json())
    assert any(x["id"] == s["id"] for x in client.get("/api/suppliers", params={"q": s["phone"]}, headers=h).json())   # search by phone
    other = supplier(client, h).json()
    assert client.patch(f"/api/suppliers/{s['id']}", json={"phone": other["phone"]}, headers=h).status_code == 409
    it = item(client, h, supplier_id=s["id"]).json(); assert it["supplier_name"] == s["name"]
    assert item(client, h, supplier_id="nope").status_code == 404
    d = client.get(f"/api/suppliers/{s['id']}", headers=h).json(); assert d["items"] == 1 and d["item_list"][0]["sku"] == it["sku"]
    client.patch(f"/api/suppliers/{s['id']}", json={"is_active": False}, headers=h)
    assert all(x["id"] != s["id"] for x in client.get("/api/suppliers", headers=h).json())
    assert any(x["id"] == s["id"] for x in client.get("/api/suppliers", params={"include_inactive": True}, headers=h).json())


# ── CSV ────────────────────────────────────────────────────────────────────────
def csv_post(c, h, text, apply=False, kind="FURNITURE", enc="utf-8"):
    return c.post("/api/catalogue/import", params={"kind": kind, "apply": apply}, files={"file": ("prices.csv", text.encode(enc), "text/csv")}, headers=h)


def test_csv_preview_then_apply_creates_and_updates_through_the_ledgers(client):
    h = hdr(client); sup = supplier(client, h).json(); old = item(client, h, price="1000", stock=2).json(); n = u()
    text = ("Item Code,Item Name,Category,Rate,Qty,Length,Width,Height,Vendor\n"
            f"{old['sku']},{old['name']},Chair,\"1,250.00\",5,,,,{sup['name']}\n"
            f"NEW-{n},Oak side table {n},Side table,₹ 8500,3,500,450,550,\n")
    prev = csv_post(client, h, text).json()
    assert prev["applied"] is False and prev["summary"] == {"create": 1, "update": 1, "unchanged": 0, "errors": 0}
    ch = {c["field"]: (c["from"], c["to"]) for c in prev["rows"][0]["changes"]}
    assert ch == {"price": ("1000.00", "1250.00"), "stock": (2, 5), "supplier": (None, sup["name"])}
    assert client.get(f"/api/catalogue/items/{old['id']}", headers=h).json()["price"] == "1000.00"       # preview changed nothing
    res = csv_post(client, h, text, apply=True).json(); assert res["applied"] is True
    d = client.get(f"/api/catalogue/items/{old['id']}", headers=h).json()
    assert d["price"] == "1250.00" and d["stock"] == 5 and d["supplier_name"] == sup["name"] and d["length_mm"] == 500   # size kept from before
    assert d["price_history"][0]["reason"] == "CSV import (prices.csv)" and d["stock_history"][0]["delta"] == 3
    assert csv_post(client, h, text).json()["summary"]["unchanged"] == 2                                  # re-import is a no-op


def test_csv_with_any_bad_row_changes_nothing_and_says_which_row(client):
    h = hdr(client); n = u()
    text = ("sku,name,category,price,length_mm,width_mm,height_mm,supplier\n"
            f"OK-{n},Fine chair,Chair,100,500,500,800,\n"
            f"BAD-{n},No price chair,Chair,,500,500,800,\n"
            f"SZ-{n},No size bed,Bed,100,,,,\n"
            f"SUP-{n},Ghost supplier chair,Chair,100,500,500,800,Nobody Traders\n"
            f"OK-{n},Twice,Chair,100,500,500,800,\n")
    res = csv_post(client, h, text, apply=True).json()
    assert res["applied"] is False and res["summary"]["create"] == 1
    errs = {e["row"]: e["error"] for e in res["errors"]}
    assert set(errs) == {3, 4, 5, 6} and "price is required" in errs[3] and "length, width and height" in errs[4]
    assert "Nobody Traders" in errs[5] and "twice" in errs[6]
    assert client.get("/api/catalogue/items", params={"q": f"OK-{n}"}, headers=h).json() == []           # all-or-nothing


def test_csv_semicolons_excel_encoding_and_kind_default(client):
    h = hdr(client); n = u()
    text = f"sku;name;category;price;unit\nLAM-{n};Laminate Café {n};Laminate;1450;sheet\n"
    res = csv_post(client, h, text, apply=True, kind="MATERIAL", enc="cp1252").json()
    assert res["applied"], res
    it = client.get("/api/catalogue/items", params={"q": f"LAM-{n}"}, headers=h).json()[0]
    assert it["kind"] == "MATERIAL" and it["unit"] == "sheet" and it["name"] == f"Laminate Café {n}"
    assert csv_post(client, h, "name,price\nx,1\n").json()["detail"].startswith("Missing column(s): sku, category")
    assert csv_post(client, h, "").status_code == 422
    assert client.post("/api/catalogue/import", params={"kind": "TOYS"}, files={"file": ("a.csv", b"sku\n", "text/csv")}, headers=h).status_code == 422


def test_export_then_reimport_round_trips(client):
    h = hdr(client); sup = supplier(client, h).json()
    item(client, h, kind="HARDWARE", category="Handle", supplier_id=sup["id"], price="245.75", material="Brass")
    r = client.get("/api/catalogue/export.csv", params={"kind": "HARDWARE"}, headers=h)
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf") and "245.75" in r.text and sup["name"] in r.text
    res = csv_post(client, h, r.content.decode("utf-8-sig"), kind="HARDWARE").json()
    assert res["errors"] == [] and res["summary"]["create"] == 0 and res["summary"]["update"] == 0


# ── Catalogue used by designer / editor / BOQ ──────────────────────────────────
def _room(c, h):
    n = u(); pid = c.post("/api/projects", json={"project_number": f"IQ-CAT-{n}", "name": "Cat"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return rid


def test_editor_and_designer_only_see_active_furniture(client):
    h = hdr(client)
    lamp = item(client, h, kind="LIGHTING", category="Pendant", stock=5).json()
    gone = item(client, h, stock=5).json(); client.patch(f"/api/catalogue/items/{gone['id']}", json={"is_active": False}, headers=h)
    skus = {i["sku"] for i in client.get("/api/catalogue/furniture", headers=h).json()}
    assert lamp["sku"] not in skus and gone["sku"] not in skus and "BED-KNG-WLT-001" in skus


def test_boq_carries_supplier_and_unit_and_warns_on_archived(client):
    h = hdr(client); sup = supplier(client, h).json()
    it = item(client, h, price="2000", stock=5, supplier_id=sup["id"], unit="set").json()
    rid = _room(client, h)
    o = dict(id="o1", name=it["name"], category="Chair", sku=it["sku"], price=2000, x=200, y=200, length=500, width=500, height=800)
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [o]}, headers=h).json()["version"]
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    line = next(i for i in b["items"] if i["sku"] == it["sku"])
    assert line["supplier"] == sup["name"] and line["unit"] == "set" and b["warnings"] == []
    client.post(f"/api/catalogue/items/{it['id']}/price", json={"price": "2100", "reason": "Rate revision"}, headers=h)
    client.patch(f"/api/catalogue/items/{it['id']}", json={"is_active": False}, headers=h)
    b2 = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    assert next(i for i in b2["items"] if i["sku"] == it["sku"])["rate"] == "2100.00"
    assert any("archived" in w for w in b2["warnings"]) and any("price changed" in w for w in b2["warnings"])
    assert next(i for i in client.get(f"/api/boqs/{b['id']}", headers=h).json()["items"] if i["sku"] == it["sku"])["rate"] == "2000.00"   # old BOQ frozen


# ── Upgrade of a pre-M9 database ───────────────────────────────────────────────
def test_pre_m9_catalogue_rows_are_upgraded_and_backfilled(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE furniture_items (id VARCHAR PRIMARY KEY, sku VARCHAR NOT NULL UNIQUE, name VARCHAR NOT NULL, category VARCHAR NOT NULL, "
                "length_mm FLOAT, width_mm FLOAT, height_mm FLOAT, price NUMERIC(12,2) NOT NULL, stock INTEGER, material VARCHAR, colour VARCHAR)")
    con.execute("INSERT INTO furniture_items VALUES ('x1','OLD-1','Old bed','Bed',1900,2000,1000,99000,2,NULL,NULL)"); con.commit(); con.close()
    eng = create_engine(f"sqlite:///{path}")
    added = upgrade_schema(eng)
    assert {"furniture_items.kind", "furniture_items.supplier_id", "furniture_items.is_active", "furniture_items.unit"} <= set(added)
    import app.main as main
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=eng)); monkeypatch.setattr(main, "upgrade_schema", lambda: [])
    seed()
    row = sqlite3.connect(path).execute("SELECT sku, kind, unit, is_active, price FROM furniture_items WHERE id='x1'").fetchone()
    assert row == ("OLD-1", "FURNITURE", "No.", 1, 99000)
    assert {"suppliers", "price_changes", "stock_movements"} <= {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
