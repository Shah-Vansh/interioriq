"""M20 lead ownership + follow-ups: assignment rules, scheduling (never in the past, local 'today'), done-with-outcome + next step,
LOST needs a reason, archive/restore, lists and filters, owner change moves open follow-ups, AI alerts, dashboard counts, roles."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import followups as fups


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, r, n in (("sales20@test.com", "SALES", "Sneha Sales"), ("sales20b@test.com", "SALES", "Rohit Sales"), ("des20@test.com", "INTERIOR_DESIGNER", "Dev Designer"),
                        ("cli20@test.com", "CLIENT", "Client")):
            if not db.query(m.User).filter_by(email=e).first(): db.add(m.User(email=e, full_name=n, role=r, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def uid(email):
    db = SessionLocal()
    try: return db.query(m.User).filter_by(email=email).first().id
    finally: db.close()


_n = [0]
def lead(c, h, **kw):
    _n[0] += 1; return c.post("/api/leads", json={"name": f"Follow lead {_n[0]}", "phone": f"9{_n[0] + 510000000:09d}"} | kw, headers=h).json()


iso = lambda d: d.isoformat()
soon = lambda **kw: datetime.now(timezone.utc) + timedelta(**kw)


def test_local_today_buckets():
    now = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)                              # 11:30 in India
    assert fups.bucket(datetime(2026, 11, 18, 5, 59, tzinfo=timezone.utc), now) == "OVERDUE"
    assert fups.bucket(datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc), now) == "TODAY"     # 23:30 IST, still today
    assert fups.bucket(datetime(2026, 11, 18, 18, 31, tzinfo=timezone.utc), now) == "UPCOMING"  # 00:01 IST tomorrow
    assert fups.bucket(datetime(2026, 11, 18, 10, 0), now) == "TODAY"                          # naive stored values are UTC


def test_owner_assignment(client):
    h = hdr(client); l = lead(client, h)
    assert l["assigned_name"] == "Admin User" and l["follow_up_status"] == "NONE"            # whoever logs it owns it
    s = hdr(client, "sales20@test.com"); ls = lead(client, s); assert ls["assigned_name"] == "Sneha Sales"
    assert client.post(f"/api/leads/{l['id']}/assign", json={"user_id": uid("cli20@test.com")}, headers=h).status_code == 422
    assert client.post(f"/api/leads/{l['id']}/assign", json={"user_id": uid("des20@test.com")}, headers=h).status_code == 422   # can't edit leads → can't own them
    assert client.post(f"/api/leads/{l['id']}/assign", json={"user_id": "nobody"}, headers=h).status_code == 422
    r = client.post(f"/api/leads/{l['id']}/assign", json={"user_id": uid("sales20b@test.com")}, headers=h).json()
    assert r["assigned_name"] == "Rohit Sales"
    assert client.post(f"/api/leads/{l['id']}/assign", json={"user_id": None}, headers=h).json()["assigned_to"] is None
    acts = [a["text"] for a in client.get(f"/api/leads/{l['id']}", headers=h).json()["activity"] if a["kind"] == "ASSIGNED"]
    assert acts == ["Unassigned", "Assigned to Rohit Sales"]
    assert client.post(f"/api/leads/{l['id']}/assign", json={"user_id": None}, headers=hdr(client, "des20@test.com")).status_code == 403
    meta = client.get("/api/crm/meta", headers=h).json()
    assert {"Sneha Sales", "Rohit Sales"} <= {u["name"] for u in meta["assignable"]} and "Dev Designer" not in {u["name"] for u in meta["assignable"]}
    assert "Budget too high" in meta["lost_reasons"] and "VISIT" in meta["follow_up_kinds"]


def test_schedule_complete_and_book_the_next_step(client):
    h = hdr(client); l = lead(client, h)
    assert client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(hours=-2))}, headers=h).status_code == 422
    assert client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(days=1)), "kind": "PIGEON"}, headers=h).status_code == 422
    f = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(days=2)), "kind": "call", "note": "Discuss budget"}, headers=h).json()
    assert f["status"] == "OPEN" and f["bucket"] == "UPCOMING" and f["assigned_name"] == "Admin User" and f["kind"] == "CALL"
    got = client.get(f"/api/leads/{l['id']}", headers=h).json()
    assert got["follow_up_status"] == "UPCOMING" and got["open_follow_ups"] == 1 and got["follow_ups"][0]["note"] == "Discuss budget"
    assert client.post(f"/api/followups/{f['id']}/done", json={"outcome": "ok"}, headers=h).status_code == 422          # outcome needs words
    r = client.post(f"/api/followups/{f['id']}/done", json={"outcome": "Interested, wants a site visit", "stage": "SITE_VISIT",
                                                            "next": {"due_at": iso(soon(days=4)), "kind": "VISIT", "note": "Measure the flat"}}, headers=h).json()
    assert r["done"]["status"] == "DONE" and r["next"]["kind"] == "VISIT" and r["lead"]["stage"] == "SITE_VISIT" and r["lead"]["open_follow_ups"] == 1
    assert client.post(f"/api/followups/{f['id']}/done", json={"outcome": "again"}, headers=h).status_code == 409
    assert client.post(f"/api/followups/{r['next']['id']}/done", json={"outcome": "Done", "stage": "WON"}, headers=h).status_code == 422
    mv = client.patch(f"/api/followups/{r['next']['id']}", json={"due_at": iso(soon(days=6))}, headers=h).json(); assert mv["due_at"] > r["next"]["due_at"]
    assert client.post(f"/api/followups/{r['next']['id']}/cancel", json={"reason": "x"}, headers=h).status_code == 422
    assert client.post(f"/api/followups/{r['next']['id']}/cancel", json={"reason": "Client travelling"}, headers=h).json()["status"] == "CANCELLED"
    hist = " | ".join(a["text"] or "" for a in client.get(f"/api/leads/{l['id']}", headers=h).json()["activity"])
    assert "Call done: Interested" in hist and "Visit scheduled" in hist and "Visit cancelled: Client travelling" in hist and "Visit moved to" in hist


def test_lost_needs_a_reason_and_closes_follow_ups(client):
    h = hdr(client); l = lead(client, h)
    client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(days=1))}, headers=h)
    r = client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST"}, headers=h); assert r.status_code == 422 and "why" in str(r.json()["detail"])
    r = client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST", "reason": "Budget too high"}, headers=h).json()
    assert r["lost_reason"] == "Budget too high" and r["open_follow_ups"] == 0 and r["follow_up_status"] == "CLOSED"
    assert client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(days=1))}, headers=h).status_code == 409
    assert client.post(f"/api/leads/{l['id']}/stage", json={"stage": "QUALIFIED"}, headers=h).json()["lost_reason"] is None


def test_archive_restore_and_list_filters(client):
    h = hdr(client); s = hdr(client, "sales20@test.com")
    mine = lead(client, s); unowned = lead(client, h); client.post(f"/api/leads/{unowned['id']}/assign", json={"user_id": None}, headers=h)
    client.post(f"/api/leads/{mine['id']}/followups", json={"due_at": iso(soon(days=1))}, headers=s)
    ids = lambda **q: {x["id"] for x in client.get("/api/leads", params=q, headers=s).json()}
    assert mine["id"] in ids(assigned="me") and unowned["id"] not in ids(assigned="me")
    assert unowned["id"] in ids(assigned="unassigned") and unowned["id"] in ids(follow_up="NONE") and mine["id"] not in ids(follow_up="NONE")
    client.post(f"/api/leads/{unowned['id']}/archive", json={"archived": True}, headers=h)
    assert unowned["id"] not in ids() and unowned["id"] in ids(archived=True)
    assert client.post(f"/api/leads/{unowned['id']}/followups", json={"due_at": iso(soon(days=1))}, headers=h).status_code == 409
    assert client.post(f"/api/leads/{unowned['id']}/archive", json={"archived": False}, headers=h).json()["archived"] is False and unowned["id"] in ids()


def test_owner_change_moves_open_follow_ups_and_my_list(client):
    h = hdr(client); s = hdr(client, "sales20@test.com"); r2 = hdr(client, "sales20b@test.com")
    l = lead(client, s); f = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": iso(soon(days=1))}, headers=s).json()
    assert f["assigned_name"] == "Sneha Sales" and f["id"] in {x["id"] for x in client.get("/api/followups", params={"scope": "mine"}, headers=s).json()["items"]}
    client.post(f"/api/leads/{l['id']}/assign", json={"user_id": uid("sales20b@test.com")}, headers=h)
    assert f["id"] in {x["id"] for x in client.get("/api/followups", params={"scope": "mine"}, headers=r2).json()["items"]}
    assert f["id"] not in {x["id"] for x in client.get("/api/followups", params={"scope": "mine"}, headers=s).json()["items"]}
    team = client.get("/api/followups", params={"scope": "team"}, headers=h).json()
    assert any(x["id"] == f["id"] and x["lead_name"] == l["name"] for x in team["items"]) and team["counts"]["UPCOMING"] >= 1


def test_overdue_and_no_next_step_alerts_and_dashboard(client):
    h = hdr(client); s = hdr(client, "sales20@test.com")
    late = lead(client, s); f = client.post(f"/api/leads/{late['id']}/followups", json={"due_at": iso(soon(hours=1))}, headers=s).json()
    stale = lead(client, s)
    db = SessionLocal()
    db.get(m.LeadFollowUp, f["id"]).due_at = datetime.now(timezone.utc) - timedelta(days=4)          # the call was due 4 days ago
    db.get(m.Lead, stale["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=3)          # 3 days with no next step
    db.commit(); db.close()
    assert client.get(f"/api/leads/{late['id']}", headers=s).json()["follow_up_status"] == "OVERDUE"
    assert late["id"] in {x["id"] for x in client.get("/api/leads", params={"follow_up": "OVERDUE"}, headers=s).json()}
    od = client.get("/api/followups", params={"scope": "mine", "when": "overdue"}, headers=s).json()
    assert [x["id"] for x in od["items"]] == [f["id"]] and od["counts"]["OVERDUE"] == 1
    al = client.get("/api/ai/alerts", headers=hdr(client, "des20@test.com")).json()["alerts"]               # sales-pipeline alerts are for all staff
    a1 = next(a for a in al if a.get("lead_id") == late["id"]); a2 = next(a for a in al if a.get("lead_id") == stale["id"])
    assert a1["rule"] == "FOLLOW_UP_OVERDUE" and a1["severity"] == "HIGH" and "4 day(s)" in a1["text"] and "Sneha Sales" in a1["text"]
    assert a2["rule"] == "LEAD_NO_NEXT_STEP" and a2["severity"] == "LOW"
    d = client.get("/api/dashboard", headers=s).json()["cards"]
    assert d["my_followups_due"] >= 1 and d["followups_overdue"] >= 1
