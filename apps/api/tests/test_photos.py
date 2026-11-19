"""M28 catalogue photos: content-validated upload (JPG/PNG/WebP only, size/pixel caps), re-encoded full + thumb JPEGs with server names,
replace removes the old files, delete, roles (write = catalogue writers, view = staff, never clients), shown on the quotation PDF."""
import io

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import photos


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, r in (("des28@test.com", "INTERIOR_DESIGNER"), ("cli28@test.com", "CLIENT")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=r.title(), role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def img(fmt="PNG", size=(1600, 900), mode="RGB"):
    b = io.BytesIO(); Image.new(mode, size, (180, 120, 60) if mode == "RGB" else (180, 120, 60, 128)).save(b, fmt); return b.getvalue()


def item_id(c, h, sku="WAR-SLD-WLT-001"):
    return next(i for i in c.get("/api/catalogue/items?kind=FURNITURE", headers=h).json() if i["sku"] == sku)["id"]


def test_upload_view_replace_delete(client):
    h = hdr(client); iid = item_id(client, h)
    r = client.post(f"/api/catalogue/items/{iid}/photo", files={"file": ("wardrobe.png", img("PNG", mode="RGBA"), "image/png")}, headers=h)
    assert r.status_code == 200 and r.json()["has_photo"] and r.json()["photo_v"]
    db = SessionLocal(); first = db.get(m.FurnitureItem, iid).photo; db.close()
    th = client.get(f"/api/catalogue/items/{iid}/photo", headers=hdr(client, "des28@test.com"))
    assert th.status_code == 200 and th.headers["content-type"] == "image/jpeg"
    t = Image.open(io.BytesIO(th.content)); assert t.format == "JPEG" and max(t.size) == photos.THUMB
    full = Image.open(io.BytesIO(client.get(f"/api/catalogue/items/{iid}/photo?size=full", headers=h).content)); assert max(full.size) == photos.FULL
    # replacing removes the old files
    client.post(f"/api/catalogue/items/{iid}/photo", files={"file": ("w.jpg", img("JPEG", (500, 800)), "image/jpeg")}, headers=h)
    assert photos.path(first) is None
    assert client.delete(f"/api/catalogue/items/{iid}/photo", headers=h).json()["has_photo"] is False
    assert client.get(f"/api/catalogue/items/{iid}/photo", headers=h).status_code == 404


def test_bad_files_and_roles_are_refused(client):
    h = hdr(client); iid = item_id(client, h)
    for data, name, code in ((b"%PDF-1.4 not an image", "x.jpg", 415), (b"", "e.png", 422), (img("GIF", (50, 50)), "a.gif", 415),
                             (b"GIF89a" + b"\x00" * 50, "fake.png", 415)):
        assert client.post(f"/api/catalogue/items/{iid}/photo", files={"file": (name, data, "image/png")}, headers=h).status_code == code, name
    assert client.post(f"/api/catalogue/items/{iid}/photo", files={"file": ("p.png", img(), "image/png")}, headers=hdr(client, "des28@test.com")).status_code == 403
    client.post(f"/api/catalogue/items/{iid}/photo", files={"file": ("p.png", img(), "image/png")}, headers=h)
    assert client.get(f"/api/catalogue/items/{iid}/photo", headers=hdr(client, "cli28@test.com")).status_code == 403
    client.delete(f"/api/catalogue/items/{iid}/photo", headers=h)


def test_photo_is_printed_on_the_quotation(client):
    h = hdr(client); iid = item_id(client, h)
    client.post(f"/api/catalogue/items/{iid}/photo", files={"file": ("p.png", img(), "image/png")}, headers=h)
    cl = client.post("/api/clients", json={"name": "Photo client", "phone": "9280000001"}, headers=h).json()
    pid = client.post("/api/projects", json={"project_number": "IQ-PHO-1", "name": "Photo flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): client.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=h).json()["version"]
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    def images(pdf):
        d = pdfium.PdfDocument(pdf); return sum(1 for o in d[0].get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE)
    with_photo = client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content
    without = client.get(f"/api/boqs/{b['id']}/quotation.pdf?photos=false", headers=h).content
    assert images(with_photo) == 1 and images(without) == 0
    client.delete(f"/api/catalogue/items/{iid}/photo", headers=h)
