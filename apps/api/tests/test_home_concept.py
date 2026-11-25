"""M37 whole home + M38 design concept: rooms placed on one home plan (auto-arrange keeps a wall between rooms, overlaps reported, house DXF);
new room types lay out (verandah, foyer, pooja, store, wash area); 'Design my home' lays out missing rooms and applies one style to every
room as a NEW version (feature wall behind the bed / on the TV wall, ceiling by room size, curtains per window, rug, art, plants, pendants);
edits are validated; saving from the editor keeps the concept; the concept feeds take-off quantities."""
import io
import time

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import concept, takeoff

RUN = str(int(time.time()))[-6:]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


def home(c, h, n):
    pid = c.post("/api/projects", json={"project_number": f"IQ-HOME-{n}", "name": "Raw flat"}, headers=h).json()["id"]
    rooms = {}
    for name, rt, L, W, ops in (("Master bedroom", "MASTER_BEDROOM", 4250, 3600, [("DOOR", "S", 300), ("WINDOW", "E", 1200)]),
                                ("Living", "LIVING", 5200, 4000, [("DOOR", "S", 300), ("WINDOW", "W", 1000)]),
                                ("Kitchen", "KITCHEN", 3600, 3000, [("DOOR", "S", 2500)]), ("Bath", "BATHROOM", 2400, 1800, [("DOOR", "S", 1400)]),
                                ("Verandah", "VERANDAH", 3500, 1800, [("DOOR", "S", 100)]), ("Foyer", "FOYER", 1800, 1500, [("DOOR", "S", 100)]),
                                ("Pooja", "POOJA", 1500, 1200, [("DOOR", "S", 100)]), ("Wash area", "WASH_AREA", 2400, 1500, [("DOOR", "S", 100)])):
        rid = c.post(f"/api/projects/{pid}/rooms", json={"name": name, "room_type": rt}, headers=h).json()["id"]
        for l, v in (("Length", L), ("Width", W), ("Ceiling Height", 2900)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
        for kind, wall, off in ops:
            body = {"kind": kind, "wall": wall, "offset_mm": off, "width_mm": 900 if kind == "DOOR" else 1400, "height_mm": 2100 if kind == "DOOR" else 1300}
            if kind == "WINDOW": body["sill_mm"] = 800
            else: body["swing"] = "OUTWARD"
            c.post(f"/api/rooms/{rid}/openings", json=body, headers=h).raise_for_status()
        rooms[name] = rid
    return pid, rooms


def test_home_plan_arrange_overlaps_and_dxf(client):
    h = hdr(client); pid, rooms = home(client, h, RUN + "1")
    p = client.get(f"/api/projects/{pid}/home-plan", headers=h).json()
    assert len(p["rooms"]) == 8 and not any(r["placed"] for r in p["rooms"]) and "VERANDAH" in p["room_types"]
    assert client.get(f"/api/projects/{pid}/home-plan.dxf", headers=h).status_code == 409
    p = client.post(f"/api/projects/{pid}/home-plan/auto", json={}, headers=h).json()
    assert all(r["placed"] for r in p["rooms"]) and p["warnings"] == []
    zone = {r["name"]: r["y"] for r in p["rooms"]}
    assert zone["Verandah"] <= zone["Living"] <= zone["Master bedroom"]                          # front of the house → back
    bed = next(r for r in p["rooms"] if r["name"] == "Master bedroom")
    liv = next(r for r in p["rooms"] if r["name"] == "Living")
    p = client.put(f"/api/projects/{pid}/home-plan", json={"rooms": [{"id": bed["id"], "x": liv["x"] + 100, "y": liv["y"] + 100}]}, headers=h).json()
    assert any("overlaps" in w for w in p["warnings"])
    client.post(f"/api/projects/{pid}/home-plan/auto", json={"all_rooms": True}, headers=h)
    d = client.get(f"/api/projects/{pid}/home-plan.dxf", headers=h)
    doc = ezdxf.read(io.StringIO(d.content.decode()))
    assert d.status_code == 200 and len(doc.modelspace().query("INSERT")) == 8 and "ROOM_1" in [b.name for b in doc.blocks]


def test_design_my_home_applies_one_style_everywhere(client):
    h = hdr(client); pid, rooms = home(client, h, RUN + "2")
    assert client.post(f"/api/projects/{pid}/concept", json={"style": "gothic"}, headers=h).status_code == 422
    r = client.post(f"/api/projects/{pid}/concept", json={"style": "modern"}, headers=h).json()
    names = {x["room"] for x in r["rooms"]}
    assert {"Master bedroom", "Living", "Kitchen", "Bath", "Verandah", "Foyer", "Pooja", "Wash area"} <= names, r["skipped"]
    c = client.get(f"/api/projects/{pid}/concept", headers=h).json()
    assert c["style"] == "modern"
    f = {x["room"]: x["finishes"] for x in c["rooms"]}
    bed = client.get(f"/api/rooms/{rooms['Master bedroom']}/designs/latest", headers=h).json()
    b = next(o for o in bed["objects"] if o["category"] == "Bed")
    assert f["Master bedroom"]["accent"]["type"] == "FLUTED_WOOD" and f["Master bedroom"]["accent"]["wall"] == concept._against(b, 4250, 3600)
    assert f["Master bedroom"]["curtains"] and f["Master bedroom"]["curtains"][0]["wall"] == "E" and f["Master bedroom"]["rug"]
    assert f["Living"]["ceiling"]["type"] == "ISLAND" and f["Bath"]["ceiling"]["type"] == "GRID" and f["Bath"]["floor"]["kind"] == "TILE"
    assert f["Pooja"]["accent"]["type"] == "JAALI" and f["Kitchen"]["accent"]["height"] == 600
    # take-off now carries the concept
    q = takeoff.quantities(4250, 3600, 2900, bed["objects"], [], f["Master bedroom"])
    assert q["ACCENT_FLUTED_WOOD"]["qty"] > 0 and q["FLOOR_WOOD"]["qty"] > 0 and q["FLOORING"]["qty"] == 0 and q["RUG"]["qty"] == 1
    plain = takeoff.quantities(4250, 3600, 2900, bed["objects"], [])
    assert q["WALL_PAINT"]["qty"] < plain["WALL_PAINT"]["qty"]


def test_edit_concept_and_editor_keeps_it(client):
    h = hdr(client); pid, rooms = home(client, h, RUN + "3")
    rid = rooms["Living"]
    assert client.post(f"/api/rooms/{rid}/concept", json={"style": "luxury"}, headers=h).status_code == 409        # no layout yet
    client.post(f"/api/projects/{pid}/concept", json={"style": "scandinavian"}, headers=h)
    e = client.put(f"/api/rooms/{rid}/concept", json={"overrides": {"accent_type": "STONE", "wall_colour": "#eeeeee", "rug": False, "ceiling": "COVE"}}, headers=h)
    assert e.status_code == 200
    fin = e.json()["finishes"]
    assert fin["accent"]["type"] == "STONE" and fin["walls"]["colour"] == "#eeeeee" and fin["rug"] is None and fin["ceiling"]["type"] == "COVE" and fin["ceiling"]["cove_rm"] > 0
    for bad in ({"accent_type": "GOLD"}, {"wall_colour": "blue"}, {"rug": "no"}, {"sofa": 1}):
        assert client.put(f"/api/rooms/{rid}/concept", json={"overrides": bad}, headers=h).status_code == 422, bad
    latest = client.get(f"/api/rooms/{rid}/designs/latest", headers=h).json()
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": latest["objects"]}, headers=h).json()["version"]       # 3D editor save
    assert client.get(f"/api/rooms/{rid}/designs/{v}", headers=h).json()["finishes"]["accent"]["type"] == "STONE"
    styles = client.get("/api/concept/styles", headers=h).json()
    assert {"modern", "traditional", "boho", "luxury"} <= set(styles["styles"]) and "FLUTED_WOOD" in styles["accent_types"]


def test_presentation_pdf_and_portal(client):
    import pypdfium2 as pdfium
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models import models as m
    h = hdr(client); pid, rooms = home(client, h, RUN + "4")
    client.post(f"/api/projects/{pid}/home-plan/auto", json={}, headers=h)
    client.post(f"/api/projects/{pid}/concept", json={"style": "traditional"}, headers=h)
    r = client.get(f"/api/projects/{pid}/presentation.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    d = pdfium.PdfDocument(r.content); t = "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))
    assert len(d) >= 11 and "Interior design proposal" in t and "Traditional Indian style" in t and "Home plan" in t
    assert "Finish schedule" in t and "Backlit jaali panel" in t and "Master bedroom" in t and "Feature wall elevation" in t
    # client of the project can download it; another client can't
    cl = client.post("/api/clients", json={"name": "Home client", "phone": f"93{RUN}88"[:10]}, headers=h).json()
    client.patch(f"/api/projects/{pid}", json={"client_id": cl["id"]}, headers=h)
    db = SessionLocal()
    try:
        if not db.query(m.User).filter_by(email=f"home{RUN}@client.test").first():
            db.add(m.User(email=f"home{RUN}@client.test", full_name="Home client", role="CLIENT", client_id=cl["id"], password_hash=hash_password("ChangeMe123!"))); db.commit()
    finally: db.close()
    hc = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": f"home{RUN}@client.test", "password": "ChangeMe123!"}).json()["access_token"]}
    assert client.get(f"/api/portal/projects/{pid}/presentation.pdf", headers=hc).status_code == 200
    assert client.get(f"/api/projects/{pid}/presentation.pdf", headers=hc).status_code == 403


def test_new_room_types_lay_out():
    from app.catalogue_pack import PACKS
    from app.services import layouts
    from app.services.geometry import Room, validate
    cat = [dict(sku=r[0], name=r[1], category=r[2], length_mm=r[3], width_mm=r[4], height_mm=r[5], price=r[6], stock=4) for p in PACKS.values() for r in p]
    door = {"kind": "DOOR", "wall": "S", "offset": 100, "width": 900, "height": 2100, "sill": 0, "swing": "OUTWARD"}
    for kind, L, W, must in (("VERANDAH", 3500, 1800, "Outdoor Chair"), ("BALCONY", 3000, 1200, "Outdoor Chair"), ("FOYER", 1800, 1500, "Shoe Rack"),
                             ("POOJA", 1500, 1200, "Pooja Unit"), ("STORE", 2000, 1500, "Storage"), ("WASH_AREA", 2400, 1500, "Washing Machine")):
        R = Room(L, W, 2800, openings=[door]); r = layouts.plan(R, kind, cat)
        assert must in [o.category for o in r["objects"]] and validate(R, r["objects"])["valid"], (kind, r["notes"])
    p = layouts.plan(Room(1500, 1200, 2800, openings=[door]), "POOJA", cat)
    assert "face east" in " ".join(p["notes"])


def test_working_drawing_set(client):
    """M40: A3 working drawings for the site team: title block, light detail, room plan + feature-wall elevation + bed details,
    wardrobe elevation + internal detail, kitchen elevations + counter plan; feet-inches by default, mm on request or by setting."""
    import pypdfium2 as pdfium
    from app.services import drawingset
    assert drawingset.ftin(1600) == "5'-3\"" and drawingset.ftin(305) == "1'-0\"" and drawingset.ftin(100) == "4\"" and drawingset.ftin(2438) == "8'-0\""
    h = hdr(client); pid, rooms = home(client, h, RUN + "6")
    client.post(f"/api/projects/{pid}/home-plan/auto", json={}, headers=h)
    client.post(f"/api/projects/{pid}/concept", json={"style": "modern"}, headers=h).raise_for_status()

    def text(b): d = pdfium.PdfDocument(b); return len(d), "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))
    r = client.get(f"/api/projects/{pid}/drawing-set.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and "working-drawings-IQ-HOME" in r.headers["content-disposition"]
    n, t = text(r.content)
    for s in ("INTERIOR FOR RESIDENTIAL", "LIGHT DETAIL", "LEGEND", "MASTER BEDROOM", "ELEVATION", "SIDE ELEVATION", "FRONT ELEVATION",
              "INTERNAL DETAIL", "COUNTER PLAN", "ALL DIMENSIONS IN FEET", "DO NOT SCALE", "(A)", "(C)"):
        assert s in t, s
    assert "13'-11\"" in t                                                       # 4250 mm master bedroom wall printed in feet-inches
    one = client.get(f"/api/projects/{pid}/drawing-set.pdf", params={"room_id": rooms["Kitchen"], "units": "mm"}, headers=h)
    n1, t1 = text(one.content)
    assert one.status_code == 200 and n1 < n and "COUNTER PLAN" in t1 and "LIGHT DETAIL" not in t1 and "MILLIMETRES" in t1 and "3600" in t1
    assert client.get(f"/api/projects/{pid}/drawing-set.pdf", params={"room_id": "nope"}, headers=h).status_code == 404
    assert client.get(f"/api/projects/{pid}/drawing-set.pdf", params={"units": "cm"}, headers=h).status_code == 422
    # company default units
    assert client.put("/api/settings/drawing-units", json={"units": "inch"}, headers=h).status_code == 422
    assert client.put("/api/settings/drawing-units", json={"units": "mm"}, headers=h).json() == {"units": "mm"}
    assert "MILLIMETRES" in text(client.get(f"/api/projects/{pid}/drawing-set.pdf", params={"room_id": rooms["Pooja"]}, headers=h).content)[1]
    client.put("/api/settings/drawing-units", json={"units": "ftin"}, headers=h)
    assert client.get("/api/settings/drawing-units", headers=h).json() == {"units": "ftin"}
    # a project with nothing designed still gives a (one-page) PDF that says what to do
    empty = client.post("/api/projects", json={"project_number": f"IQ-EMPTY-{RUN}", "name": "Empty"}, headers=h).json()["id"]
    assert "Save designs" in text(client.get(f"/api/projects/{empty}/drawing-set.pdf", headers=h).content)[1]
