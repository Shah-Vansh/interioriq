"""M21 multi-room design generation: bedroom, living, dining, kitchen and study layouts from the catalogue — valid by the same validator
the 3D editor uses, doors kept clear, working zones in front of units, options (skip items, kitchen shape, seats), missing categories
reported (never invented), unsupported rooms refused, and the generated designs flow into BOQ + electrical drawings."""
import itertools

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.main import SEED_FURNITURE, app
from app.services import layouts
from app.services.geometry import Room, door_zones, validate

CAT = [dict(sku=s, name=n, category=c, length_mm=l, width_mm=w, height_mm=h, price=p, style=(more + [None])[0], mount_mm=(more + [None, None])[1]) for s, n, c, l, w, h, p, _, *more in SEED_FURNITURE]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def room(c, h, rtype, L, W, H=2900, doors=()):
    _n[0] += 1
    pid = c.post("/api/projects", json={"project_number": f"IQ-LAY-{_n[0]}-{rtype}", "name": "Layouts"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": rtype.title(), "room_type": rtype}, headers=h).json()["id"]
    for lbl, v in (("Length", L), ("Width", W), ("Ceiling Height", H)):
        c.put(f"/api/rooms/{rid}/measurements", json={"label": lbl, "value": v, "source": "USER_VERIFIED"}, headers=h)
    for d in doors:
        assert c.post(f"/api/rooms/{rid}/openings", json={"kind": "DOOR", "width_mm": 900, "height_mm": 2100} | d, headers=h).status_code == 201
    return rid


def gen(c, h, rid, **body):
    return c.post(f"/api/rooms/{rid}/designs/generate", json=body, headers=h)


def door(wall, off, w=900): return {"kind": "DOOR", "wall": wall, "offset": off, "width": w, "height": 2100, "sill": 0, "swing": "INWARD_LEFT", "label": "Door 1"}
def rect(o): return box(o.x, o.y, o.x + o.length, o.y + o.width)


@pytest.mark.parametrize("rtype,L,W,need", [
    ("LIVING", 5200, 4000, {"Sofa", "TV Unit", "Coffee Table"}), ("DINING", 4000, 3200, {"Dining Table", "Dining Chair"}),
    ("KITCHEN", 3000, 2400, {"Kitchen"}), ("STUDY", 3000, 2700, {"Study", "Office Chair"}), ("MASTER_BEDROOM", 4250, 3600, {"Bed", "Wardrobe"})])
def test_every_room_type_gets_a_valid_layout(client, rtype, L, W, need):
    h = hdr(client); rid = room(client, h, rtype, L, W, doors=[{"wall": "S", "offset_mm": 200}])
    g = gen(client, h, rid).json()
    assert g["validation"]["valid"], g["validation"]["errors"]
    assert need <= {o["category"] for o in g["objects"]} and g["notes"] and g["kind"] == layouts.kind_of(rtype)
    assert client.post(f"/api/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=h).json()["is_valid"] is True   # saved design re-validated by the server


def test_default_bedroom_is_unchanged():
    out = layouts.plan(Room(4250, 3600, 2750), "BEDROOM", CAT)
    assert [(o.id, o.x, o.y, o.length, o.width) for o in out["objects"]] == [("bed", 1160, 1520, 1930, 2030), ("wardrobe", 50, 50, 2700, 600)]


def test_small_bedroom_slides_the_bed_and_explains_the_missing_wardrobe():
    r = Room(3000, 2800, 2750, openings=[door("S", 100)]); out = layouts.plan(r, "BEDROOM", CAT)
    assert [o.name for o in out["objects"]] == ["Queen Bed — Oak", "2-Door Wardrobe — Oak"] and validate(r, out["objects"])["valid"]   # king + any wardrobe won't fit: queen + compact does
    no_compact = [c for c in CAT if c["sku"] != "WAR-2D-OAK-001"]
    out = layouts.plan(r, "BEDROOM", no_compact)
    assert [o.category for o in out["objects"]] == ["Bed"] and any("Wardrobe left out" in n for n in out["notes"])


def test_living_sofa_faces_the_tv_at_viewing_distance():
    r = Room(5200, 4000, 2900, openings=[door("S", 300)]); out = layouts.plan(r, "LIVING", CAT); o = {x.id: x for x in out["objects"]}
    sofa, tv, table = o["sofa"], o["tv"], o["coffee"]
    assert sofa.y > tv.y and sofa.y - (tv.y + tv.width) >= layouts.VIEW_MIN                       # opposite walls, ≥ 1.5 m apart
    assert abs((sofa.x + sofa.length / 2) - (tv.x + tv.length / 2)) < 1                           # centred on each other
    assert sofa.y - (table.y + table.width) == 400 and table.y - (tv.y + tv.width) >= 600          # 400 mm leg room, 600 mm walkway to the TV
    small = layouts.plan(Room(3600, 3000), "LIVING", CAT)
    assert "coffee" not in {x.id for x in small["objects"]} and any("Coffee table left out" in n for n in small["notes"])


def test_dining_chairs_seat_around_the_table_with_pull_out_space():
    r = Room(4000, 3200); out = layouts.plan(r, "DINING", CAT); objs = out["objects"]
    t = next(o for o in objs if o.category == "Dining Table"); chairs = [o for o in objs if o.category == "Dining Chair"]
    assert t.length == 1800 and len(chairs) == 6
    for ch in chairs:
        assert rect(ch).touches(rect(t)) and not rect(ch).overlaps(rect(t))                          # pulled up to the table edge
        assert ch.y - 400 >= 0 and ch.y + ch.width + 400 <= r.width                                  # 400 mm behind every chair
    four = layouts.plan(r, "DINING", CAT, {"seats": 4})["objects"]
    assert sum(o.category == "Dining Chair" for o in four) == 4 and next(o for o in four if o.category == "Dining Table").length == 1200   # smallest table that seats 4
    tight = layouts.plan(Room(2600, 2400), "DINING", CAT)
    assert any("Only 3 of the table's 6 seats" in n for n in tight["notes"])


def test_kitchen_runs_keep_the_door_and_a_working_aisle_clear():
    r = Room(3600, 3000, 2900, openings=[door("S", 2500)]); out = layouts.plan(r, "KITCHEN", CAT); objs = out["objects"]
    assert validate(r, objs)["valid"] and "U-shaped" in out["notes"][0]
    zone = door_zones(r)[0][1]
    assert all(not rect(o).intersects(zone) or rect(o).intersection(zone).area == 0 for o in objs)
    south = [o for o in objs if o.y < 100 and o.height < 1800]; north = [o for o in objs if o.y + o.width > r.width - 100]
    assert south and north and min(n.y for n in north) - max(s.y + s.width for s in south) >= 1000           # aisle between opposite runs
    assert sum(o.height >= 1800 for o in objs) == 1                                                           # one tall unit
    straight = layouts.plan(r, "KITCHEN", CAT, {"kitchen_shape": "STRAIGHT", "skip": ["tall"]})
    assert "Straight" in straight["notes"][0] and all(o.height < 1000 for o in straight["objects"])           # no tall unit (skipped)
    floor = [o for o in straight["objects"] if not o.z]
    assert len({o.y for o in floor}) == 1 or len({o.x for o in floor}) == 1                                # one counter run on one wall
    tiny = layouts.plan(Room(2000, 1900, openings=[door("S", 500)]), "KITCHEN", CAT, {"kitchen_shape": "PARALLEL"})
    assert tiny["objects"] == [] and "parallel kitchen doesn't fit" in tiny["notes"][0]
    with pytest.raises(layouts.LayoutError): layouts.plan(r, "KITCHEN", CAT, {"kitchen_shape": "Z"})


def test_study_desk_by_the_window_with_its_chair():
    r = Room(3000, 2700, 2900, openings=[door("S", 2000), {"kind": "WINDOW", "wall": "E", "offset": 800, "width": 1200, "height": 1200, "sill": 900, "swing": None, "label": "Window 1"}])
    o = {x.category: x for x in layouts.plan(r, "STUDY", CAT)["objects"]}
    assert o["Study"].x + o["Study"].length == 2950 and rect(o["Office Chair"]).touches(rect(o["Study"]))


def test_missing_categories_are_reported_never_invented():
    no_tv = [c for c in CAT if c["category"] != "TV Unit"]
    out = layouts.plan(Room(5200, 4000), "LIVING", no_tv, all_items=CAT)
    assert {m["label"]: (m["required"], m["out_of_stock"]) for m in out["missing"]}["TV unit"] == (True, True)   # exists, but out of stock
    assert "TV Unit" not in {o.category for o in out["objects"]} and "Sofa" in {o.category for o in out["objects"]}
    out = layouts.plan(Room(3000, 2400), "KITCHEN", [c for c in CAT if c["category"] != "Kitchen"], all_items=[])
    assert out["objects"] == [] and out["missing"][0]["label"] == "Kitchen base unit" and out["missing"][0]["out_of_stock"] is False


def test_never_crashes_and_never_returns_an_invalid_layout_except_the_explained_bedroom_fallback():
    for kind, (L, W), (wall, off) in itertools.product(("LIVING", "DINING", "KITCHEN", "STUDY", "BEDROOM"), ((1800, 1600), (2400, 2100), (3300, 2900), (4600, 3700)),
                                                       (("S", 100), ("N", 600), ("E", 200), ("W", 900))):
        if off + 900 > (L if wall in "NS" else W): continue
        r = Room(L, W, 2900, openings=[door(wall, off)]); out = layouts.plan(r, kind, CAT)
        v = validate(r, out["objects"])
        assert v["valid"] or any("showing the preferred" in n for n in out["notes"]), (kind, L, W, wall, off, v["errors"])


def test_api_options_unsupported_rooms_and_overrides(client):
    h = hdr(client)
    bath = room(client, h, "OTHER", 2400, 1800)                     # (bathrooms are laid out since M32 — an 'other' room still needs a type)
    r = gen(client, h, bath); assert r.status_code == 422 and "bathroom and utility" in r.json()["detail"]
    assert gen(client, h, bath, room_type="STUDY").json()["kind"] == "STUDY"                                    # lay it out as another type
    liv = room(client, h, "LIVING", 5200, 4000)
    assert "Coffee Table" not in {o["category"] for o in gen(client, h, liv, options={"skip": ["coffee"]}).json()["objects"]}
    assert gen(client, h, liv, options={"skip": ["pool"]}).status_code == 422
    assert gen(client, h, liv, options={"seats": 40}).status_code == 422
    assert gen(client, h, liv, options={"colour": "red"}).status_code == 422                                    # unknown option
    meta = client.get("/api/layouts/meta", headers=h).json()
    assert meta["room_kind"]["MASTER_BEDROOM"] == "BEDROOM" and "U" in meta["kitchen_shapes"] and {o["slot"] for o in meta["optional"]["LIVING"]} == {"coffee", "armchair", "bookshelf"}


def test_generated_kitchen_prices_and_wires_up(client):
    h = hdr(client); rid = room(client, h, "KITCHEN", 3600, 3000, doors=[{"wall": "S", "offset_mm": 2500}])
    g = gen(client, h, rid).json(); v = client.post(f"/api/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=h).json()["version"]
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    lines = {i["description"]: i["qty"] for i in b["items"]}
    n900 = sum(o["sku"] == "KBU-900-001" for o in g["objects"])
    assert n900 >= 2 and lines["Kitchen Base Unit 900"] == str(n900)                                            # modules grouped with quantities
    el = client.get(f"/api/rooms/{rid}/drawings/electrical", headers=h).json()
    labels = [p["label"] for p in el["points"]]
    assert "Chimney point (6A) above the hob" in labels and any("fridge" in x for x in labels) and not any(p["type"] == "AC" for p in el["points"])


def _aisles(out, r):
    """Gap between the fronts of counter runs on opposite walls (S↔N and W↔E)."""
    by = lambda w: [o for o in out["objects"] if out["walls"].get(o.id) == w]
    res = []
    if by("S") and by("N"): res.append(min(o.y for o in by("N")) - max(o.y + o.width for o in by("S")))
    if by("W") and by("E"): res.append(min(o.x for o in by("E")) - max(o.x + o.length for o in by("W")))
    return res


@pytest.mark.parametrize("L,W,shape", [(3600, 2000, "AUTO"), (3600, 2000, "PARALLEL"), (2600, 2300, "U"), (3000, 2200, "AUTO")])
def test_kitchen_never_squeezes_the_working_aisle(L, W, shape):
    r = Room(L, W); out = layouts.plan(r, "KITCHEN", CAT, {"kitchen_shape": shape})
    assert out["objects"] and all(a >= 1000 for a in _aisles(out, r)), (_aisles(out, r), out["notes"])


def test_narrow_living_room_turns_the_sofa_to_keep_viewing_distance():
    r = Room(4000, 2700); o = {x.id: x for x in layouts.plan(r, "LIVING", CAT)["objects"]}
    assert o["sofa"].length == 900 and layouts.distance(o["sofa"], o["tv"], "W" if o["sofa"].x < 100 else "E") >= layouts.VIEW_MIN
