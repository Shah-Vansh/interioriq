import os, tempfile
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"   # isolated DB, set before app import

from decimal import Decimal
import ezdxf, io, pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import geometry
from app.services.cost_engine import Line, compute
from app.services.room_model import apply_measurement, can_overwrite

# ── Cost engine ──────────────────────────────────────────────────────────────
def test_cost_hand_calculated():
    r = compute([Line(Decimal(1), Decimal(100000))])
    assert r["subtotal"] == Decimal("100000.00")
    assert r["overhead"] == Decimal("8000.00")
    assert r["margin"] == Decimal("19440.00")        # 18% of 108000
    assert r["discount"] == Decimal("6372.00")       # 5% of 127440
    assert r["gst"] == Decimal("21792.24")           # 18% of 121068
    assert r["grand_total"] == Decimal("142860.24")

def test_cost_has_no_float_drift():
    assert Line(Decimal(3), Decimal("0.10")).total == Decimal("0.30")

# ── Measurement source priority ──────────────────────────────────────────────
def test_ocr_cannot_overwrite_verified():
    existing = dict(label="Length", value=4250, unit="mm", source="USER_VERIFIED", confidence=100, verified=True)
    rec, applied = apply_measurement(existing, "Length", 4100, "mm", "OCR", 90, False)
    assert applied is False and rec["value"] == 4250

def test_priority_order():
    assert can_overwrite("OCR", False, "SITE_SURVEY")
    assert not can_overwrite("SITE_SURVEY", False, "AI_ESTIMATE")
    assert not can_overwrite("SITE_SURVEY", True, "SITE_SURVEY")   # verified: only USER_VERIFIED may replace
    assert can_overwrite("SITE_SURVEY", True, "USER_VERIFIED")

def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        can_overwrite("OCR", False, "MAGIC")

# ── Geometry ─────────────────────────────────────────────────────────────────
ROOM = geometry.Room(4250, 3600, 2750)
def test_collision_detected():
    a = geometry.Obj("a", "Bed", "Bed", 1000, 1000, 2000, 2000, 1000)
    b = geometry.Obj("b", "Desk", "Study", 2500, 2000, 1200, 600, 760)
    assert any("Collision" in e for e in geometry.validate(ROOM, [a, b])["errors"])

def test_outside_boundary_detected():
    o = geometry.Obj("a", "Wardrobe", "Wardrobe", 3000, 100, 2700, 600, 2200)
    assert not geometry.validate(ROOM, [o])["valid"]

def test_taller_than_ceiling_detected():
    o = geometry.Obj("a", "Tall", "Wardrobe", 100, 100, 600, 600, 3000)
    assert any("ceiling" in e for e in geometry.validate(ROOM, [o])["errors"])

def test_touching_edges_is_not_collision():
    a = geometry.Obj("a", "A", "x", 0, 0, 1000, 1000, 500)
    b = geometry.Obj("b", "B", "x", 1000, 0, 1000, 1000, 500)
    assert geometry.validate(ROOM, [a, b])["valid"]

# ── API (real auth, real DB) ─────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def hdr(client, email="admin@interioriq.com"):
    t = client.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}

def test_requires_auth(client):
    assert client.get("/api/projects").status_code == 401

def test_bad_password_rejected(client):
    assert client.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "nope"}).status_code == 401

def test_rbac_blocks_wrong_role(client):
    h = hdr(client, "amit@interioriq.com")   # SITE_ENGINEER cannot create projects
    assert client.post("/api/projects", json={"project_number": "X1", "name": "n"}, headers=h).status_code == 403

def test_full_flow(client):
    h = hdr(client)
    pid = client.post("/api/projects", json={"project_number": "IQ-T-1", "name": "Test"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Master Bedroom", "room_type": "MASTER_BEDROOM"}, headers=h).json()["id"]

    # design needs dimensions first
    assert client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).status_code == 409

    put = lambda label, v, src: client.put(f"/api/rooms/{rid}/measurements", json={"label": label, "value": v, "source": src}, headers=h).json()
    assert put("Length", 4250, "USER_VERIFIED")["applied"]
    assert put("Width", 3600, "USER_VERIFIED")["applied"]
    rejected = put("Length", 4100, "OCR")                       # OCR must not beat a verified value
    assert rejected["applied"] is False and rejected["current"]["value"] == 4250

    gen = client.post(f"/api/rooms/{rid}/designs/generate", json={"prompt": "modern bedroom under 20 lakh"}, headers=h).json()
    assert gen["validation"]["valid"] and len(gen["objects"]) >= 2
    assert gen["requirements"]["budget"] == 2_000_000

    v1 = client.post(f"/api/rooms/{rid}/designs", json={"objects": gen["objects"]}, headers=h).json()
    v2 = client.post(f"/api/rooms/{rid}/designs", json={"objects": gen["objects"]}, headers=h).json()
    assert (v1["version"], v2["version"]) == (1, 2)             # history preserved, never overwritten
    assert len(client.get(f"/api/rooms/{rid}/designs", headers=h).json()) == 2

    # an invalid (colliding) design is stored but flagged, never silently accepted
    bad = [dict(gen["objects"][0]), dict(gen["objects"][0], id="dup")]
    assert client.post(f"/api/rooms/{rid}/designs", json={"objects": bad}, headers=h).json()["is_valid"] is False

    for kind in ("floor-plan", "furniture", "elevation-north"):
        r = client.get(f"/api/rooms/{rid}/cad/{kind}", headers=h)
        assert r.status_code == 200
        ezdxf.read(io.StringIO(r.content.decode()))             # the DXF must actually parse

def test_boq_endpoint_matches_engine(client):
    r = client.post("/api/boq/compute", json={"lines": [{"qty": "1", "rate": "100000"}]}, headers=hdr(client)).json()
    assert r["grand_total"] == "142860.24"


def test_list_rooms_and_measurements(client):
    h = hdr(client)
    pid = client.post("/api/projects", json={"project_number": "IQ-T-2", "name": "List test"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Study", "room_type": "STUDY"}, headers=h).json()["id"]
    client.put(f"/api/rooms/{rid}/measurements", json={"label": "Length", "value": 3000, "source": "SITE_SURVEY"}, headers=h)
    assert [r["name"] for r in client.get(f"/api/projects/{pid}/rooms", headers=h).json()] == ["Study"]
    ms = client.get(f"/api/rooms/{rid}/measurements", headers=h).json()
    assert ms[0]["source"] == "SITE_SURVEY" and ms[0]["verified"] is False

def test_cors_allows_frontend_origin(client):
    r = client.options("/api/auth/login", headers={"Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,authorization"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_duplicate_project_number_is_409_not_500(client):
    h = hdr(client)
    assert client.post("/api/projects", json={"project_number": "IQ-DUP", "name": "a"}, headers=h).status_code == 201
    r = client.post("/api/projects", json={"project_number": "IQ-DUP", "name": "b"}, headers=h)
    assert r.status_code == 409 and "already exists" in r.json()["detail"]


def _room_with_dims(client, h, num):
    pid = client.post("/api/projects", json={"project_number": num, "name": "x"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "R", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)):
        client.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    return rid

def _obj(i, x, y, l=1000, w=600, h=800):
    return dict(id=i, name=f"Item {i}", category="Chair", x=x, y=y, length=l, width=w, height=h, price=1000)

def test_validate_endpoint_flags_offending_objects_without_saving(client):
    h = hdr(client); rid = _room_with_dims(client, h, "IQ-V-1")
    r = client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [_obj("a", 100, 100), _obj("b", 600, 300), _obj("c", 3000, 2500)]}, headers=h).json()
    assert r["valid"] is False and r["flagged"] == ["a", "b"]          # c is fine and is not flagged
    assert client.get(f"/api/rooms/{rid}/designs", headers=h).json() == []   # nothing was saved

def test_out_of_bounds_object_is_flagged(client):
    h = hdr(client); rid = _room_with_dims(client, h, "IQ-V-2")
    r = client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": [_obj("a", 4000, 100)]}, headers=h).json()
    assert r["flagged"] == ["a"]

def test_load_latest_and_specific_version(client):
    h = hdr(client); rid = _room_with_dims(client, h, "IQ-V-3")
    assert client.get(f"/api/rooms/{rid}/designs/latest", headers=h).status_code == 404
    client.post(f"/api/rooms/{rid}/designs", json={"objects": [_obj("a", 100, 100)]}, headers=h)
    client.post(f"/api/rooms/{rid}/designs", json={"objects": [_obj("a", 100, 100), _obj("b", 2000, 2000)]}, headers=h)
    assert len(client.get(f"/api/rooms/{rid}/designs/latest", headers=h).json()["objects"]) == 2
    v1 = client.get(f"/api/rooms/{rid}/designs/1", headers=h).json()
    assert v1["version"] == 1 and len(v1["objects"]) == 1
    assert client.get(f"/api/rooms/{rid}/designs/9", headers=h).status_code == 404

def test_malformed_objects_are_422_not_500(client):
    h = hdr(client); rid = _room_with_dims(client, h, "IQ-V-4")
    post = lambda objs: client.post(f"/api/rooms/{rid}/designs/validate", json={"objects": objs}, headers=h).status_code
    assert post([{"id": "a"}]) == 422                                   # missing fields
    assert post([_obj("a", 0, 0, l=-5)]) == 422                         # negative size
    assert post([_obj("a", 0, 0), _obj("a", 900, 900)]) == 422          # duplicate ids

def test_catalogue_furniture_list(client):
    items = client.get("/api/catalogue/furniture?in_stock=true", headers=hdr(client)).json()
    assert {"BED-KNG-WLT-001", "WAR-SLD-WLT-001"} <= {i["sku"] for i in items} and all(i["stock"] > 0 for i in items)


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:5173"])
def test_cors_allows_local_dev_origins(client, origin):
    r = client.options("/api/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.headers.get("access-control-allow-origin") == origin

@pytest.mark.parametrize("origin", ["https://evil.example.com", "http://localhost.evil.com", "http://127.0.0.1.evil.com:3000", "http://192.168.1.5:3000"])
def test_cors_blocks_other_origins(client, origin):
    r = client.options("/api/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in r.headers
