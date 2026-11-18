import io
import sqlite3

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.core.database import SessionLocal, upgrade_schema
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import crm as crmlib
from app.services.phone import PhoneError, normalize_phone


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for email, role in (("client2@test.com", "CLIENT"), ("sales@test.com", "SALES"), ("designer@test.com", "INTERIOR_DESIGNER")):
            if not db.query(m.User).filter_by(email=email).first():
                db.add(m.User(email=email, full_name=role.title(), role=role, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def uniq():
    _n[0] += 1; return _n[0]

def phone():   # a unique valid mobile per test
    return f"9{uniq() + 812340000:09d}"


# ── Phone normalisation ─────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", ["+91 98765-43210", "098765 43210", "9876543210", "(+91) 98765 43210", "+91 (98765) 43210", "0091 98765 43210",
                                 "91 98765 43210", "+91-98765-43210", "98765.43210"])
def test_every_way_of_typing_one_number_gives_the_same_value(raw):
    assert normalize_phone(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["abc", "98765", "12345678901234567", "+91 98765", "0000000000", "9999999999", "98765 4321x", "++919876543210",
                                 "98765+43210", "00000000000"])
def test_nonsense_is_rejected(raw):
    with pytest.raises(PhoneError): normalize_phone(raw)


def test_landline_with_std_code_and_foreign_numbers():
    assert normalize_phone("079 2658 1234") == "+917926581234"
    assert normalize_phone("+1 (415) 555-0132") == "+14155550132"
    assert normalize_phone("") is None and normalize_phone(None) is None


# ── Leads ───────────────────────────────────────────────────────────────────
def lead(c, h, **kw):
    body = {"name": "Vikram Agarwal", "phone": phone(), "city": "Ahmedabad", "requirement": "3BHK full interior", "budget": "2200000"} | kw
    r = c.post("/api/leads", json=body, headers=h); assert r.status_code == 201, r.text; return r.json()


def test_lead_starts_new_and_history_records_every_stage_change_and_note(client):
    h = hdr(client); l = lead(client, h)
    assert l["stage"] == "NEW" and l["budget"] == "2200000.00"
    for s in ("CONTACTED", "QUALIFIED", "SITE_VISIT"):
        assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": s}, headers=h).json()["stage"] == s
    assert client.post(f"/api/leads/{l['id']}/notes", json={"text": "  Wants walnut finish  "}, headers=h).status_code == 201
    d = client.get(f"/api/leads/{l['id']}", headers=h).json()
    kinds = [(a["kind"], a["from_stage"], a["to_stage"]) for a in d["activity"]]
    assert ("CREATED", None, "NEW") in kinds and ("STAGE", "NEW", "CONTACTED") in kinds and ("STAGE", "QUALIFIED", "SITE_VISIT") in kinds
    note = [a for a in d["activity"] if a["kind"] == "NOTE"][0]
    assert note["text"] == "Wants walnut finish" and note["user_name"] == "Admin User" and note["created_at"]
    assert len(d["activity"]) == 5


def test_all_nine_spec_stages_exist_and_unknown_stage_is_422(client):
    h = hdr(client)
    assert client.get("/api/crm/stages", headers=h).json() == ["NEW", "CONTACTED", "QUALIFIED", "SITE_VISIT", "DESIGN", "QUOTATION", "NEGOTIATION", "WON", "LOST"]
    l = lead(client, h)
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "MAYBE"}, headers=h).status_code == 422
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST", "reason": "Chose another firm"}, headers=h).status_code == 200


def test_moving_to_the_same_stage_logs_nothing(client):
    h = hdr(client); l = lead(client, h)
    client.post(f"/api/leads/{l['id']}/stage", json={"stage": "NEW"}, headers=h)
    assert len(client.get(f"/api/leads/{l['id']}", headers=h).json()["activity"]) == 1


def test_bad_lead_input_is_422_not_500(client):
    h = hdr(client)
    for body in ({"name": ""}, {"name": "X", "phone": "call me"}, {"name": "X", "email": "nope"}, {"name": "X", "budget": "-5"},
                 {"name": "X", "hacker": 1}, {"name": "X", "budget": "lots"}):
        assert client.post("/api/leads", json=body, headers=h).status_code == 422, body
    assert client.post("/api/leads/nope/notes", json={"text": "x"}, headers=h).status_code == 404
    l = lead(client, h)
    assert client.post(f"/api/leads/{l['id']}/notes", json={"text": "   "}, headers=h).status_code == 422


def test_search_finds_leads_by_phone_typed_differently(client):
    h = hdr(client); p = phone(); l = lead(client, h, phone=p, name="Search Target")
    hits = client.get("/api/leads", params={"q": f"+91 {p[:5]}-{p[5:]}"}, headers=h).json()
    assert [x["id"] for x in hits] == [l["id"]]
    assert any(x["id"] == l["id"] for x in client.get("/api/leads", params={"q": "search targ"}, headers=h).json())


def test_roles_client_is_blocked_designer_reads_only(client):
    h = hdr(client); l = lead(client, h)
    ch, dh, sh = hdr(client, "client2@test.com"), hdr(client, "designer@test.com"), hdr(client, "sales@test.com")
    assert client.get("/api/leads", headers=ch).status_code == 403 and client.get("/api/clients", headers=ch).status_code == 403
    assert client.get("/api/leads", headers=dh).status_code == 200
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "CONTACTED"}, headers=dh).status_code == 403
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "CONTACTED"}, headers=sh).status_code == 200
    assert client.get("/api/leads").status_code == 401


# ── Conversion ──────────────────────────────────────────────────────────────
def test_convert_creates_client_and_project_together(client):
    h = hdr(client); l = lead(client, h, email="vik@example.com")
    r = client.post(f"/api/leads/{l['id']}/convert", json={"project_number": f"IQ-CRM-{uniq()}"}, headers=h)
    assert r.status_code == 201, r.text; out = r.json()
    assert out["client_reused"] is False
    c = client.get(f"/api/clients/{out['client_id']}", headers=h).json()
    assert c["name"] == "Vikram Agarwal" and c["email"] == "vik@example.com" and c["projects"] == 1
    p = [p for p in client.get("/api/projects", headers=h).json() if p["id"] == out["project_id"]][0]
    assert p["client_id"] == out["client_id"] and p["client_name"] == "Vikram Agarwal" and p["budget"] == "2200000.00" and p["status"] == "SURVEY"
    d = client.get(f"/api/leads/{l['id']}", headers=h).json()
    assert d["stage"] == "WON" and d["project_number"] == p["project_number"] and d["activity"][0]["kind"] == "CONVERTED"
    # twice -> refused; and a converted lead can't be dragged out of Won
    assert client.post(f"/api/leads/{l['id']}/convert", json={"project_number": f"IQ-CRM-{uniq()}"}, headers=h).status_code == 409
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST"}, headers=h).status_code == 409


def test_convert_reuses_existing_client_with_same_phone_typed_differently(client):
    h = hdr(client); p = phone()
    existing = client.post("/api/clients", json={"name": "Pooja Desai", "phone": f"0{p[:5]} {p[5:]}"}, headers=h).json()
    l = lead(client, h, name="Pooja D", phone=f"+91-{p}")
    assert l["existing_client"]["id"] == existing["id"]
    out = client.post(f"/api/leads/{l['id']}/convert", json={"project_number": f"IQ-CRM-{uniq()}"}, headers=h).json()
    assert out["client_reused"] is True and out["client_id"] == existing["id"]


def test_convert_with_taken_project_number_creates_nothing(client):
    h = hdr(client); num = f"IQ-CRM-{uniq()}"
    client.post("/api/projects", json={"project_number": num, "name": "Existing"}, headers=h)
    p = phone(); l = lead(client, h, phone=p)
    db = SessionLocal(); before = db.query(m.Client).count(); db.close()
    assert client.post(f"/api/leads/{l['id']}/convert", json={"project_number": num}, headers=h).status_code == 409
    db = SessionLocal()
    assert db.query(m.Client).count() == before and db.query(m.Client).filter_by(phone_norm=normalize_phone(p)).count() == 0
    db.close()
    assert client.get(f"/api/leads/{l['id']}", headers=h).json()["stage"] == "NEW"


def test_convert_is_all_or_nothing_when_project_creation_fails(client, monkeypatch):
    """Break the step AFTER the client row is written: the client must not survive."""
    h = hdr(client); p = phone(); l = lead(client, h, phone=p)
    def boom(*a, **k): raise RuntimeError("disk full")
    monkeypatch.setattr(crmlib, "create_project", boom)
    with TestClient(app, raise_server_exceptions=False) as c2:
        assert c2.post(f"/api/leads/{l['id']}/convert", json={"project_number": f"IQ-CRM-{uniq()}"}, headers=h).status_code == 500
    db = SessionLocal()
    assert db.query(m.Client).filter_by(phone_norm=normalize_phone(p)).count() == 0
    lead_row = db.get(m.Lead, l["id"]); assert lead_row.client_id is None and lead_row.stage == "NEW"
    assert db.query(m.LeadActivity).filter_by(lead_id=l["id"], kind="CONVERTED").count() == 0
    db.close()


def test_lost_lead_cannot_be_converted(client):
    h = hdr(client); l = lead(client, h)
    client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST", "reason": "Chose another firm"}, headers=h)
    assert client.post(f"/api/leads/{l['id']}/convert", json={"project_number": f"IQ-CRM-{uniq()}"}, headers=h).status_code == 409


# ── Clients ─────────────────────────────────────────────────────────────────
def test_duplicate_client_phone_is_caught_however_typed(client):
    h = hdr(client); p = phone()
    a = client.post("/api/clients", json={"name": "Rekha Soni", "phone": f"+91 {p[:5]}-{p[5:]}"}, headers=h)
    assert a.status_code == 201
    for typed in (f"0{p}", f"(+91) {p[:5]} {p[5:]}", f"0091{p}"):
        r = client.post("/api/clients", json={"name": "Someone", "phone": typed}, headers=h)
        assert r.status_code == 409 and "Rekha Soni" in r.json()["detail"], typed
    other = client.post("/api/clients", json={"name": "Other", "phone": phone()}, headers=h).json()
    assert client.patch(f"/api/clients/{other['id']}", json={"phone": f"0{p}"}, headers=h).status_code == 409
    assert client.patch(f"/api/clients/{a.json()['id']}", json={"phone": f"0{p}"}, headers=h).status_code == 200   # own number is not a duplicate


def test_client_create_edit_search(client):
    h = hdr(client)
    c = client.post("/api/clients", json={"name": "  Arjun Kapoor ", "company": "Kapoor Exports", "city": "Surat", "phone": phone(),
                                          "address": "12 Ring Road", "email": "arjun@kapoor.in"}, headers=h).json()
    assert c["name"] == "Arjun Kapoor"
    e = client.patch(f"/api/clients/{c['id']}", json={"city": "Vadodara", "notes": "VIP"}, headers=h).json()
    assert e["city"] == "Vadodara" and e["company"] == "Kapoor Exports" and e["notes"] == "VIP"
    assert client.patch(f"/api/clients/{c['id']}", json={"name": ""}, headers=h).status_code == 422
    assert any(x["id"] == c["id"] for x in client.get("/api/clients", params={"q": "kapoor exp"}, headers=h).json())
    assert client.get("/api/clients/nope", headers=h).status_code == 404
    for bad in ({"name": "A", "phone": "12"}, {"name": "A", "email": "a@b"}, {"name": "A", "extra": 1}):
        assert client.post("/api/clients", json=bad, headers=h).status_code == 422


def test_project_client_can_be_linked_changed_and_unlinked(client):
    h = hdr(client)
    a = client.post("/api/clients", json={"name": "Client A"}, headers=h).json(); b = client.post("/api/clients", json={"name": "Client B"}, headers=h).json()
    p = client.post("/api/projects", json={"project_number": f"IQ-CRM-{uniq()}", "name": "Linked", "client_id": a["id"]}, headers=h).json()
    assert p["client_name"] == "Client A"
    assert client.patch(f"/api/projects/{p['id']}", json={"client_id": b["id"]}, headers=h).json()["client_name"] == "Client B"
    assert client.patch(f"/api/projects/{p['id']}", json={"client_id": None}, headers=h).json()["client_id"] is None
    assert client.patch(f"/api/projects/{p['id']}", json={"client_id": "ghost"}, headers=h).status_code == 404
    assert client.post("/api/projects", json={"project_number": f"IQ-CRM-{uniq()}", "name": "X", "client_id": "ghost"}, headers=h).status_code == 404
    assert client.patch(f"/api/projects/{p['id']}", json={"client_id": a["id"]}, headers=hdr(client, "designer@test.com")).status_code == 403


def test_quotation_pdf_prints_the_client(client):
    h = hdr(client)
    c = client.post("/api/clients", json={"name": "Sunita Shah", "company": "Shah Textiles", "address": "4 CG Road", "city": "Ahmedabad",
                                          "phone": "+91 99887 76655"}, headers=h).json()
    p = client.post("/api/projects", json={"project_number": f"IQ-CRM-{uniq()}", "name": "Quote", "client_id": c["id"]}, headers=h).json()
    rid = client.post(f"/api/projects/{p['id']}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for lbl, v in (("Length", 4250), ("Width", 3600)):
        client.put(f"/api/rooms/{rid}/measurements", json={"label": lbl, "value": v, "source": "USER_VERIFIED"}, headers=h)
    g = client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).json()
    v = client.post(f"/api/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=h).json()["version"]
    bid = client.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()["id"]
    pdf = client.get(f"/api/boqs/{bid}/quotation.pdf", headers=h).content
    text = "".join(pg.get_textpage().get_text_range() for pg in pdfium.PdfDocument(io.BytesIO(pdf)))
    for s in ("Sunita Shah", "Shah Textiles", "4 CG Road", "Ahmedabad", "+91 99887 76655"): assert s in text, s


# ── Database upgrade ────────────────────────────────────────────────────────
def test_old_database_is_upgraded_in_place_without_losing_data(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE clients (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, phone VARCHAR, email VARCHAR, city VARCHAR)")
    con.execute("CREATE TABLE projects (id VARCHAR PRIMARY KEY, project_number VARCHAR NOT NULL UNIQUE, name VARCHAR NOT NULL, client_id VARCHAR, status VARCHAR, budget NUMERIC(14,2), progress INTEGER)")
    con.execute("INSERT INTO clients VALUES ('c1','Old Client','98765 43210','o@x.com','Surat')")
    con.execute("INSERT INTO projects VALUES ('p1','IQ-OLD','Old Project','c1','LEAD',500000,10)")
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{path}")
    added = upgrade_schema(eng)
    assert "clients.phone_norm" in added and "clients.company" in added and "projects.created_at" in added
    insp = inspect(eng)
    assert {"leads", "lead_activities", "boqs"} <= set(insp.get_table_names())
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT name, phone, city FROM clients").fetchall() == [("Old Client", "98765 43210", "Surat")]
        assert c.exec_driver_sql("SELECT project_number, budget FROM projects").fetchall()[0][0] == "IQ-OLD"
    assert upgrade_schema(eng) == []          # running again changes nothing
    eng.dispose()
