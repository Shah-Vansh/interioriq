"""M31 recurring follow-ups: 'every N days' (1–90); done → next one booked N days after the due time (rolled past now if done late), same
kind/note/assignee, still repeating; stop_repeat ends it; cancel or Lost ends it; PATCH changes or clears the interval; history says so."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models import models as m


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


_n = [0]
def lead(c, h):
    _n[0] += 1; return c.post("/api/leads", json={"name": f"Repeat lead {_n[0]}", "phone": f"9{_n[0] + 730000000:09d}"}, headers=h).json()


def due(**kw): return (datetime.now(timezone.utc) + timedelta(**kw)).replace(microsecond=0)


def open_fus(c, h, lid): return [f for f in c.get(f"/api/leads/{lid}", headers=h).json()["follow_ups"] if f["status"] == "OPEN"]


def parse(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)     # stored times without a zone are UTC


def test_done_books_the_next_occurrence(client):
    h = hdr(client); l = lead(client, h); d0 = due(hours=2)
    f = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": d0.isoformat(), "kind": "CALL", "note": "Monthly check-in", "repeat_days": 14}, headers=h).json()
    assert f["repeat_days"] == 14
    r = client.post(f"/api/followups/{f['id']}/done", json={"outcome": "Spoke, still deciding"}, headers=h).json()
    nxt = r["next"]
    assert nxt and nxt["repeat_days"] == 14 and nxt["note"] == "Monthly check-in" and nxt["kind"] == "CALL" and nxt["assigned_to"] == f["assigned_to"]
    assert abs((parse(nxt["due_at"]) - (d0 + timedelta(days=14))).total_seconds()) < 2
    hist = " ".join(a["text"] or "" for a in client.get(f"/api/leads/{l['id']}", headers=h).json()["activity"])
    assert "repeating every 14 day(s)" in hist and "Repeating call booked" in hist
    # stop repeating: done without a new one
    r = client.post(f"/api/followups/{nxt['id']}/done", json={"outcome": "They signed elsewhere", "stop_repeat": True}, headers=h).json()
    assert r["next"] is None and open_fus(client, h, l["id"]) == []


def test_late_done_rolls_forward_and_manual_next_is_kept(client):
    h = hdr(client); l = lead(client, h)
    f = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": due(hours=1).isoformat(), "repeat_days": 1}, headers=h).json()
    db = SessionLocal()
    try: row = db.get(m.LeadFollowUp, f["id"]); row.due_at = datetime.now(timezone.utc) - timedelta(days=3, hours=1); db.commit()     # done 3 days late
    finally: db.close()
    nxt = client.post(f"/api/followups/{f['id']}/done", json={"outcome": "Called back late"}, headers=h).json()["next"]
    assert parse(nxt["due_at"]) > datetime.now(timezone.utc) and parse(nxt["due_at"]) < datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    # booking a manual next step as well keeps both (manual one is returned)
    r = client.post(f"/api/followups/{nxt['id']}/done", json={"outcome": "Asked for a site visit", "next": {"due_at": due(days=2).isoformat(), "kind": "VISIT"}}, headers=h).json()
    kinds = sorted(x["kind"] for x in open_fus(client, h, l["id"]))
    assert r["next"]["kind"] == "VISIT" and kinds == ["CALL", "VISIT"]


def test_patch_cancel_and_lost_end_the_repeat(client):
    h = hdr(client); l = lead(client, h)
    f = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": due(hours=3).isoformat(), "repeat_days": 7}, headers=h).json()
    assert client.patch(f"/api/followups/{f['id']}", json={"repeat_days": 30}, headers=h).json()["repeat_days"] == 30
    assert client.patch(f"/api/followups/{f['id']}", json={"repeat_days": None}, headers=h).json()["repeat_days"] is None
    assert client.post(f"/api/followups/{f['id']}/done", json={"outcome": "Done once"}, headers=h).json()["next"] is None
    for bad in (0, 91, -1):
        assert client.post(f"/api/leads/{l['id']}/followups", json={"due_at": due(hours=3).isoformat(), "repeat_days": bad}, headers=h).status_code == 422
    g = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": due(hours=3).isoformat(), "repeat_days": 7}, headers=h).json()
    client.post(f"/api/followups/{g['id']}/cancel", json={"reason": "Client asked us to stop"}, headers=h)
    assert open_fus(client, h, l["id"]) == []
    k = client.post(f"/api/leads/{l['id']}/followups", json={"due_at": due(hours=3).isoformat(), "repeat_days": 7}, headers=h).json()
    client.post(f"/api/leads/{l['id']}/stage", json={"stage": "LOST", "reason": "Budget too high"}, headers=h)
    assert open_fus(client, h, l["id"]) == []
