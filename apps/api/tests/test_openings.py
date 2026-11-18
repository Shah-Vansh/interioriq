"""M19 doors & windows: opening validation, door swing/approach + window checks in the validator, the generator avoiding doors,
switchboard beside the door, paint/skirting deductions, elevations + DXF with openings, re-check of the latest design, roles."""
import io
from decimal import Decimal as D

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import geometry, takeoff


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, r in (("cli19@test.com", "CLIENT"), ("site19@test.com", "SITE_ENGINEER")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=r.title(), role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]


BED = dict(id="bed", name="King Bed — Walnut", category="Bed", sku="BED-KNG-WLT-001", price=124000, x=1110, y=1520, length=1930, width=2030, height=1200)
WAR = dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)


def room(c, h, dims=True):
    n = u(); pid = c.post("/api/projects", json={"project_number": f"IQ-OP-{n}", "name": "Openings flat"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    if dims:
        for l, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2900)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return pid, rid


def add(c, h, rid, **kw):
    return c.post(f"/api/rooms/{rid}/openings", json={"kind": "DOOR", "wall": "S", "offset_mm": 3200, "width_mm": 900, "height_mm": 2100} | kw, headers=h)


def test_openings_are_validated(client):
    h = hdr(client)
    _, nodim = room(client, h, dims=False)
    assert add(client, h, nodim).status_code == 409
    pid, rid = room(client, h)
    assert add(client, h, rid, offset_mm=3500).status_code == 422                                         # 3500 + 900 > 4250
    assert add(client, h, rid, wall="X").status_code == 422 and add(client, h, rid, kind="ARCH").status_code == 422
    assert add(client, h, rid, swing="UPWARD").status_code == 422
    assert add(client, h, rid, kind="WINDOW", wall="N", height_mm=2500, sill_mm=900).status_code == 422     # taller than the 2900 room
    assert add(client, h, rid, width_mm=200).status_code == 422
    r = add(client, h, rid, sill_mm=500).json()
    d = r["openings"][0]; assert d["label"] == "Door 1" and d["sill"] == 0 and d["swing"] == "INWARD_RIGHT"   # doors start at the floor
    assert add(client, h, rid, offset_mm=3600, width_mm=600).status_code == 409                          # overlaps Door 1
    w = add(client, h, rid, kind="WINDOW", wall="n", offset_mm=1500, width_mm=1200, height_mm=1200, sill_mm=900, swing="INWARD_LEFT").json()
    win = next(o for o in w["openings"] if o["kind"] == "WINDOW"); assert win["label"] == "Window 1" and win["swing"] is None and win["wall"] == "N"
    assert client.patch(f"/api/openings/{win['id']}", json={"offset_mm": 3500}, headers=h).status_code == 422
    assert client.patch(f"/api/openings/{win['id']}", json={"offset_mm": 1000}, headers=hdr(client, "site19@test.com")).json()["openings"][1]["offset"] == 1000
    assert client.get(f"/api/rooms/{rid}/openings", headers=hdr(client, "cli19@test.com")).status_code == 403
    assert [o["label"] for o in client.delete(f"/api/openings/{win['id']}", headers=h).json()["openings"]] == ["Door 1"]
    assert len(client.get(f"/api/rooms/{rid}/openings", headers=h).json()["openings"]) == 1


def test_validator_keeps_doorways_clear_and_warns_about_windows():
    room_ = geometry.Room(4250, 3600, 2900, openings=[
            {"kind": "DOOR", "wall": "S", "offset": 3200, "width": 900, "height": 2100, "swing": "INWARD_RIGHT", "label": "Door 1"},
            {"kind": "DOOR", "wall": "E", "offset": 2000, "width": 800, "height": 2100, "swing": "SLIDING", "label": "Door 2"},
            {"kind": "WINDOW", "wall": "S", "offset": 600, "width": 1200, "height": 1200, "sill": 900, "label": "Window 1"}])
    O = lambda **kw: geometry.Obj(**({"id": "x", "name": "Chair", "category": "Chair", "x": 0, "y": 0, "length": 500, "width": 500, "height": 800} | kw))
    v = geometry.validate(room_, [O(x=3400, y=500)])                       # inside the 900 mm swing square
    assert not v["valid"] and "blocks Door 1" in v["errors"][0] and v["flagged"] == ["x"]
    assert geometry.validate(room_, [O(x=3400, y=950)])["valid"]           # just outside it
    assert not geometry.validate(room_, [O(x=3800, y=2100)])["valid"]      # within 450 mm of the sliding door on the east wall
    assert geometry.validate(room_, [O(x=3200, y=2100)])["valid"]          # 550 mm away
    w = geometry.validate(room_, [O(id="w", name="Wardrobe", x=50, y=50, length=2000, width=600, height=2200)])
    assert w["valid"] and any("covers Window 1" in x for x in w["warnings"])
    assert not any("covers" in x for x in geometry.validate(room_, [O(id="t", name="Low unit", x=600, y=50, length=1000, width=400, height=750)])["warnings"])


def test_new_door_rechecks_the_latest_design_and_generation_avoids_it(client):
    h = hdr(client); pid, rid = room(client, h)
    client.post(f"/api/rooms/{rid}/designs", json={"objects": [BED, WAR]}, headers=h)
    r = add(client, h, rid, offset_mm=100, width_mm=900).json()                                           # door right behind the wardrobe
    assert r["latest_design"]["valid"] is False and "blocks Door 1" in r["latest_design"]["errors"][0]
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).json()
    assert g["validation"]["valid"] is True and {o["category"] for o in g["objects"]} == {"Bed", "Wardrobe"}
    war = next(o for o in g["objects"] if o["category"] == "Wardrobe")
    assert not (war["y"] < 900 and war["x"] < 1000)                                                        # moved away from the door
    assert client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [BED, WAR]}, headers=h).json()["valid"] is False


def test_switchboard_goes_beside_the_door():
    no_door = takeoff.mep.electrical(4250, 3600, 2900, [BED, WAR])
    assert no_door["assumptions"] and "no door is recorded" in no_door["assumptions"][0]
    e = takeoff.mep.electrical(4250, 3600, 2900, [BED, WAR], [{"kind": "DOOR", "wall": "S", "offset": 3200, "width": 900, "height": 2100, "swing": "INWARD_RIGHT", "label": "Door 1"}])
    sb = next(p for p in e["points"] if p["type"] == "SWITCHBOARD")
    assert e["assumptions"] == [] and "beside Door 1" in sb["label"] and (sb["x"], sb["y"]) == (3050, 0)   # 3200+900+150 > 4250−300 → other side


def test_takeoff_deducts_openings():
    ops = [{"kind": "DOOR", "wall": "S", "offset": 3200, "width": 900, "height": 2100, "swing": "INWARD_RIGHT", "label": "Door 1"},
           {"kind": "WINDOW", "wall": "N", "offset": 1500, "width": 1200, "height": 1200, "sill": 900, "label": "Window 1"}]
    q = takeoff.quantities(4250, 3600, 2900, [BED, WAR], ops)
    assert q["WALL_PAINT"]["qty"] == D("34.94") and "3.33 sq.m doors/windows" in q["WALL_PAINT"]["basis"]  # 38.27 − 1.89 − 1.44
    assert q["SKIRTING"]["qty"] == D("11.5") and "0.90 m doorways" in q["SKIRTING"]["basis"]               # 12.4 − 0.9


def test_elevations_and_dxf_show_openings(client):
    h = hdr(client); pid, rid = room(client, h)
    client.post(f"/api/rooms/{rid}/designs", json={"objects": [BED, WAR]}, headers=h)
    add(client, h, rid)
    add(client, h, rid, kind="WINDOW", wall="N", offset_mm=1500, width_mm=1200, height_mm=1200, sill_mm=900)
    el = {w["wall"]: w for w in client.get(f"/api/rooms/{rid}/drawings/elevations", headers=h).json()["walls"]}
    assert el["NORTH"]["openings"] == [{"label": "Window 1", "kind": "WINDOW", "x": 1500, "width": 1200, "height": 1200, "sill": 900}]
    assert el["SOUTH"]["openings"][0]["x"] == 4250 - (3200 + 900)                                          # seen from inside, left → right
    plan = client.get(f"/api/rooms/{rid}/drawings/plan", headers=h).json(); assert len(plan["openings"]) == 2
    e = client.get(f"/api/rooms/{rid}/drawings/electrical", headers=h).json(); assert e["assumptions"] == []
    for kind, extra in (("plan", ""), ("electrical", ""), ("elevation", "?wall=SOUTH")):
        doc = ezdxf.read(io.StringIO(client.get(f"/api/rooms/{rid}/drawings/{kind}/dxf{extra}", headers=h).content.decode("utf-8", "replace")))
        layers = {e.dxf.layer for e in doc.modelspace()}
        assert "DOORS" in layers, kind
    doc = ezdxf.read(io.StringIO(client.get(f"/api/rooms/{rid}/drawings/plan/dxf", headers=h).content.decode("utf-8", "replace")))
    assert any(e.dxftype() == "ARC" for e in doc.modelspace()) and "WINDOWS" in {e.dxf.layer for e in doc.modelspace()}
