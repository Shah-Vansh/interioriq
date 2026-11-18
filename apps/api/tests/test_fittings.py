"""M21b: units fixed above the floor (z) — stacking, windows, ceiling, floor space; kitchen sink / hob / wall cabinets / fillers / work
triangle; item choice by style and tier; fitting a budget by swapping to cheaper items and dropping extras; catalogue mount height + style."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.main import SEED_FURNITURE, app
from app.services import layouts, mep, takeoff
from app.services.cost_engine import Line, compute
from app.services.geometry import Obj, Room, validate

CAT = [dict(sku=s, name=n, category=c, length_mm=l, width_mm=w, height_mm=h, price=p, style=(more + [None])[0], mount_mm=(more + [None, None])[1])
       for s, n, c, l, w, h, p, _, *more in SEED_FURNITURE]
grand = lambda objs: compute([Line(Decimal(1), Decimal(str(o.price))) for o in objs])["grand_total"]
door = lambda wall, off: {"kind": "DOOR", "wall": wall, "offset": off, "width": 900, "height": 2100, "sill": 0, "swing": "INWARD_LEFT", "label": "Door 1"}
window = lambda wall, off, w=1200: {"kind": "WINDOW", "wall": wall, "offset": off, "width": w, "height": 1200, "sill": 900, "swing": None, "label": "Window 1"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


# ── z: fixed above the floor ──────────────────────────────────────────────────
def test_wall_cabinet_over_a_base_unit_is_not_a_collision_but_two_at_the_same_height_are():
    r = Room(3000, 2500, 2700)
    base = Obj("b", "Base", "Kitchen", 50, 50, 900, 600, 850)
    wall = Obj("w", "Wall cabinet", "Kitchen Wall", 50, 50, 900, 350, 700, z=1450)
    assert validate(r, [base, wall])["valid"]
    low = Obj("w", "Wall cabinet", "Kitchen Wall", 50, 50, 900, 350, 700, z=800)                    # overlaps the base unit's height
    assert "Collision" in validate(r, [base, low])["errors"][0]
    assert "taller than ceiling (2150 > 2000mm)" in validate(Room(3000, 2500, 2000), [wall])["errors"][0]
    assert validate(r, [wall])["occupancy"] == 0                                                     # takes no floor space


def test_window_and_door_rules_use_the_real_height():
    r = Room(3000, 2500, 2700, openings=[window("S", 1000), door("N", 1000)])
    under = Obj("b", "Base", "Kitchen", 1000, 50, 900, 600, 850)                                      # under the 900 sill
    over = Obj("w", "Wall cabinet", "Kitchen Wall", 1000, 50, 900, 350, 700, z=1450)                   # across the window (900–2100)
    above = Obj("w2", "Loft", "Storage", 1000, 50, 900, 350, 400, z=2150)                             # above the window head
    v = validate(r, [under, over, above]); assert v["valid"] and len(v["warnings"]) == 1 and "fixed across it, 1450–2150 mm" in v["warnings"][0]
    loft = Obj("l", "Loft over the door", "Storage", 1000, 2050, 900, 400, 300, z=2200)                # above the door head: not blocking
    assert validate(r, [loft])["valid"]
    assert not validate(r, [Obj("t", "Tall", "Storage", 1000, 2050, 900, 400, 1800)])["valid"]        # standing in the doorway


def test_drawings_and_takeoff_respect_mount_height():
    objs = [dict(id="w", name="Wall cabinet", category="Kitchen Wall", x=50, y=1900, length=900, width=350, height=700, z=1450)]
    el = next(w for w in mep.elevations(3000, 2250, 2700, objs) if w["wall"] == "NORTH")
    assert el["items"][0]["z"] == 1450
    q, bare = takeoff.quantities(3000, 2250, 2700, objs, []), takeoff.quantities(3000, 2250, 2700, [], [])
    assert float(bare["WALL_PAINT"]["qty"]) - float(q["WALL_PAINT"]["qty"]) == pytest.approx(0.63 + 0.245, abs=0.01)     # hides 900 × 700 front + its 350 × 700 sides (take-off rule)
    assert bare["SKIRTING"]["qty"] == q["SKIRTING"]["qty"]                                                    # but no skirting: it doesn't reach the floor


# ── kitchen fittings ──────────────────────────────────────────────────────────
def kitchen(L=3600, W=3000, ops=None, **opts):
    r = Room(L, W, 2900, openings=ops if ops is not None else [door("S", 2500), window("N", 1000)])
    return r, layouts.plan(r, "KITCHEN", CAT, opts)


def test_sink_under_the_window_hob_away_from_it_with_counter_both_sides():
    r, out = kitchen(); o = out["objects"]
    sink = next(x for x in o if x.category == "Kitchen Sink"); hob = next(x for x in o if x.category == "Kitchen Hob")
    assert sink.y + sink.width > r.width - 100 and 1000 - 900 < sink.x + sink.length and sink.x < 2200       # north run, under the window (1000–2200)
    assert not (hob.y + hob.width > r.width - 100 and hob.x < 2200 and hob.x + hob.length > 1000)            # not under the window
    rect = lambda a: box(a.x, a.y, a.x + a.length, a.y + a.width)
    assert rect(hob).distance(rect(sink)) > 1                                                                 # never side by side
    assert sum(rect(hob).distance(rect(x)) < 1 for x in o if x.id != hob.id and not x.z) >= 2                 # counter on both sides
    assert any("Work triangle" in n for n in out["notes"]) and validate(r, o)["valid"]


def test_wall_cabinets_hang_over_the_counter_not_the_hob_or_the_window():
    r, out = kitchen(); o = out["objects"]
    walls = [x for x in o if x.category == "Kitchen Wall"]; hob = next(x for x in o if x.category == "Kitchen Hob")
    assert walls and all(x.z == 1450 and x.width == 350 or x.length == 350 for x in walls)
    rect = lambda a: box(a.x, a.y, a.x + a.length, a.y + a.width)
    assert not any(rect(w).intersection(rect(hob)).area > 0 for w in walls)                                   # chimney over the hob
    assert not any(w.y + w.width > r.width - 100 and w.x < 2200 and w.x + w.length > 1000 for w in walls)    # nothing across the window
    assert any("none in front of the window" in n and "none above the hob" in n for n in out["notes"])


def test_filler_panels_close_corner_and_end_gaps_only():
    r, out = kitchen(); fills = [x for x in out["objects"] if x.category == "Kitchen Filler"]
    assert fills and all(20 <= max(min(f.length, f.width), 0) <= layouts.FILLER_MAX for f in fills) and validate(r, out["objects"])["valid"]
    assert all("mm)" in f.name and f.sku == "KFP-001" for f in fills)
    _, none = kitchen(skip=["filler"]); assert not any(x.category == "Kitchen Filler" for x in none["objects"])
    no_item = [c for c in CAT if c["category"] != "Kitchen Filler"]
    out2 = layouts.plan(r, "KITCHEN", no_item); assert not any(x.category == "Kitchen Filler" for x in out2["objects"])
    assert any(m["label"] == "Filler panel" for m in out2["missing"])                                        # reported, not invented


def test_kitchen_electrical_follows_the_fittings(client):
    _, out = kitchen(); objs = [o.__dict__ for o in out["objects"]]
    e = mep.electrical(3600, 3000, 2900, objs, [door("S", 2500)]); labels = [p["label"] for p in e["points"]]
    hob = next(o for o in objs if o["category"] == "Kitchen Hob")
    chim = next(p for p in e["points"] if p["label"].startswith("Chimney"))
    assert labels.count("Chimney point (6A) above the hob") == 1 and abs(chim["x"] - (hob["x"] + hob["length"] / 2)) < 1   # over the actual hob
    assert "6A socket under the sink (RO / dishwasher)" in labels and "16A hob point (induction)" in labels
    assert labels.count("Under-cabinet LED strip") == sum(o["category"] == "Kitchen Wall" for o in objs) and not any(p["type"] == "AC" for p in e["points"])


# ── style, tier, budget ──────────────────────────────────────────────────────
def test_style_from_the_brief_picks_matching_items():
    r = Room(5200, 4000, 2900)
    plain = {o.id: o.sku for o in layouts.plan(r, "LIVING", CAT)["objects"]}
    assert plain["sofa"] == "SOF-3S-GRY-001" and plain["tv"] == "TVU-WLT-001"                     # balanced: largest that fits
    out = layouts.plan(r, "LIVING", CAT, styles=["luxury"]); o = {x.id: x.sku for x in out["objects"]}
    assert o["sofa"] == "SOF-3S-LTH-001" and any("Style 'luxury'" in n for n in out["notes"])
    scandi = {x.id: x.sku for x in layouts.plan(r, "LIVING", CAT, styles=["scandinavian"])["objects"]}
    assert scandi["tv"] == "TVU-OAK-001" and scandi["sofa"] == "SOF-3S-GRY-001"


def test_tiers_order_by_price():
    r = Room(5200, 4000, 2900)
    assert {x.id: x.sku for x in layouts.plan(r, "LIVING", CAT, {"tier": "PREMIUM"})["objects"]}["sofa"] == "SOF-3S-LTH-001"
    cheap = {x.id: x.sku for x in layouts.plan(r, "LIVING", CAT, {"tier": "BUDGET"})["objects"]}
    assert cheap["sofa"] == "SOF-2S-GRY-001" and cheap["tv"] == "TVU-OAK-001"
    with pytest.raises(layouts.LayoutError): layouts.plan(r, "LIVING", CAT, {"tier": "CHEAP"})


def test_budget_swaps_to_cheaper_items_then_drops_extras_and_says_so():
    r = Room(4250, 3600, 2900)
    full = layouts.plan(r, "BEDROOM", CAT); total = grand(full["objects"])
    out = layouts.plan(r, "BEDROOM", CAT, budget=Decimal("200000"), cost=grand)
    names = [o.name for o in out["objects"]]
    assert grand(out["objects"]) <= 200000 < total and names == ["Queen Bed — Oak", "2-Door Wardrobe — Oak"]
    assert any(n.startswith("To fit the ₹2,00,000.00 budget: ") and "King Bed — Walnut → Queen Bed — Oak" in n for n in out["notes"])
    assert validate(r, out["objects"])["valid"]
    tight = layouts.plan(r, "BEDROOM", CAT, budget=Decimal("50000"), cost=grand)
    assert any(n.startswith("Still ₹") and "over the ₹50,000.00 budget" in n for n in tight["notes"]) and len(tight["objects"]) == 2   # beds/wardrobes are never dropped
    liv = layouts.plan(Room(5200, 4000, 2900), "LIVING", CAT, styles=["luxury"], budget=Decimal("200000"), cost=grand)
    assert grand(liv["objects"]) <= 200000 and any("Left out to stay within budget" in n or "To fit" in n for n in liv["notes"])


def test_generate_api_uses_brief_style_budget_and_tier(client):
    h = hdr(client)
    pid = client.post("/api/projects", json={"project_number": "IQ-FIT-1", "name": "Fittings"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Living", "room_type": "LIVING"}, headers=h).json()["id"]
    for lbl, v in (("Length", 5200), ("Width", 4000), ("Ceiling Height", 2900)):
        client.put(f"/api/rooms/{rid}/measurements", json={"label": lbl, "value": v, "source": "USER_VERIFIED"}, headers=h)
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={"prompt": "luxury living room"}, headers=h).json()
    assert g["requirements"]["styles"] == ["luxury"] and "Leather" in next(o["name"] for o in g["objects"] if o["category"] == "Sofa")
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={"prompt": "living room under 2 lakh"}, headers=h).json()
    assert Decimal(g["cost"]["grand_total"]) <= 200000 and g["over_budget"] is False and g["budget_gap"]
    assert client.post(f"/api/rooms/{rid}/designs/generate", json={"options": {"tier": "BUDGET"}}, headers=h).status_code == 200
    assert client.post(f"/api/rooms/{rid}/designs/generate", json={"options": {"tier": "x"}}, headers=h).status_code == 422
    meta = client.get("/api/layouts/meta", headers=h).json(); assert meta["tiers"] == ["BUDGET", "BALANCED", "PREMIUM"] and "luxury" in meta["styles"]
    # a saved design keeps z; a wall cabinet over a base unit validates on the server
    objs = [dict(id="b", name="Base", category="Kitchen", x=50, y=50, length=900, width=600, height=850),
            dict(id="w", name="Wall cabinet", category="Kitchen Wall", x=50, y=50, length=900, width=350, height=700, z=1450)]
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()
    assert v["is_valid"] is True and client.get(f"/api/rooms/{rid}/designs/{v['version']}", headers=h).json()["objects"][1]["z"] == 1450
    assert client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [dict(objs[1], z=-5)]}, headers=h).status_code == 422


def test_catalogue_mount_height_and_style_tags(client):
    h = hdr(client)
    r = client.post("/api/catalogue/items", json={"sku": "FIT-WC-1", "name": "Wall cabinet test", "category": "Kitchen Wall", "price": "9000",
                                                  "length_mm": 600, "width_mm": 350, "height_mm": 700, "mount_mm": 1500, "style": "Modern, minimal;  modern"}, headers=h)
    assert r.status_code == 201, r.text
    it = r.json(); assert it["mount_mm"] == 1500 and it["style"] == "modern, minimal"
    assert client.patch(f"/api/catalogue/items/{it['id']}", json={"style": "luxury!"}, headers=h).status_code == 422
    assert client.patch(f"/api/catalogue/items/{it['id']}", json={"mount_mm": 4000}, headers=h).status_code == 422
    f = next(x for x in client.get("/api/catalogue/furniture", headers=h).json() if x["sku"] == "FIT-WC-1"); assert f["mount_mm"] == 1500
    csv = client.get("/api/catalogue/export.csv", headers=h)
    if csv.status_code == 200: assert "mount_mm,style" in csv.text.splitlines()[0]
