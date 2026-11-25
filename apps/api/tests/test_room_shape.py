"""M41 room shell: L-shaped / U / angled-wall rooms, doors on any wall (incl. the inner walls of an L), sloped and uneven ceilings,
beams / columns / pillars / ceiling drops — all checked by the ONE validator, respected by the layout generator."""
import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.main import app
from app.services import shape
from app.services.geometry import Obj, Room, validate

RUN = str(int(time.time()))[-6:]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


def test_outlines_and_walls():
    s = shape.clean_shape(4500, 3600, {"type": "CUTS", "cuts": {"ne": [1500, 1200]}})
    assert s == {"type": "CUTS", "cuts": {"NE": [1500, 1200]}}
    assert shape.outline(4500, 3600, s) == [(0, 0), (4500, 0), (4500, 2400), (3000, 2400), (3000, 3600), (0, 3600)]
    assert shape.polygon(4500, 3600, s).area == 4500 * 3600 - 1500 * 1200
    es = shape.edges(4500, 3600, s)
    assert [e["wall"] for e in es] == ["S", "E", "N", "E", "N", "W"] and [e["side"] for e in es] == ["S", "E", None, None, "N", "W"]
    # inner walls of the L have no 'side' — doors there are placed by wall number
    p = shape.resolve_opening(4500, 3600, s, {"edge": 2, "offset": 300, "width": 900})
    assert (p["x0"], p["y0"], p["x1"], p["y1"]) == (4200, 2400, 3300, 2400) and (p["nx"], p["ny"]) == (0, -1) and p["wall"] == "N"
    with pytest.raises(shape.ShapeError, match="no wall on the N side"): shape.resolve_opening(4500, 3600, s, {"wall": "N", "offset": 3200, "width": 900})
    assert shape.resolve_opening(4500, 3600, s, {"wall": "N", "offset": 1000, "width": 900})["y0"] == 3600
    for bad, why in (({"type": "CUTS", "cuts": {"NE": [4400, 1000]}}, "leaves less"), ({"type": "CUTS", "cuts": {"XX": [1, 1]}}, "Unknown corner"),
                     ({"type": "CUTS", "cuts": {"SW": [2500, 900], "SE": [1900, 900]}}, "south wall"),
                     ({"type": "POLYGON", "points": [[0, 0], [4000, 3000], [4000, 0], [0, 3000]]}, "crosses itself"),
                     ({"type": "POLYGON", "points": [[0, 0], [3000, 0], [3000, 2000], [0, 2000]]}, "must fill"), ({"type": "OVAL"}, "RECT, CUTS or POLYGON")):
        with pytest.raises(shape.ShapeError, match=why): shape.clean_shape(4000, 3000, bad)
    # angled wall: listed clockwise, normalised to counter-clockwise from the south-west
    a = shape.clean_shape(4000, 3200, {"type": "POLYGON", "points": [[0, 0], [0, 3200], [3400, 3200], [4000, 2500], [4000, 0]]})
    assert a["points"][0] == [0, 0] and a["points"][1] == [4000, 0] and len(shape.edges(4000, 3200, a)) == 5
    angled = shape.edges(4000, 3200, a)[2]
    assert angled["side"] is None and angled["wall"] == "E" and round(angled["length"]) == 922


def test_ceilings():
    sl = shape.clean_ceiling(4000, 3000, {"type": "sloped", "low": 2400, "high": 3600, "high_wall": "n"})
    assert sl == {"type": "SLOPED", "low": 2400, "high": 3600, "high_wall": "N"}
    assert shape.ceiling_at(sl, 2750, 4000, 3000, 100, 0) == 2400 and shape.ceiling_at(sl, 2750, 4000, 3000, 100, 1500) == 3000
    un = shape.clean_ceiling(4000, 3000, {"type": "UNEVEN", "points": [[0, 0, 2900], [4000, 3000, 2700], [2000, 1500, 2600]]})
    assert shape.ceiling_at(un, 0, 4000, 3000, 2000, 1500) == 2600 and 2600 < shape.ceiling_at(un, 0, 4000, 3000, 500, 500) < 2900
    assert shape.lowest_over(un, 0, 4000, 3000, box(1500, 1000, 2500, 2000)) == 2600           # the low spot inside the footprint counts
    for bad, why in (({"type": "SLOPED", "low": 3000, "high": 2500, "high_wall": "N"}, "more than low"), ({"type": "SLOPED", "low": 2400, "high": 3000}, "high_wall"),
                     ({"type": "UNEVEN", "points": [[0, 0, 900], [1, 1, 2500]]}, "1800"), ({"type": "UNEVEN", "points": [[9000, 0, 2500], [0, 0, 2500]]}, "outside")):
        with pytest.raises(shape.ShapeError, match=why): shape.clean_ceiling(4000, 3000, bad)


def test_validator_knows_the_shell():
    s = {"type": "CUTS", "cuts": {"NE": [1500, 1200]}}
    R = Room(4500, 3600, 2900, shape=s, ceiling_profile={"type": "SLOPED", "low": 2300, "high": 3200, "high_wall": "S"},
             structures=[{"kind": "COLUMN", "x": 0, "y": 0, "length": 300, "width": 300, "label": "Column 1"},
                         {"kind": "BEAM", "x": 0, "y": 1700, "length": 4500, "width": 230, "depth": 450, "label": "Beam 1"},
                         {"kind": "PILLAR", "x": 2000, "y": 1000, "length": 300, "width": 300, "label": "Pillar 1"}])
    v = lambda *o: validate(R, list(o))["errors"]
    assert v(Obj("a", "Bed", "Bed", 3200, 2600, 1000, 900, 450)) == ["Bed: outside room boundary"]                        # in the cut-out corner
    assert v(Obj("a", "Bed", "Bed", 100, 100, 600, 600, 450)) == ["Bed: hits Column 1"]
    assert v(Obj("a", "Desk", "Desk", 1900, 900, 600, 400, 750)) == ["Desk: hits Pillar 1"]
    under = shape.ceiling_at(R.ceiling_profile, 0, 4500, 3600, 0, 1930) - 450
    e = v(Obj("w", "Wardrobe", "Wardrobe", 400, 1600, 1800, 600, 2400))
    assert e == [f"Wardrobe: hits Beam 1 (underside {under:.0f}mm)"]
    assert v(Obj("w", "Base", "Kitchen", 400, 1600, 900, 600, 850)) == []                                                   # low unit passes under the beam
    tall = Obj("t", "Tall unit", "Kitchen", 400, 3000, 600, 590, 2350)                                                        # north = low side (2300)
    assert v(tall)[0].startswith("Tall unit: taller than the ceiling here") and v(Obj("t", "Tall unit", "Kitchen", 400, 400, 600, 590, 2350)) == []


def _room(c, h, pid, name, rt, L, W, H=2900):
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": name, "room_type": rt}, headers=h).json()["id"]
    for l, v in (("Length", L), ("Width", W), ("Ceiling Height", H)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return rid


def test_survey_api_and_generator(client):
    h = hdr(client)
    pid = client.post("/api/projects", json={"project_number": f"IQ-SHAPE-{RUN}", "name": "Odd flat"}, headers=h).json()["id"]
    rid = _room(client, h, pid, "Master bedroom", "MASTER_BEDROOM", 4800, 4200)
    assert client.get(f"/api/rooms/{rid}/shape", headers=h).json()["shape"] == {"type": "RECT"}
    r = client.put(f"/api/rooms/{rid}/shape", json={"shape": {"type": "CUTS", "cuts": {"NE": [1500, 1500]}}}, headers=h)
    assert r.status_code == 200 and r.json()["area_sqm"] == round((4800 * 4200 - 1500 * 1500) / 1e6, 2) and len(r.json()["edges"]) == 6
    assert client.put(f"/api/rooms/{rid}/shape", json={"shape": {"type": "CUTS", "cuts": {"NE": [4700, 100]}}}, headers=h).status_code == 422
    # door: across the cut on the N side is refused; on the inner wall by number it's fine
    d = {"kind": "DOOR", "offset_mm": 3400, "width_mm": 900, "height_mm": 2100, "swing": "INWARD_LEFT"}
    bad = client.post(f"/api/rooms/{rid}/openings", json={**d, "wall": "N"}, headers=h)
    assert bad.status_code == 422 and "pick the wall by number" in bad.json()["detail"]
    ok = client.post(f"/api/rooms/{rid}/openings", json={**d, "offset_mm": 200, "edge": 3}, headers=h)          # edge 3 = inner wall facing east
    assert ok.status_code == 201, ok.text
    door = ok.json()["openings"][0]
    assert door["edge"] == 3 and door["wall"] == "E" and door["x0"] == 3300 and door["nx"] == -1
    client.post(f"/api/rooms/{rid}/openings", json={"kind": "WINDOW", "wall": "S", "offset_mm": 1500, "width_mm": 1500, "height_mm": 1200, "sill_mm": 900}, headers=h).raise_for_status()
    # the shape can't change under a door
    r = client.put(f"/api/rooms/{rid}/shape", json={"shape": {"type": "RECT"}}, headers=h)
    assert r.status_code == 409 and "Door 1" in r.json()["detail"]
    # ceiling
    assert client.put(f"/api/rooms/{rid}/ceiling", json={"ceiling": {"type": "SLOPED", "low": 2000, "high": 3000, "high_wall": "N"}}, headers=h).status_code == 409   # window head 2100 > 2000
    r = client.put(f"/api/rooms/{rid}/ceiling", json={"ceiling": {"type": "SLOPED", "low": 2700, "high": 3300, "high_wall": "N"}}, headers=h).json()
    assert r["ceiling"]["type"] == "SLOPED" and (r["ceiling_min"], r["ceiling_max"]) == (2700, 3300)
    # structures
    assert client.post(f"/api/rooms/{rid}/structures", json={"kind": "BEAM", "x_mm": 0, "y_mm": 2000, "length_mm": 4800, "width_mm": 230}, headers=h).status_code == 422
    assert client.post(f"/api/rooms/{rid}/structures", json={"kind": "BEAM", "x_mm": 0, "y_mm": 2000, "length_mm": 4800, "width_mm": 230, "depth_mm": 1600}, headers=h).status_code == 422
    assert client.post(f"/api/rooms/{rid}/structures", json={"kind": "PILLAR", "x_mm": 3500, "y_mm": 3000, "length_mm": 300, "width_mm": 300}, headers=h).status_code == 422  # in the cut
    r = client.post(f"/api/rooms/{rid}/structures", json={"kind": "BEAM", "x_mm": 0, "y_mm": 2000, "length_mm": 4800, "width_mm": 230, "depth_mm": 450}, headers=h)
    assert r.status_code == 201 and r.json()["structures"][0]["label"] == "Beam 1"
    col = client.post(f"/api/rooms/{rid}/structures", json={"kind": "COLUMN", "x_mm": 0, "y_mm": 0, "length_mm": 350, "width_mm": 350}, headers=h).json()["structures"][1]
    assert col["label"] == "Column 1" and col["depth"] == 0
    # the generator works around all of it and the result is valid
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={"prompt": "master bedroom", "catalogue_filter_in_stock": False}, headers=h)
    assert g.status_code == 200, g.text
    body = g.json(); assert body["validation"]["valid"], body["validation"]
    bed = next(o for o in body["objects"] if o["category"] == "Bed")
    assert not (bed["x"] + bed["length"] > 3300 and bed["y"] + bed["width"] > 2700)                    # not in the cut-out
    assert not any(o["x"] < 350 and o["y"] < 350 for o in body["objects"])                             # not on the column
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": body["objects"]}, headers=h).json()["version"]
    # a pillar dropped onto the bed makes the saved design invalid — reported on the survey screen
    r = client.post(f"/api/rooms/{rid}/structures", json={"kind": "PILLAR", "x_mm": bed["x"] + 100, "y_mm": bed["y"] + 100, "length_mm": 300, "width_mm": 300}, headers=h).json()
    assert r["latest_design"]["version"] == v and not r["latest_design"]["valid"] and any("Pillar 1" in e for e in r["latest_design"]["errors"])
    sid = r["structures"][-1]["id"]
    assert client.patch(f"/api/structures/{sid}", json={"x_mm": 2000, "y_mm": 2500}, headers=h).status_code == 200
    r = client.delete(f"/api/structures/{sid}", headers=h).json(); assert len(r["structures"]) == 2
    tl = client.get(f"/api/projects/{pid}/timeline", headers=h)
    if tl.status_code == 200: assert "room shape set" in tl.text and "Beam 1 added" in tl.text


def test_drawings_and_takeoff_follow_the_shell():
    from app.services import cad, mep, takeoff
    import ezdxf, io
    s = {"type": "CUTS", "cuts": {"NE": [1500, 1500]}}
    shell = {"L": 4800, "W": 4200, "H": 2900, "shape": s, "outline": [list(p) for p in shape.outline(4800, 4200, s)],
             "ceiling": {"type": "SLOPED", "low": 2700, "high": 3300, "high_wall": "N"}, "ceiling_min": 2700, "ceiling_max": 3300,
             "structures": [{"kind": "COLUMN", "x": 0, "y": 0, "length": 300, "width": 300, "label": "Column 1", "depth": 0},
                            {"kind": "BEAM", "x": 0, "y": 2000, "length": 4800, "width": 230, "depth": 450, "label": "Beam 1"}]}
    c = mep.ceiling(4800, 4200, 2900, [], shell)
    assert c["gypsum_area_m2"] == round((4800 * 4200 - 1500 * 1500) / 1e6, 2) and c["false_ceiling_height"] == 2400
    assert all(not (p["x"] > 3300 and p["y"] > 2700) for p in c["lights"]) and all(not (1850 <= p["y"] <= 2380) for p in c["lights"])
    north = next(e for e in mep.elevations(4800, 4200, 2900, [], [], shell) if e["wall"] == "NORTH")
    assert north["ceiling_line"][0] == [0, 3300] and north["wall_spans"] == [(0, 3300)]
    west = next(e for e in mep.elevations(4800, 4200, 2900, [], [], shell) if e["wall"] == "WEST")
    assert west["ceiling_line"][0][1] == 2700 and west["ceiling_line"][-1][1] == 3300
    assert {x["label"] for x in west["structures"]} == {"Column 1", "Beam 1"}
    doc = ezdxf.read(io.StringIO(cad.furniture_layout("R", 4800, 4200, [], [], shell).decode()))
    assert {"STRUCTURE", "BEAMS"} <= {l.dxf.name for l in doc.layers}
    assert len(doc.modelspace().query("LWPOLYLINE")[0].get_points()) == 6 and len(doc.modelspace().query("DIMENSION")) >= 8
    q = takeoff.quantities(4800, 4200, 2900, [], [], None, shell)
    plain = takeoff.quantities(4800, 4200, 2900, [], [], None, None)
    assert float(q["FLOORING"]["qty"]) == round((4800 * 4200 - 1500 * 1500 - 300 * 300) / 1e6, 2)
    assert float(q["WALL_PAINT"]["qty"]) > float(plain["WALL_PAINT"]["qty"]) and "Beam 1" in q["WALL_PAINT"]["basis"]
    assert float(q["SKIRTING"]["qty"]) == round((2 * (4800 + 4200) + 600) / 1000, 2)        # an L has the same perimeter + column faces
