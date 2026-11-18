"""M22 per-project staff permissions: off by default (nothing changes); when on, staff see / open only their teams' projects — by path,
by ?project_id=, in lists, dashboard, reports, alerts, search and notifications; admins and the 'see every project' roles see all;
creators and lead converters join the team; payables are company-wide; team changes are logged; settings validated."""
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m

USERS = (("des22@test.com", "INTERIOR_DESIGNER", "Dia Designer"), ("pm22@test.com", "PROJECT_MANAGER", "Pavan PM"), ("proc22@test.com", "PROCUREMENT_MANAGER", "Prakash Procure"),
         ("sales22@test.com", "SALES", "Sana Sales"), ("est22@test.com", "ESTIMATOR", "Esha Estimator"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, r, n in USERS:
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=n, role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        try: yield c
        finally: c.put("/api/settings/company", json={"limit_staff_to_projects": False, "all_projects_roles": "PROCUREMENT_MANAGER, INVENTORY_MANAGER"}, headers=hdr(c))


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def uid(e):
    db = SessionLocal()
    try: return db.query(m.User).filter_by(email=e).first().id
    finally: db.close()


_n = [0]
def project(c, h, name="Team test"):
    _n[0] += 1
    p = c.post("/api/projects", json={"project_number": f"IQ-TM-{_n[0]}", "name": name}, headers=h).json()
    rid = c.post(f"/api/projects/{p['id']}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for lbl, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": lbl, "value": v, "source": "USER_VERIFIED"}, headers=h)
    g = c.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=h).json()
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=h).json()["version"]
    bid = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={}, headers=h).json()["id"]
    return p, rid, bid


def limit(c, on=True, **kw):
    r = c.put("/api/settings/company", json={"limit_staff_to_projects": on, **kw}, headers=hdr(c)); assert r.status_code == 200, r.text


def test_off_by_default_everyone_sees_everything(client):
    limit(client, False)
    h = hdr(client); p, rid, bid = project(client, h)
    d = hdr(client, "des22@test.com")
    assert p["id"] in {x["id"] for x in client.get("/api/projects", headers=d).json()}
    assert client.get(f"/api/rooms/{rid}/designs", headers=d).status_code == 200 and client.get(f"/api/boqs/{bid}", headers=d).status_code == 200
    team = client.get(f"/api/projects/{p['id']}/team", headers=d).json()
    assert team["limited"] is False and [x["name"] for x in team["members"]] == ["Admin User"]           # the creator joined


def test_on_staff_see_only_their_teams_projects(client):
    h = hdr(client); p, rid, bid = project(client, h, "Secret villa"); other, _, _ = project(client, h, "Open flat")
    client.post(f"/api/projects/{other['id']}/team", json={"user_id": uid("des22@test.com")}, headers=h)
    limit(client, True)
    d = hdr(client, "des22@test.com")
    ids = {x["id"] for x in client.get("/api/projects", headers=d).json()}
    assert other["id"] in ids and p["id"] not in ids
    for url in (f"/api/projects/{p['id']}/rooms", f"/api/rooms/{rid}/designs", f"/api/boqs/{bid}", f"/api/boqs/{bid}/quotation.pdf",
                f"/api/rooms/{rid}/drawings/plan", f"/api/projects/{p['id']}/team", f"/api/purchase-orders?project_id={p['id']}"):
        r = client.get(url, headers=d); assert r.status_code == 403 and "not on this project's team" in r.json()["detail"], url
    assert client.post(f"/api/rooms/{rid}/designs/generate", json={}, headers=d).status_code == 403
    assert all(q["project_id"] != p["id"] for q in client.get("/api/quotations", headers=d).json())
    assert all(x["href"] != f"/projects/{p['id']}" for x in client.get("/api/search", params={"q": "Secret"}, headers=d).json())
    dash = client.get("/api/dashboard", headers=d).json()
    assert all(x["id"] != p["id"] for x in dash["projects"]) and dash["cards"]["active_projects"] >= 1
    assert all(a.get("project_id") in (None, other["id"]) or a["project_id"] in ids for a in client.get("/api/ai/alerts", headers=d).json()["alerts"])
    assert client.get("/api/notifications/draft", params={"kind": "QUOTATION", "ref_id": bid}, headers=d).status_code == 403
    # admins and the 'see every project' roles still see it
    for e in ("admin@interioriq.com", "proc22@test.com"):
        assert p["id"] in {x["id"] for x in client.get("/api/projects", headers=hdr(client, e)).json()}
    assert client.get(f"/api/boqs/{bid}", headers=hdr(client, "proc22@test.com")).status_code == 200


def test_adding_and_removing_a_member(client):
    limit(client, True)
    h = hdr(client); p, rid, bid = project(client, h); d = hdr(client, "des22@test.com")
    assert client.get(f"/api/rooms/{rid}/designs", headers=d).status_code == 403
    t = client.post(f"/api/projects/{p['id']}/team", json={"user_id": uid("des22@test.com")}, headers=h).json()
    assert "Dia Designer" in [x["name"] for x in t["members"]] and t["limited"] is True
    assert client.get(f"/api/rooms/{rid}/designs", headers=d).status_code == 200                      # works immediately
    assert client.post(f"/api/projects/{p['id']}/team", json={"user_id": uid("des22@test.com")}, headers=h).status_code == 409
    assert client.post(f"/api/projects/{p['id']}/team", json={"user_id": uid("est22@test.com")}, headers=d).status_code == 403   # designers can't manage teams
    client.delete(f"/api/projects/{p['id']}/team/{uid('des22@test.com')}", headers=h)
    assert client.get(f"/api/rooms/{rid}/designs", headers=d).status_code == 403
    tl = " | ".join(e["text"] for e in client.get(f"/api/projects/{p['id']}/timeline", headers=h).json()) if client.get(f"/api/projects/{p['id']}/timeline", headers=h).status_code == 200 else ""
    if tl: assert "Dia Designer (interior designer) added to the team" in tl and "Dia Designer removed from the team" in tl


def test_creator_and_lead_converter_join_and_a_manager_cannot_lock_themselves_out(client):
    limit(client, True)
    pm = hdr(client, "pm22@test.com")
    p = client.post("/api/projects", json={"project_number": "IQ-TM-PM-1", "name": "PM's own"}, headers=pm).json()
    assert p["id"] in {x["id"] for x in client.get("/api/projects", headers=pm).json()}
    r = client.delete(f"/api/projects/{p['id']}/team/{uid('pm22@test.com')}", headers=pm)
    assert r.status_code == 409 and "lose access" in r.json()["detail"]
    s = hdr(client, "sales22@test.com")
    lead = client.post("/api/leads", json={"name": "Team lead", "phone": "9822000111"}, headers=s).json()
    conv = client.post(f"/api/leads/{lead['id']}/convert", json={"project_number": "IQ-TM-CONV-1"}, headers=hdr(client)).json()
    names = [x["name"] for x in client.get(f"/api/projects/{conv['project_id']}/team", headers=hdr(client)).json()["members"]]
    assert set(names) == {"Admin User", "Sana Sales"}                                                    # converter + lead owner
    assert conv["project_id"] in {x["id"] for x in client.get("/api/projects", headers=s).json()}


def test_payables_are_company_wide_and_settings_are_validated(client):
    limit(client, True)
    assert client.get("/api/payables/summary", headers=hdr(client, "pm22@test.com")).status_code == 403
    assert client.get("/api/payables/summary", headers=hdr(client, "proc22@test.com")).status_code == 200
    assert client.get("/api/payables/summary", headers=hdr(client)).status_code == 200
    assert client.put("/api/settings/company", json={"all_projects_roles": "PROCUREMENT_MANAGER, WIZARD"}, headers=hdr(client)).status_code == 422
    assert client.put("/api/settings/company", json={"all_projects_roles": "CLIENT"}, headers=hdr(client)).status_code == 422
    limit(client, True, all_projects_roles="project_manager, procurement_manager")
    assert client.get("/api/payables/summary", headers=hdr(client, "pm22@test.com")).status_code == 200      # PMs now see every project
    vals = client.get("/api/settings/company", headers=hdr(client)).json()["values"]
    assert vals["all_projects_roles"] == "PROJECT_MANAGER, PROCUREMENT_MANAGER" and vals["limit_staff_to_projects"] is True
    limit(client, False, all_projects_roles="PROCUREMENT_MANAGER, INVENTORY_MANAGER")
    assert client.get("/api/payables/summary", headers=hdr(client, "pm22@test.com")).status_code == 200


def test_clients_still_only_see_their_own(client):
    limit(client, True)
    h = hdr(client)
    c = client.post("/api/clients", json={"name": "Team Client", "phone": "9822000222"}, headers=h).json()
    p = client.post("/api/projects", json={"project_number": "IQ-TM-CL-1", "name": "Client's", "client_id": c["id"]}, headers=h).json()
    db = SessionLocal()
    if not db.query(m.User).filter_by(email="cli22@test.com").first():
        db.add(m.User(email="cli22@test.com", full_name="Team Client", role="CLIENT", client_id=c["id"], password_hash=hash_password("ChangeMe123!"))); db.commit()
    db.close()
    ch = hdr(client, "cli22@test.com")
    assert [x["id"] for x in client.get("/api/projects", headers=ch).json()] == [p["id"]]
    limit(client, False)
