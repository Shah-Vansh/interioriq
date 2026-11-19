"""M30 free rotation + colours: the server validator works on the TURNED footprint (collisions, room boundary), rotation is stored 0–360,
colours must be #rrggbb, DXF draws angled units at their angle, old designs (no rotation/colour) behave exactly as before."""
import io

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import geometry as g


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


def O(id, x, y, l, w, rot=0, **kw): return g.Obj(id, id, "Table", x, y, l, w, 750, rotation=rot, **kw)


def test_rotated_footprint_drives_collisions_and_boundary():
    room = g.Room(4000, 3000)
    # b sits 50 mm north of a: fine square-on, but turning a by 90° about its centre swings it 300 mm north into b
    a, b = O("a", 1000, 1000, 1000, 400), O("b", 1300, 1450, 400, 400)
    assert g.validate(room, [a, b])["valid"]
    r = g.validate(room, [O("a", 1000, 1000, 1000, 400, 90), b])
    assert not r["valid"] and set(r["flagged"]) == {"a", "b"}
    # a long table fits along the room, but at 90° … it is wider than the room is deep only if too long: 3500 long in a 3000 deep room
    assert g.validate(room, [O("t", 250, 1000, 3500, 900)])["valid"]
    out = g.validate(room, [O("t", 250, 1000, 3500, 900, 90)])
    assert not out["valid"] and "outside room boundary" in out["errors"][0]
    # 360 and 0 are the same; a 90° turn of a square changes nothing
    assert g.footprint(0, 0, 100, 100, 360).equals(g.footprint(0, 0, 100, 100, 0))
    assert g.footprint(0, 0, 100, 100, 90).equals(g.footprint(0, 0, 100, 100))


def _room(c, h, n):
    pid = c.post("/api/projects", json={"project_number": f"IQ-ROT-{n}", "name": "Rotation"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Living", "room_type": "LIVING"}, headers=h).json()["id"]
    for l, v in (("Length", 4000), ("Width", 3000)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return rid


def test_api_stores_rotation_and_colour_and_validates_them(client):
    import time
    h = hdr(client); rid = _room(client, h, str(int(time.time()))[-6:])
    obj = dict(id="t", name="Coffee table", category="Coffee Table", x=1500, y=1000, length=1000, width=500, height=400, price=12000)
    r = client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [{**obj, "rotation": -30, "colour": "#8B5A2B"}]}, headers=h)
    assert r.status_code == 200 and r.json()["valid"]
    for bad in ({"colour": "brown"}, {"colour": "#12345"}, {"rotation": 400}):
        assert client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [{**obj, **bad}]}, headers=h).status_code == 422, bad
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [{**obj, "rotation": -30, "colour": "#8B5A2B"}]}, headers=h).json()["version"]
    saved = client.get(f"/api/rooms/{rid}/designs/{v}", headers=h).json()
    o = (saved.get("design_json") or saved)["objects"][0]
    assert o["rotation"] == 330 and o["colour"] == "#8B5A2B"
    # DXF plan draws the turned rectangle (corners not axis-aligned)
    dxf = client.get(f"/api/rooms/{rid}/drawings/plan/dxf", params={"version": v}, headers=h)
    assert dxf.status_code == 200
    if True:
        doc = ezdxf.read(io.StringIO(dxf.content.decode("utf-8", "ignore")))
        polys = [p for p in doc.modelspace().query("LWPOLYLINE") if p.dxf.layer == "FURNITURE"]
        pts = [tuple(round(c, 1) for c in p[:2]) for p in polys[0].get_points()]
        assert len({x for x, _ in pts}) == 4                    # 4 different x values → really angled
