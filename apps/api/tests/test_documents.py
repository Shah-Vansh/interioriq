import io, os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import documents as docs, ocr
from app.services.ocr import Block

# ── helpers ──────────────────────────────────────────────────────────────────
def _font(sz):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        try: return ImageFont.truetype(f, sz)
        except Exception: pass
    return ImageFont.load_default()

def plan_png(extra: str = "") -> bytes:
    img = Image.new("RGB", (1400, 900), "white"); d = ImageDraw.Draw(img)
    d.rectangle([150, 150, 1250, 750], outline="black", width=6)
    for text, xy, sz in [("MASTER BEDROOM", (520, 380), 44), ("4250 mm", (600, 90), 40), ("3600 mm", (1280, 430), 40), ("Ceiling height: 2750 mm", (430, 800), 34), (extra, (200, 20), 20)]:
        if text: d.text(xy, text, fill="black", font=_font(sz))
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()

def text_pdf(lines):
    content = "BT /F1 18 Tf 50 750 Td 22 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1): offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()

class FakeOCR:
    name = "fake"
    def available(self): return True
    def read(self, img): return [Block("Length 4250 mm", 95, [0, 0, 1, 1]), Block("Width 3600 mm", 90, [0, 0, 1, 1]), Block("Ceiling height: 2750 mm", 97, [0, 0, 1, 1])]

class Broken:
    name = "broken"
    def available(self): return True
    def read(self, img): raise RuntimeError("engine exploded")

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="client@test.com").first():
            db.add(m.User(email="client@test.com", full_name="C", role="CLIENT", password_hash=hash_password("ChangeMe123!"))); db.commit()
        db.close(); yield c

def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}

_n = [0]
def project(c, h):
    _n[0] += 1
    pid = c.post("/api/projects", json={"project_number": f"IQ-D-{_n[0]}", "name": "docs"}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "R", "room_type": "BEDROOM"}, headers=h).json()["id"]
    return pid, rid

def up(c, h, pid, data, name="plan.png", ctype="image/png", **form):
    return c.post(f"/api/projects/{pid}/documents", files={"file": (name, data, ctype)}, data=form, headers=h)

@pytest.fixture
def fake_ocr(monkeypatch): monkeypatch.setattr(ocr, "get_providers", lambda: [FakeOCR()])

# ── upload security ──────────────────────────────────────────────────────────
def test_type_comes_from_content_not_from_name_or_mime(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h)
    r = up(client, h, pid, plan_png(), name="evil.exe", ctype="application/x-msdownload")
    assert r.status_code == 201 and r.json()["kind"] == "png"               # a real PNG with a silly name is still a PNG

@pytest.mark.parametrize("data,name", [(b"just some text, not an image", "plan.png"), (b"MZ\x90\x00 fake exe " * 20, "plan.pdf"), (b"<?php echo 1;", "plan.jpg")])
def test_disguised_files_are_rejected(client, data, name):
    h = hdr(client); pid, _ = project(client, h)
    assert up(client, h, pid, data, name=name).status_code == 415

def test_corrupt_files_are_rejected_at_upload(client):
    h = hdr(client); pid, _ = project(client, h)
    assert up(client, h, pid, b"\x89PNG\r\n\x1a\n" + os.urandom(300)).status_code == 422
    assert up(client, h, pid, b"%PDF-1.4\ngarbage", name="x.pdf", ctype="application/pdf").status_code == 422
    assert up(client, h, pid, b"").status_code == 422

def test_size_limit(client, monkeypatch):
    h = hdr(client); pid, _ = project(client, h)
    monkeypatch.setattr(docs, "MAX_BYTES", 1000)
    assert up(client, h, pid, plan_png()).status_code == 413

def test_path_traversal_filename_is_harmless(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h)
    r = up(client, h, pid, plan_png(), name="../../../../etc/passwd.png").json()
    assert r["name"] == "passwd.png"                                       # display name keeps no path
    stored = Path(settings.STORAGE_PATH) / "documents" / pid
    assert [p.name for p in stored.iterdir()] == [f"{r['id']}.png"]        # stored under a server-generated name, inside the project folder

def test_duplicate_upload_is_detected(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h); data = plan_png("dup")
    a, b = up(client, h, pid, data).json(), up(client, h, pid, data).json()
    assert a["duplicate"] is False and b["duplicate"] is True and a["id"] == b["id"]
    assert len(client.get(f"/api/projects/{pid}/documents", headers=h).json()) == 1

def test_room_from_another_project_is_rejected(client):
    h = hdr(client); pid, _ = project(client, h); _, other_room = project(client, h)
    assert up(client, h, pid, plan_png(), room_id=other_room).status_code == 422

def test_roles(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h)
    assert up(client, hdr(client, "client@test.com"), pid, plan_png()).status_code == 403          # clients cannot upload
    assert client.get(f"/api/projects/{pid}/documents", headers=hdr(client, "client@test.com")).status_code == 403
    assert up(client, hdr(client, "amit@interioriq.com"), pid, plan_png("site")).status_code == 201   # site engineers can
    assert client.get(f"/api/projects/{pid}/documents").status_code == 401

# ── pipeline ─────────────────────────────────────────────────────────────────
def test_ocr_runs_and_produces_candidates(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, plan_png('t1')).json()['id']}", headers=h).json()
    assert d["status"] == "OCR_DONE" and d["provider"] == "fake"
    got = {(c["label"], c["value_mm"]) for c in d["candidates"]}
    assert {("Length", 4250.0), ("Width", 3600.0), ("Ceiling Height", 2750.0)} <= got

def test_falls_back_to_next_engine_when_one_fails(client, monkeypatch):
    monkeypatch.setattr(ocr, "get_providers", lambda: [Broken(), FakeOCR()])
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, plan_png('t2')).json()['id']}", headers=h).json()
    assert d["status"] == "OCR_DONE" and d["provider"] == "fake"

def test_all_engines_failing_is_a_clear_failure_not_a_crash(client, monkeypatch):
    monkeypatch.setattr(ocr, "get_providers", lambda: [Broken()])
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, plan_png('t3')).json()['id']}", headers=h).json()
    assert d["status"] == "FAILED" and "failed" in d["error"].lower()

def test_no_engine_installed_says_how_to_fix_it(client, monkeypatch):
    monkeypatch.setattr(ocr, "get_providers", lambda: [])
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, plan_png('t4')).json()['id']}", headers=h).json()
    assert d["status"] == "FAILED" and "pip install" in d["error"]

def test_rerun_after_failure(client, monkeypatch):
    h = hdr(client); pid, _ = project(client, h)
    monkeypatch.setattr(ocr, "get_providers", lambda: [Broken()])
    doc = up(client, h, pid, plan_png("t5")).json()["id"]
    assert client.get(f"/api/documents/{doc}", headers=h).json()["status"] == "FAILED"
    monkeypatch.setattr(ocr, "get_providers", lambda: [FakeOCR()])
    assert client.post(f"/api/documents/{doc}/ocr", headers=h).status_code == 202
    assert client.get(f"/api/documents/{doc}", headers=h).json()["status"] == "OCR_DONE"

def test_pdf_text_layer_is_used_directly(client):
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, text_pdf(['Length 4250 mm', 'Width 3600 mm', 'Ceiling height 2750 mm']), name='cad.pdf', ctype='application/pdf').json()['id']}", headers=h).json()
    assert d["status"] == "OCR_DONE" and d["provider"] == "pdf-text-layer"
    c = {x["label"]: x for x in d["candidates"]}
    assert c["Length"]["value_mm"] == 4250.0 and c["Length"]["confidence"] == 99.0   # exact text, so high confidence

def test_file_download_is_authenticated_and_not_sniffable(client, fake_ocr):
    h = hdr(client); pid, _ = project(client, h); data = plan_png("dl")
    doc = up(client, h, pid, data).json()["id"]
    r = client.get(f"/api/documents/{doc}/file", headers=h)
    assert r.status_code == 200 and r.content == data and r.headers["x-content-type-options"] == "nosniff" and r.headers["content-type"] == "image/png"
    assert client.get(f"/api/documents/{doc}/file").status_code == 401
    assert client.get(f"/api/documents/{doc}/file", headers=hdr(client, "client@test.com")).status_code == 403
    assert client.get("/api/documents/nope/file", headers=h).status_code == 404

# ── applying OCR values: the source-priority rules must hold ─────────────────
def test_apply_respects_verified_values(client, fake_ocr):
    h = hdr(client); pid, rid = project(client, h)
    client.put(f"/api/rooms/{rid}/measurements", json={"label": "Length", "value": 4300, "source": "USER_VERIFIED"}, headers=h)
    doc = up(client, h, pid, plan_png("a1")).json()["id"]
    r = client.post(f"/api/documents/{doc}/apply", headers=h, json={"room_id": rid, "items": [
        {"label": "Length", "value_mm": 4250, "confidence": 95}, {"label": "Width", "value_mm": 3600, "confidence": 90}]}).json()
    by = {x["label"]: x for x in r["results"]}
    assert by["Length"]["applied"] is False and "USER_VERIFIED" in by["Length"]["reason"]    # OCR must not beat a verified value
    assert by["Width"]["applied"] is True and (r["applied"], r["rejected"]) == (1, 1)
    ms = {x["label"]: x for x in client.get(f"/api/rooms/{rid}/measurements", headers=h).json()}
    assert ms["Length"]["value"] == 4300 and ms["Length"]["source"] == "USER_VERIFIED"
    assert ms["Width"]["value"] == 3600 and ms["Width"]["source"] == "OCR" and ms["Width"]["verified"] is False

def test_apply_normalises_labels_and_ocr_can_update_ocr(client, fake_ocr):
    h = hdr(client); pid, rid = project(client, h); doc = up(client, h, pid, plan_png("a2")).json()["id"]
    apply = lambda label, v: client.post(f"/api/documents/{doc}/apply", headers=h, json={"room_id": rid, "items": [{"label": label, "value_mm": v, "confidence": 80}]}).json()
    assert apply("length ", 4000)["applied"] == 1 and apply("LENGTH", 4100)["applied"] == 1
    ms = client.get(f"/api/rooms/{rid}/measurements", headers=h).json()
    assert [(x["label"], x["value"]) for x in ms] == [("Length", 4100.0)]                  # one row, not three

def test_apply_rejects_other_projects_room_and_bad_values(client, fake_ocr):
    h = hdr(client); pid, rid = project(client, h); _, other = project(client, h); doc = up(client, h, pid, plan_png("a3")).json()["id"]
    post = lambda room, items: client.post(f"/api/documents/{doc}/apply", headers=h, json={"room_id": room, "items": items}).status_code
    ok = [{"label": "Length", "value_mm": 4000, "confidence": 90}]
    assert post(other, ok) == 422                                                          # cannot write into another project's room
    assert post(rid, [{"label": "Length", "value_mm": -5}]) == 422 and post(rid, [{"label": "", "value_mm": 5}]) == 422 and post(rid, []) == 422

# ── real engines, real pixels ────────────────────────────────────────────────
REAL = [p for p in ocr.ALL if p.available()]

@pytest.mark.skipif(not REAL, reason="no OCR engine installed")
@pytest.mark.parametrize("prov", REAL, ids=lambda p: p.name)
def test_real_engine_reads_a_floor_plan(client, monkeypatch, prov):
    monkeypatch.setattr(ocr, "get_providers", lambda: [prov])
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, plan_png('real-' + prov.name)).json()['id']}", headers=h).json()
    assert d["status"] == "OCR_DONE" and d["provider"] == prov.name, d.get("error")
    values = {c["value_mm"] for c in d["candidates"]}
    assert {4250.0, 3600.0, 2750.0} <= values, sorted(values)
    ceiling = [c for c in d["candidates"] if c["label"] == "Ceiling Height"]
    assert ceiling and ceiling[0]["value_mm"] == 2750.0                                    # label recognised from "Ceiling height:"

@pytest.mark.skipif(not REAL, reason="no OCR engine installed")
def test_real_engine_on_scanned_pdf(client, monkeypatch):
    monkeypatch.setattr(ocr, "get_providers", lambda: REAL)
    b = io.BytesIO(); Image.open(io.BytesIO(plan_png("scan"))).save(b, "PDF")             # raster-only PDF: no text layer
    h = hdr(client); pid, _ = project(client, h)
    d = client.get(f"/api/documents/{up(client, h, pid, b.getvalue(), name='scan.pdf', ctype='application/pdf').json()['id']}", headers=h).json()
    assert d["status"] == "OCR_DONE" and d["provider"] != "pdf-text-layer" and 2750.0 in {c["value_mm"] for c in d["candidates"]}, d.get("error")


def test_documents_interrupted_by_a_restart_are_recovered(client):
    h = hdr(client); pid, _ = project(client, h)
    db = SessionLocal(); d = m.Document(project_id=pid, original_name="x.png", kind="png", size_bytes=1, sha256="stuck-" + pid, storage_path="x", status="PROCESSING")
    db.add(d); db.commit(); did = d.id; db.close()
    assert client.get(f"/api/documents/{did}", headers=h).json()["status"] == "PROCESSING"
    with TestClient(app):                                    # starting the app again is a "restart"
        pass
    d = client.get(f"/api/documents/{did}", headers=h).json()
    assert d["status"] == "FAILED" and "restart" in d["error"]
    assert client.post(f"/api/documents/{did}/ocr", headers=h).status_code == 202   # ...and the user can retry
