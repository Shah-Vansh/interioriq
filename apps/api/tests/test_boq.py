import io, random
from decimal import Decimal as D
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services.cost_engine import inr, split_payments

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="client@test.com").first():
            db.add(m.User(email="client@test.com", full_name="C", role="CLIENT", password_hash=hash_password("ChangeMe123!"))); db.commit()
        db.close(); yield c

def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}

_n = [0]
def room(c, h, number=None):
    _n[0] += 1
    pid = c.post("/api/projects", json={"project_number": number or f"IQ-B-{_n[0]}", "name": "BOQ test"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Master Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)):
        c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return rid

def catalogue(sku, name, price, stock=5, category="Chair", material="Oak"):
    db = SessionLocal(); it = db.query(m.FurnitureItem).filter_by(sku=sku).first()
    if it: it.price, it.name, it.stock = price, name, stock
    else: db.add(m.FurnitureItem(sku=sku, name=name, category=category, length_mm=500, width_mm=500, height_mm=800, price=price, stock=stock, material=material))
    db.commit(); db.close()

def obj(i, name="Chair", sku="", price=0, category="Chair", x=None, y=100):
    return dict(id=f"o{i}", name=name, category=category, sku=sku, price=price, x=100 + i * 700 if x is None else x, y=y, length=500, width=500, height=800)

def save(c, h, rid, objects):
    r = c.post(f"/api/rooms/{rid}/designs", json={"objects": objects}, headers=h).json(); return r["version"]

def boq(c, h, rid, version, **params):
    return c.post(f"/api/rooms/{rid}/designs/{version}/boq", json=params, headers=h)

def pdf_text(data: bytes) -> str:
    doc = pdfium.PdfDocument(data); return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))

# ── the numbers: expected values derived independently by hand ────────────────
def test_bed_and_wardrobe_total_matches_hand_calculation(client):
    h = hdr(client); rid = room(client, h)
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).json()
    assert g["objects"][0]["sku"] == "BED-KNG-WLT-001"                    # designs now carry the catalogue SKU
    r = boq(client, h, rid, save(client, h, rid, g["objects"]))
    assert r.status_code == 201; b = r.json()
    assert b["totals"] == {"subtotal": "333720.00", "overhead": "26697.60", "margin": "64875.17", "pre_tax": "425292.77",
                           "discount": "21264.64", "after_discount": "404028.13", "gst": "72725.06", "grand_total": "476753.19"}
    bed, war = b["items"]
    assert (bed["description"], bed["rate"], bed["labour"], bed["total"]) == ("King Bed — Walnut", "124000.00", "9920.00", "133920.00")
    assert (war["rate"], war["labour"], war["total"]) == ("185000.00", "14800.00", "199800.00")
    assert b["quotation_no"].startswith("QT-IQ-B-") and b["quotation_no"].endswith("-01")

def test_identical_items_are_grouped_and_stock_is_checked(client):
    catalogue("TST-CHAIR", "Test Chair", 1000, stock=1); h = hdr(client); rid = room(client, h)
    b = boq(client, h, rid, save(client, h, rid, [obj(i, "Test Chair", "TST-CHAIR", 1000) for i in range(3)])).json()
    assert len(b["items"]) == 1 and b["items"][0]["qty"] == "3" and b["items"][0]["total"] == "3240.00"      # 3 x (1000 + 8% labour)
    assert any("3 needed but only 1 in stock" in w for w in b["warnings"])

def test_uses_current_catalogue_price_and_old_boqs_never_change(client):
    catalogue("TST-DRIFT", "Drift Chair", 500, stock=10); h = hdr(client); rid = room(client, h)
    v = save(client, h, rid, [obj(0, "Drift Chair", "TST-DRIFT", 500)])          # design saved while the price was 500
    catalogue("TST-DRIFT", "Drift Chair", 650, stock=10)
    b1 = boq(client, h, rid, v).json()
    assert b1["items"][0]["rate"] == "650.00" and any("500.00 -> 650.00" in w for w in b1["warnings"])
    catalogue("TST-DRIFT", "Drift Chair", 900, stock=10)
    b2 = boq(client, h, rid, v).json()
    assert (b1["version"], b2["version"]) == (1, 2) and b2["items"][0]["rate"] == "900.00"
    again = client.get(f"/api/boqs/{b1['id']}", headers=h).json()
    assert again["totals"] == b1["totals"] and again["items"] == b1["items"]    # v1 is a frozen snapshot
    assert [x["version"] for x in client.get(f"/api/rooms/{rid}/boqs", headers=h).json()] == [2, 1]

def test_only_valid_nonempty_designs_can_be_priced(client):
    catalogue("TST-CHAIR", "Test Chair", 1000, stock=9); h = hdr(client); rid = room(client, h)
    invalid = save(client, h, rid, [obj(0, "Test Chair", "TST-CHAIR", 1000, x=100), obj(1, "Test Chair", "TST-CHAIR", 1000, x=300)])   # overlapping
    assert boq(client, h, rid, invalid).status_code == 409 and "validation errors" in boq(client, h, rid, invalid).json()["detail"]
    assert boq(client, h, rid, save(client, h, rid, [])).status_code == 409
    assert boq(client, h, rid, 99).status_code == 404

def test_legacy_and_unknown_items(client):
    catalogue("TST-LEGACY", "Legacy Table", 2000, stock=5); h = hdr(client); rid = room(client, h)
    legacy = {k: v for k, v in obj(0, "Legacy Table", "", 1).items() if k != "sku"}            # saved before SKUs existed: matched by name, priced from the catalogue
    b = boq(client, h, rid, save(client, h, rid, [legacy, obj(1, "Custom Shelf", "", 750)])).json()
    by = {i["description"]: i for i in b["items"]}
    assert by["Legacy Table"]["sku"] == "TST-LEGACY" and by["Legacy Table"]["rate"] == "2000.00" and by["Legacy Table"]["flags"] == []
    assert by["Custom Shelf"]["flags"] == ["NOT_IN_CATALOGUE"] and by["Custom Shelf"]["rate"] == "750.00"
    assert any("Custom Shelf: not found in the catalogue" in w for w in b["warnings"])
    free = save(client, h, rid, [obj(0, "Mystery Item", "", 0)])                                # no price anywhere: refuse to quote it as free
    r = boq(client, h, rid, free); assert r.status_code == 409 and "Mystery Item" in r.json()["detail"]

def test_rate_overrides_are_applied_exactly_and_bounded(client):
    catalogue("TST-CHAIR", "Test Chair", 1000, stock=9); h = hdr(client); rid = room(client, h); v = save(client, h, rid, [obj(0, "Test Chair", "TST-CHAIR", 1000)])
    base = boq(client, h, rid, v).json(); no_lab = boq(client, h, rid, v, labour_pct=0).json(); freight = boq(client, h, rid, v, transport=5000).json()
    assert no_lab["items"][0]["total"] == "1000.00" and no_lab["params"]["labour_pct"] == "0"
    assert D(freight["totals"]["subtotal"]) - D(base["totals"]["subtotal"]) == D("5000.00")
    assert freight["items"][-1]["category"] == "Transport" and freight["items"][-1]["total"] == "5000.00"
    for bad in ({"gst_pct": 150}, {"transport": -1}, {"labour_pct": -5}, {"margin_pct": "abc"}, {"installation": 10**9}):
        assert boq(client, h, rid, v, **bad).status_code == 422, bad

def test_defaults_endpoint(client):
    assert client.get("/api/estimation/defaults", headers=hdr(client)).json()["gst_pct"] == "18"

def test_access_control(client):
    catalogue("TST-CHAIR", "Test Chair", 1000, stock=9); h = hdr(client); rid = room(client, h); v = save(client, h, rid, [obj(0, "Test Chair", "TST-CHAIR", 1000)])
    b = boq(client, h, rid, v).json()
    for who in ("client@test.com", "amit@interioriq.com"):                                      # client and site engineer: no commercial data
        hh = hdr(client, who)
        assert boq(client, hh, rid, v).status_code == 403 and client.get(f"/api/boqs/{b['id']}", headers=hh).status_code == 403
        assert client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=hh).status_code == 403
    assert client.get(f"/api/boqs/{b['id']}").status_code == 401 and client.get("/api/boqs/nope", headers=h).status_code == 404

# ── the PDF ──────────────────────────────────────────────────────────────────
def test_quotation_pdf_contains_the_real_numbers(client):
    h = hdr(client); rid = room(client, h, number="IQ T/1")
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).json(); b = boq(client, h, rid, save(client, h, rid, g["objects"])).json()
    r = client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert 'filename="QT-IQ-T-1-01.pdf"' in r.headers["content-disposition"]                   # hostile characters in the project number are neutralised
    text = pdf_text(r.content)
    for needle in ("QUOTATION", b["quotation_no"], "King Bed", "6-Door Wardrobe", "BED-KNG-WLT-001", "4,76,753.19", "Grand total", "Payment schedule", "Terms and conditions", "Valid until"):
        assert needle in text, needle
    for share in split_payments("476753.19", [30, 20, 25, 20, 5]): assert inr(share) in text, share   # every payment instalment is printed

def test_pdf_survives_non_latin_names_and_long_lists(client):
    catalogue("TST-GUJ", "Sofa — ગુજરાતી", 1000, stock=5, category="Sofa"); h = hdr(client); rid = room(client, h)
    many = [obj(i, f"Part {i:02d}", "", 100, x=100 + (i % 20) * 200, y=100 + (i // 20) * 200) for i in range(60)]
    for o in many: o.update(length=100, width=100)
    b = boq(client, h, rid, save(client, h, rid, many)).json(); assert len(b["items"]) == 60
    r = client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h); assert r.status_code == 200
    doc = pdfium.PdfDocument(r.content); assert len(doc) >= 2 and "Page 2" in pdf_text(r.content)
    rid2 = room(client, h); b2 = boq(client, h, rid2, save(client, h, rid2, [obj(0, "Sofa — ગુજરાતી", "TST-GUJ", 1000, category="Sofa")])).json()
    assert client.get(f"/api/boqs/{b2['id']}/quotation.pdf", headers=h).status_code == 200      # unsupported glyphs degrade to '?', they don't crash

def test_pdf_for_unknown_boq_is_404(client): assert client.get("/api/boqs/nope/quotation.pdf", headers=hdr(client)).status_code == 404

# ── money helpers ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,s", [(0, "0.00"), (999, "999.00"), (1000, "1,000.00"), (100000, "1,00,000.00"), ("1234567.5", "12,34,567.50"), (12345678.9, "1,23,45,678.90"),
                                 ("476753.19", "4,76,753.19"), (-1234567.891, "-12,34,567.89"), ("0.005", "0.01")])
def test_inr_indian_grouping(v, s): assert inr(v) == s

def test_payment_split_always_sums_exactly():
    rng = random.Random(7)
    for _ in range(500):
        total = D(rng.randint(1, 10**10)) / 100
        for pcts in ([30, 20, 25, 20, 5], [33.33, 33.33, 33.34], [100], [50, 50]):
            parts = split_payments(total, pcts); assert sum(parts) == total and all(p >= 0 for p in parts) and len(parts) == len(pcts)

def test_payment_split_rejects_bad_percentages():
    for bad in ([30, 20], [60, 50], [0]):
        with pytest.raises(ValueError): split_payments(1000, bad)
