"""M32 bathroom + utility layouts: WC with 600 mm in front and elbow room, vanity (+ mirror cabinet above it), shower in a corner, linen;
utility: washing machine in a corner, counter run beside it, tall cabinet, wall cabinets above; everything passes the validator; the
electrical drawing gets wet-room points and no AC; OTHER rooms still need a chosen type; missing categories are reported."""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import layouts
from app.services.geometry import Room, validate

RUN = str(int(time.time()))[-6:]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


CAT = [dict(sku=a, name=b, category=c, length_mm=d, width_mm=e, height_mm=f, price=g, stock=5, **({"mount_mm": i} if i else {})) for a, b, c, d, e, f, g, i in [
    ("WC", "Wall-hung WC", "WC", 360, 540, 400, 24000, None), ("V8", "Vanity 800", "Vanity", 800, 480, 850, 32000, None), ("V6", "Vanity 600", "Vanity", 600, 450, 850, 24000, None),
    ("SH", "Shower 900", "Shower Enclosure", 900, 900, 2000, 38000, None), ("MI", "Mirror 800", "Mirror Cabinet", 800, 150, 700, 12500, 1300),
    ("LI", "Linen 450", "Linen Cabinet", 450, 350, 1800, 16000, None), ("WM", "Washer", "Washing Machine", 600, 600, 850, 0, None),
    ("UB", "Utility base 900", "Utility Base", 900, 560, 850, 19000, None), ("UT", "Utility tall", "Utility Tall", 600, 560, 2100, 27000, None),
    ("UW", "Utility wall", "Utility Wall", 900, 350, 700, 13000, 1450)]]
DOOR = lambda w, o, s="INWARD_LEFT": {"kind": "DOOR", "wall": w, "offset": o, "width": 800, "height": 2100, "sill": 0, "swing": s}


@pytest.mark.parametrize("L,W,door", [(2400, 1800, DOOR("S", 1400)), (3000, 2000, DOOR("W", 100)), (2100, 1500, DOOR("S", 1200, "OUTWARD")), (1500, 1500, None)])
def test_bathroom_rules(L, W, door):
    R = Room(L, W, 2700, openings=[door] if door else [])
    r = layouts.plan(R, "BATHROOM", CAT)
    cats = [o.category for o in r["objects"]]
    assert "WC" in cats and "Vanity" in cats and validate(R, r["objects"])["valid"]
    wc = next(o for o in r["objects"] if o.category == "WC")
    for o in r["objects"]:                                     # elbow room: nothing on the floor within 200 mm beside the WC
        if o is wc or o.z >= 1200: continue
        gap_x = max(o.x - (wc.x + wc.length), wc.x - (o.x + o.length)); gap_y = max(o.y - (wc.y + wc.width), wc.y - (o.y + o.width))
        assert max(gap_x, gap_y) >= 199, (o.name, gap_x, gap_y)
    mir = [o for o in r["objects"] if o.category == "Mirror Cabinet"]
    van = next(o for o in r["objects"] if o.category == "Vanity")
    assert all(m.z >= van.z + van.height for m in mir)
    if L * W >= 2400 * 1800: assert "Shower Enclosure" in cats                  # a normal bathroom gets its shower corner


def test_utility_rules():
    R = Room(2400, 1500, 2700, openings=[DOOR("S", 100, "OUTWARD")])
    r = layouts.plan(R, "UTILITY", CAT)
    by = {o.category: o for o in r["objects"]}
    assert {"Washing Machine", "Utility Base", "Utility Tall", "Utility Wall"} <= set(by) and validate(R, r["objects"])["valid"]
    w, b, u = by["Washing Machine"], by["Utility Base"], by["Utility Wall"]
    assert abs(b.y - w.y - (w.width - b.width)) < 1 or abs(b.y - w.y) < 60             # same wall as the washer
    assert u.z == 1450 and u.x == b.x                                                   # wall cabinet over the counter
    assert "counter run" in " ".join(r["notes"])


def test_api_generates_wet_rooms_and_electrical(client):
    h = hdr(client)
    meta = client.get("/api/layouts/meta", headers=h).json()
    assert "BATHROOM" in meta["kinds"] and "UTILITY" in meta["kinds"] and [s["slot"] for s in meta["required"]["BATHROOM"]] == ["wc", "vanity"]
    pid = client.post("/api/projects", json={"project_number": f"IQ-WET-{RUN}", "name": "Wet rooms"}, headers=h).json()["id"]
    out = {}
    for name, rt, L, W in (("Bath", "BATHROOM", 2400, 1800), ("Laundry", "UTILITY", 2400, 1500), ("Store", "OTHER", 2000, 1500)):
        rid = client.post(f"/api/projects/{pid}/rooms", json={"name": name, "room_type": rt}, headers=h).json()["id"]
        for l, v in (("Length", L), ("Width", W), ("Ceiling Height", 2700)): client.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
        client.post(f"/api/rooms/{rid}/openings", json={"kind": "DOOR", "wall": "S", "offset_mm": 100, "width_mm": 800, "height_mm": 2100, "swing": "OUTWARD"}, headers=h)
        out[name] = (rid, client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h))
    rid, r = out["Bath"]; assert r.status_code == 200, r.text
    d = r.json(); assert d["kind"] == "BATHROOM" and d["validation"]["valid"] and {"WC", "Vanity"} <= {o["category"] for o in d["objects"]}
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": d["objects"]}, headers=h).json()["version"]
    el = client.get(f"/api/rooms/{rid}/drawings/electrical", params={"version": v}, headers=h).json()
    labels = " ".join(p["label"] for p in el["points"])
    assert "Exhaust fan" in labels and "shaver" in labels.lower() and not any(p["type"] == "AC" for p in el["points"])
    assert out["Laundry"][1].status_code == 200 and out["Laundry"][1].json()["kind"] == "UTILITY"
    assert out["Store"][1].status_code == 422                                           # OTHER still needs a chosen type


def test_missing_categories_are_reported_not_invented():
    R = Room(2400, 1800, 2700)
    r = layouts.plan(R, "BATHROOM", [c for c in CAT if c["category"] not in ("Vanity", "Shower Enclosure")])
    miss = {m["slot"]: m["required"] for m in r["missing"]}
    assert miss.get("vanity") is True and miss.get("shower") is False and all(o.category != "Vanity" for o in r["objects"])
