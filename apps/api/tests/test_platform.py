"""M12–M13: dashboard/reports/AI-PM from live data, settings (company, users, roles, system, AI), contacts, client portal, drawings, what-if costing, site photos."""
import io
from datetime import date, timedelta

import ezdxf
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for email, role in (("des12@test.com", "INTERIOR_DESIGNER"), ("pm12@test.com", "PROJECT_MANAGER")):
            if not db.query(m.User).filter_by(email=email).first():
                db.add(m.User(email=email, full_name=role.title(), role=role, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, email="admin@interioriq.com", pw="ChangeMe123!"):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


_n = [0]
def u():
    _n[0] += 1; return _n[0]


def project(c, h, **kw):
    n = u(); return c.post("/api/projects", json={"project_number": f"IQ-PL-{n}", "name": f"Platform {n}"} | kw, headers=h).json()


def room_with_design(c, h, pid, objs=None):
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2900)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = objs or [dict(id="bed", name="King Bed — Walnut", category="Bed", sku="BED-KNG-WLT-001", price=124000, x=1110, y=1520, length=1930, width=2030, height=1200),
                    dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()
    assert v["is_valid"], v
    return rid, v["version"]


def pdf_text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


# ── Dashboard / reports / AI PM ───────────────────────────────────────────────
def test_dashboard_and_alerts_come_from_real_data(client):
    h = hdr(client)
    late = project(client, h, target_date=(date.today() - timedelta(days=3)).isoformat())
    d = client.get("/api/dashboard", headers=h).json()
    assert d["cards"]["active_projects"] >= 1 and d["money_visible"] is True and isinstance(d["activity"], list)
    assert any(s["stage"] == "LEAD" and s["count"] >= 1 for s in d["stages"])
    al = client.get("/api/ai/alerts", headers=h).json()
    mine = [a for a in al["alerts"] if a["project_id"] == late["id"]]
    assert mine and mine[0]["rule"] == "OVERDUE" and mine[0]["severity"] == "HIGH" and "3 day" in mine[0]["text"]
    assert {r["rule"] for r in al["rules"]} >= {"OVERDUE", "PAYMENT_BEHIND", "PO_LATE", "LOW_STOCK"}
    des = client.get("/api/dashboard", headers=hdr(client, "des12@test.com")).json()
    assert des["money_visible"] is False and des["cards"]["pipeline_value"] is None and des["cards"]["outstanding"] is None
    assert client.get("/api/reports/revenue", headers=hdr(client, "des12@test.com")).status_code == 403
    rows = client.get("/api/reports/projects", headers=h).json()
    me = next(r for r in rows if r["id"] == late["id"]); assert me["days_left"] < 0 and me["alerts"] >= 1


def test_revenue_report_counts_this_months_payment(client):
    h = hdr(client); p = project(client, h); rid, v = room_with_design(client, h, p["id"])
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    before = client.get("/api/reports/revenue", params={"months": 3}, headers=h).json()
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    client.post(f"/api/projects/{p['id']}/payments", json={"boq_id": b["id"], "amount": "12345.67", "received_on": date.today().isoformat(), "mode": "UPI"}, headers=h)
    after = client.get("/api/reports/revenue", params={"months": 3}, headers=h).json()
    from decimal import Decimal as D
    assert D(after["months"][-1]["received"]) - D(before["months"][-1]["received"]) == D("12345.67")
    assert D(after["months"][-1]["approved"]) - D(before["months"][-1]["approved"]) == D(b["totals"]["grand_total"])
    assert len(after["months"]) == 3


# ── Company settings ──────────────────────────────────────────────────────────
def test_company_settings_drive_the_pdfs(client):
    h = hdr(client)
    assert client.put("/api/settings/company", json={"name": "X"}, headers=hdr(client, "pm12@test.com")).status_code == 403
    assert client.put("/api/settings/company", json={"gstin": "27AAPFU0939F1ZW"}, headers=h).status_code == 422
    assert client.put("/api/settings/company", json={"quote_valid_days": "0"}, headers=h).status_code == 422
    assert client.put("/api/settings/company", json={"nope": 1}, headers=h).status_code == 422
    r = client.put("/api/settings/company", json={"name": "Shreeji Interiors LLP", "gstin": "27aapfu0939f1zv", "address": "CG Road, Ahmedabad"}, headers=h)
    assert r.status_code == 200 and r.json()["values"]["gstin"] == "27AAPFU0939F1ZV"
    assert client.put("/api/settings/company", json={"board_sku_18": "ply-bwp-18"}, headers=h).json()["values"]["board_sku_18"] == "PLY-BWP-18"   # SKUs are stored upper-case
    client.put("/api/settings/company", json={"board_sku_18": ""}, headers=h)
    p = project(client, h); rid, v = room_with_design(client, h, p["id"])
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    txt = pdf_text(client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content)
    assert "Shreeji Interiors LLP" in txt and "27AAPFU0939F1ZV" in txt and "CG Road" in txt
    client.put("/api/settings/company", json={"name": "InteriorIQ Design Studio", "gstin": "", "address": ""}, headers=h)


# ── Users ─────────────────────────────────────────────────────────────────────
def test_user_management_and_instant_deactivation(client):
    h = hdr(client); n = u(); email = f"newuser{n}@test.com"
    assert client.post("/api/users", json={"email": email, "full_name": "Neha", "role": "ESTIMATOR", "password": "short"}, headers=h).status_code == 422
    assert client.post("/api/users", json={"email": email, "full_name": "Neha", "role": "WIZARD", "password": "Strong123"}, headers=h).status_code == 422
    assert client.post("/api/users", json={"email": email, "full_name": "Neha", "role": "ESTIMATOR", "password": "Strong123"}, headers=hdr(client, "pm12@test.com")).status_code == 403
    nu = client.post("/api/users", json={"email": email.upper(), "full_name": "Neha", "role": "ESTIMATOR", "password": "Strong123"}, headers=h)
    assert nu.status_code == 201 and nu.json()["email"] == email; nu = nu.json()
    assert client.post("/api/users", json={"email": email, "full_name": "Dup", "role": "ESTIMATOR", "password": "Strong123"}, headers=h).status_code == 409
    assert client.post("/api/users", json={"email": f"c{n}@t.com", "full_name": "C", "role": "CLIENT", "password": "Strong123"}, headers=h).status_code == 422
    nh = hdr(client, email, "Strong123")
    assert client.get("/api/catalogue/items", headers=nh).status_code == 200
    client.patch(f"/api/users/{nu['id']}", json={"role": "INSTALLATION_MANAGER"}, headers=h)
    assert client.get("/api/auth/me", headers=nh).json()["role"] == "INSTALLATION_MANAGER"          # role change applies to the SAME token at once
    client.patch(f"/api/users/{nu['id']}", json={"is_active": False}, headers=h)
    assert client.get("/api/catalogue/items", headers=nh).status_code == 401                           # deactivation applies at once
    assert client.post("/api/auth/login", json={"email": email, "password": "Strong123"}).status_code == 401
    client.patch(f"/api/users/{nu['id']}", json={"is_active": True, "password": "NewPass456"}, headers=h)
    assert client.post("/api/auth/login", json={"email": email, "password": "NewPass456"}).status_code == 200
    me = client.get("/api/auth/me", headers=h).json()
    assert client.patch(f"/api/users/{me['sub']}", json={"is_active": False}, headers=h).status_code == 409
    others = [x for x in client.get("/api/users", headers=h).json() if x["role"] == "SUPER_ADMIN" and x["id"] != me["sub"] and x["is_active"]]
    if not others:
        assert client.patch(f"/api/users/{me['sub']}", json={"role": "ADMIN"}, headers=h).status_code == 409


def test_roles_matrix_and_system_and_ai(client):
    h = hdr(client)
    r = client.get("/api/settings/roles", headers=h).json()
    cap = {c["name"]: c["roles"] for c in r["capabilities"]}
    assert "QC_MANAGER" in cap["QC inspection"] and "SALES" not in cap["QC inspection"] and cap["Client portal (own projects only)"] == ["CLIENT"]
    s = client.get("/api/settings/system", headers=h).json()
    assert s["database"]["kind"] == "sqlite" and s["storage"]["writable"] is True and s["pdf"] is True and "users" in s["database"]["rows"]
    assert client.get("/api/settings/system", headers=hdr(client, "des12@test.com")).status_code == 403
    ai = client.get("/api/settings/ai", headers=h).json()
    assert any("AI Project Manager" in f["name"] for f in ai["features"]) and "ollama" in ai


# ── Contacts ──────────────────────────────────────────────────────────────────
def test_contacts(client):
    h = hdr(client); n = u()
    cl = client.post("/api/clients", json={"name": f"Contact Client {n}", "phone": f"9{n + 400000000:09d}"}, headers=h).json()
    assert client.post("/api/contacts", json={"client_id": cl["id"], "name": "Riya", "phone": "abc"}, headers=h).status_code == 422
    c = client.post("/api/contacts", json={"client_id": cl["id"], "name": "Riya Shah", "relation": "Architect", "phone": "+91 99887 76655"}, headers=h).json()
    assert any(x["id"] == c["id"] for x in client.get("/api/contacts", params={"q": "099887 76655"}, headers=h).json())
    assert client.patch(f"/api/contacts/{c['id']}", json={"relation": "Spouse"}, headers=h).json()["relation"] == "Spouse"
    assert client.delete(f"/api/contacts/{c['id']}", headers=h).status_code == 204
    assert client.get("/api/contacts", params={"client_id": cl["id"]}, headers=h).json() == []


# ── Client portal ─────────────────────────────────────────────────────────────
def test_client_portal_sees_only_its_own_projects(client):
    h = hdr(client); n = u()
    cl = client.post("/api/clients", json={"name": f"Portal Client {n}", "phone": f"9{n + 300000000:09d}"}, headers=h).json()
    mine = project(client, h, client_id=cl["id"]); other = project(client, h)
    rid, v = room_with_design(client, h, mine["id"])
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    client.post("/api/users", json={"email": f"portal{n}@test.com", "full_name": "Portal Client", "role": "CLIENT", "password": "Client123", "client_id": cl["id"]}, headers=h)
    ch = hdr(client, f"portal{n}@test.com", "Client123")
    assert [p["id"] for p in client.get("/api/portal/projects", headers=ch).json()] == [mine["id"]]
    assert [p["id"] for p in client.get("/api/projects", headers=ch).json()] == [mine["id"]]
    assert client.get(f"/api/portal/projects/{other['id']}", headers=ch).status_code == 404
    o = client.get(f"/api/portal/projects/{mine['id']}", headers=ch).json()
    assert o["quotations"] == []                                                  # drafts are internal
    assert client.post(f"/api/portal/boqs/{b['id']}/decision", json={"decision": "APPROVED"}, headers=ch).status_code == 404
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "SENT"}, headers=h)
    assert client.get(f"/api/portal/boqs/{b['id']}/quotation.pdf", headers=ch).status_code == 200
    r = client.post(f"/api/portal/boqs/{b['id']}/decision", json={"decision": "APPROVED", "note": "Go ahead"}, headers=ch).json()
    assert r["status"] == "APPROVED" and "By client" in r["status_note"]
    o = client.get(f"/api/portal/projects/{mine['id']}", headers=ch).json()
    assert o["status"] == "PROCUREMENT" and any("APPROVED" in e["text"] for e in o["timeline"])
    assert not any(e["text"].startswith("Room") for e in o["timeline"])           # internal events hidden
    for url in ("/api/quotations", "/api/dashboard", f"/api/projects/{mine['id']}/overview", "/api/clients"):
        assert client.get(url, headers=ch).status_code == 403
    assert client.get(f"/api/portal/projects/{mine['id']}", headers=hdr(client, "pm12@test.com")).status_code == 403   # staff use the staff screens


# ── Drawings + what-if ────────────────────────────────────────────────────────
def test_drawings_follow_the_saved_design(client):
    h = hdr(client); p = project(client, h); rid, v = room_with_design(client, h, p["id"])
    c = client.get(f"/api/rooms/{rid}/drawings/ceiling", headers=h).json()
    war = (50, 50, 2700, 600)
    assert c["version"] == v and c["lights"] and c["false_ceiling_height"] == 2600
    assert not any(l["type"] == "DOWNLIGHT" and 50 - 150 <= l["x"] <= 2750 + 150 and 50 - 150 <= l["y"] <= 650 + 150 for l in c["lights"])
    assert any(l["type"] == "SPOTLIGHT" and "Wardrobe" in l["label"] for l in c["lights"])
    e = client.get(f"/api/rooms/{rid}/drawings/electrical", headers=h).json()
    labels = [x["label"] for x in e["points"]]
    assert sum("Bedside" in l for l in labels) == 2 and any(l.startswith("AC point") for l in labels) and e["assumptions"]
    el = {w["wall"]: w for w in client.get(f"/api/rooms/{rid}/drawings/elevations", headers=h).json()["walls"]}
    assert [i["name"] for i in el["SOUTH"]["items"]] == ["6-Door Wardrobe"] and [i["name"] for i in el["NORTH"]["items"]] == ["King Bed — Walnut"]
    assert el["SOUTH"]["items"][0]["x"] == 4250 - (50 + 2700)
    for kind in ("ceiling", "electrical", "plan"):
        r = client.get(f"/api/rooms/{rid}/drawings/{kind}/dxf", headers=h); assert r.status_code == 200
        doc = ezdxf.read(io.StringIO(r.content.decode("utf-8", "replace")))
        assert len(list(doc.modelspace())) > 4
    assert client.get(f"/api/rooms/{rid}/drawings/elevation/dxf", params={"wall": "UP"}, headers=h).status_code == 422
    assert client.get(f"/api/rooms/{rid}/drawings/nonsense", headers=h).status_code == 404


def test_what_if_costing_never_changes_the_saved_boq(client):
    h = hdr(client); p = project(client, h); rid, v = room_with_design(client, h, p["id"])
    b = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()
    pv = client.post(f"/api/boqs/{b['id']}/preview", json={"discount_pct": "0", "margin_pct": "25"}, headers=h).json()
    assert pv["totals"]["grand_total"] != b["totals"]["grand_total"] and pv["saved_totals"]["grand_total"] == b["totals"]["grand_total"]
    assert client.get(f"/api/boqs/{b['id']}", headers=h).json()["totals"] == b["totals"]
    assert client.post(f"/api/boqs/{b['id']}/preview", json={"gst_pct": "101"}, headers=h).status_code == 422


# ── Site photos ───────────────────────────────────────────────────────────────
def test_site_photos_are_stored_not_ocrd(client):
    h = hdr(client); p = project(client, h)
    buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 120, 40)).save(buf, "PNG")
    r = client.post(f"/api/projects/{p['id']}/documents", data={"category": "site_photo"}, files={"file": ("wall.png", buf.getvalue(), "image/png")}, headers=h)
    assert r.status_code == 201 and r.json()["status"] == "STORED" and r.json()["category"] == "SITE_PHOTO"
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    assert client.post(f"/api/projects/{p['id']}/documents", data={"category": "SITE_PHOTO"}, files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h).status_code in (422, 415)
    assert [d["name"] for d in client.get(f"/api/projects/{p['id']}/documents", params={"category": "SITE_PHOTO"}, headers=h).json()] == ["wall.png"]
    assert client.get(f"/api/projects/{p['id']}/documents", params={"exclude_media": True}, headers=h).json() == []
    assert client.get(f"/api/documents/{r.json()['id']}", headers=h).json()["status"] == "STORED"
