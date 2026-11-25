"""Shop drawings: PDF (A3) + DXF per work order, drawn from the SAME rules as the cutting list (type-aware: plinth for floor kitchen units,
no shelf in sinks, 3-drawer hob stack), title block + cutting list on the sheet, roles."""
import io

import ezdxf
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import cutting, shopdrawing


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


def text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


@pytest.mark.parametrize("cat,L,D,H", [("Wardrobe", 2700, 600, 2200), ("Kitchen", 900, 600, 850), ("Kitchen Sink", 900, 600, 850),
                                       ("Kitchen Hob", 900, 600, 850), ("Kitchen Wall", 900, 350, 700), (None, 1200, 450, 1800)])
def test_drawing_matches_the_cutting_list(cat, L, D, H):
    g = shopdrawing.layout(cat, L, D, H); p = {x["name"].split(" (")[0]: x for x in cutting.panels(L, D, H, cat)}
    assert len(g["partitions"]) == p.get("Partition", {"qty": 0})["qty"]
    panels = cutting.panels(L, D, H, cat)
    shelves = sum(x["qty"] for x in panels if x["name"] == "Shelf")
    drawn = sum(len(b["ys"]) for b in g["wbays"] if b["kind"] == "SHELVES") if g.get("wbays") else g["shelves_per_bay"] * g["bays"]
    assert drawn == shelves
    assert g["doors"] == p.get("Shutter", {"qty": 0})["qty"] and (sum(len(b["drawers"]) for b in g["wbays"] if b["kind"] == "HANGING") if g.get("wbays") else g["drawers"]) == p.get("Drawer front", {"qty": 0})["qty"]
    assert p["Side"]["length"] == H - g["plinth"]                                  # carcass height excludes the plinth
    cut = cutting.cut_list(L, D, H, cat)
    t = text(shopdrawing.pdf(title=f"Unit {cat}", wo_number="WO-T-001", project="IQ-T", unit_no=1, sku="SKU-1", material="BWP ply", category=cat, cut=cut, company="Studio"))
    assert "FRONT ELEVATION" in t and "CUTTING LIST" in t and f"{L:.0f} overall width" in t and "WO-T-001" in t
    doc = ezdxf.read(io.StringIO(shopdrawing.dxf(title="t", category=cat, cut=cut).decode()))
    assert {"CARCASS", "SHUTTERS", "DIMENSIONS"} <= {l.dxf.name for l in doc.layers} and len(doc.modelspace().query("DIMENSION")) >= 3


def test_kitchen_rules():
    hob = {p["name"]: p for p in cutting.panels(900, 600, 850, "Kitchen Hob")}
    assert "Shutter" not in hob and hob["Drawer front"]["qty"] == 3 and hob["Plinth"]["length"] == 860
    assert "Shelf" not in {p["name"] for p in cutting.panels(900, 600, 850, "Kitchen Sink")}
    assert cutting.panels(900, 600, 850) == cutting.panels(900, 600, 850, None)       # no category → old behaviour


def test_endpoint_for_a_work_order(client):
    h = hdr(client)
    cl = client.post("/api/clients", json={"name": "Shop client", "phone": "9361000001"}, headers=h).json()
    pid = client.post("/api/projects", json={"project_number": "IQ-SHOP-1", "name": "Shop flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): client.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=h).json()["version"]
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    client.post(f"/api/boqs/{b['id']}/work-orders", headers=h)
    wo = client.get("/api/work-orders", params={"project_id": pid}, headers=h).json()[0]
    r = client.get(f"/api/work-orders/{wo['id']}/shop-drawing.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and wo["wo_number"] in text(r.content)
    d = client.get(f"/api/work-orders/{wo['id']}/shop-drawing.dxf", headers=h); assert d.status_code == 200 and b"DIMENSION" in d.content
    assert client.get(f"/api/work-orders/{wo['id']}/shop-drawing.png", headers=h).status_code == 404
