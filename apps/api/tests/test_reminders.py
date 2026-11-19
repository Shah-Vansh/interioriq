"""M25 follow-up reminders: settings (admin, validated, off by default), 'due soon' emails (once, multi-server safe, again after a
reschedule/reassign, not for self-booked ones), the morning summary (once per local day after the hour), SKIPPED when email can't go out,
WhatsApp links to the lead and to the assignee, editable templates."""
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m
from app.services import notify, reminders

SALES, SALES2 = "sales25@test.com", "sales25b@test.com"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        for e, n, ph in ((SALES, "Meera Sales", None), (SALES2, "Arjun Sales", "+91 98250 11111"), ("des25@test.com", "Dev Designer", None)):
            if not db.query(m.User).filter_by(email=e).first():
                db.add(m.User(email=e, full_name=n, role="INTERIOR_DESIGNER" if e.startswith("des") else "SALES", phone=ph, password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close(); yield c
        db = SessionLocal(); reminders.save(db, dict(reminders.DEFAULTS), "test"); db.close()       # leave it off for other test modules


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")


def hdr(c, e="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "ChangeMe123!"}).json()["access_token"]}


def uid(email):
    db = SessionLocal()
    try: return db.query(m.User).filter_by(email=email).first().id
    finally: db.close()


_n = [0]
def lead(c, h, assigned_to=None, **kw):
    _n[0] += 1; l = c.post("/api/leads", json={"name": f"Reminder lead {_n[0]}", "phone": f"9{_n[0] + 620000000:09d}"} | kw, headers=h).json()
    if assigned_to: assert c.post(f"/api/leads/{l['id']}/assign", json={"user_id": assigned_to}, headers=h).status_code == 200
    return l


def fu(c, h, lid, minutes, **kw):
    r = c.post(f"/api/leads/{lid}/followups", json={"due_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(), "kind": "CALL"} | kw, headers=h)
    assert r.status_code == 201, r.text; return r.json()


def msgs(kind, ref):
    db = SessionLocal()
    try: return db.query(m.Message).filter_by(kind=kind, ref_id=ref).all()
    finally: db.close()


def run(fn, *a, **kw):
    db = SessionLocal()
    try: return fn(db, *a, **kw)
    finally: db.close()


def test_settings_are_off_by_default_validated_and_admin_only(client):
    h = hdr(client)
    s = client.get("/api/notifications/followup-reminders", headers=hdr(client, SALES)).json()
    assert s["enabled"] is False and s["before_minutes"] == 30 and s["digest_hour"] == 9 and 0 in s["before_choices"]
    assert any(p["name"] == "Meera Sales" for p in s["people"])
    assert client.put("/api/notifications/followup-reminders", json={"enabled": True}, headers=hdr(client, SALES)).status_code == 403
    for bad in ({"before_minutes": 7}, {"digest_hour": 24}, {"enabled": "yes"}, {"nope": 1}, {"digest_hour": True}):
        assert client.put("/api/notifications/followup-reminders", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/notifications/followup-reminders/run", headers=h).status_code == 409          # off
    s = client.put("/api/notifications/followup-reminders", json={"enabled": True, "before_minutes": 60, "digest_hour": 8}, headers=h).json()
    assert s["enabled"] and s["before_minutes"] == 60 and s["digest_hour"] == 8


def test_due_soon_reminder_once_and_again_after_reschedule(client, smtp):
    h = hdr(client); run(reminders.save, {"enabled": True, "before_minutes": 30}, "t")
    l = lead(client, h, assigned_to=uid(SALES))
    near = fu(client, h, l["id"], 20, note="Discuss the kitchen")           # booked by the admin for Meera → reminded
    far = fu(client, h, l["id"], 180)                                        # outside the window
    run(reminders.send_due)
    [x] = msgs("FOLLOWUP_REMINDER", near["id"])
    assert x.status == "QUEUED" and x.to == SALES and x.channel == "EMAIL" and x.trigger == "AUTO"
    assert l["name"] in x.subject and "Discuss the kitchen" in x.body and "https://wa.me/91" in x.body and "/crm/followups" in x.body
    assert msgs("FOLLOWUP_REMINDER", far["id"]) == []
    run(reminders.send_due); run(reminders.send_due)
    assert len(msgs("FOLLOWUP_REMINDER", near["id"])) == 1                   # never twice
    got = client.get(f"/api/leads/{l['id']}", headers=h).json()["follow_ups"]
    assert next(f for f in got if f["id"] == near["id"])["reminded_at"]
    # moving it later clears the reminder; it fires again once the new time is near
    new_due = datetime.now(timezone.utc) + timedelta(minutes=120)
    assert client.patch(f"/api/followups/{near['id']}", json={"due_at": new_due.isoformat()}, headers=h).status_code == 200
    run(reminders.send_due); assert len(msgs("FOLLOWUP_REMINDER", near["id"])) == 1
    run(reminders.send_due, new_due - timedelta(minutes=10)); assert len(msgs("FOLLOWUP_REMINDER", near["id"])) == 2
    # reassigning sends the new person their own reminder
    client.patch(f"/api/followups/{near['id']}", json={"assigned_to": uid(SALES2)}, headers=h)
    run(reminders.send_due, new_due - timedelta(minutes=5))
    assert [x.to for x in msgs("FOLLOWUP_REMINDER", near["id"])][-1] == SALES2


def test_claim_is_exclusive_and_self_booked_or_closed_are_not_reminded(client, smtp):
    h = hdr(client); hs = hdr(client, SALES); run(reminders.save, {"enabled": True, "before_minutes": 30}, "t")
    l = lead(client, h, assigned_to=uid(SALES))
    mine = fu(client, hs, l["id"], 10)                                      # Meera booked it herself 10 min ahead: she knows
    run(reminders.send_due); assert msgs("FOLLOWUP_REMINDER", mine["id"]) == []
    l2 = lead(client, h, assigned_to=uid(SALES)); f2 = fu(client, h, l2["id"], 15)
    client.post(f"/api/leads/{l2['id']}/stage", json={"stage": "LOST", "reason": "Budget too high"}, headers=h)   # cancels it
    run(reminders.send_due); assert msgs("FOLLOWUP_REMINDER", f2["id"]) == []
    # two servers racing: the conditional UPDATE lets exactly one win
    l3 = lead(client, h, assigned_to=uid(SALES)); f3 = fu(client, h, l3["id"], 15)
    a, b = SessionLocal(), SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        n1 =a.query(m.LeadFollowUp).filter(m.LeadFollowUp.id == f3["id"], m.LeadFollowUp.reminded_at.is_(None)).update({"reminded_at": now}, synchronize_session=False); a.commit()
        n2 = b.query(m.LeadFollowUp).filter(m.LeadFollowUp.id == f3["id"], m.LeadFollowUp.reminded_at.is_(None)).update({"reminded_at": now}, synchronize_session=False); b.commit()
        assert (n1, n2) == (1, 0)
    finally: a.close(); b.close()


def test_skipped_with_reason_when_email_is_not_set_up(client, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    h = hdr(client); run(reminders.save, {"enabled": True, "before_minutes": 30}, "t")
    l = lead(client, h, assigned_to=uid(SALES)); f = fu(client, h, l["id"], 20)
    run(reminders.send_due)
    [x] = msgs("FOLLOWUP_REMINDER", f["id"])
    assert x.status == "SKIPPED" and "not set up" in x.error


def test_morning_summary_once_per_day_after_the_hour(client, smtp):
    h = hdr(client); run(reminders.save, {"enabled": True, "digest": True, "digest_hour": 9, "before_minutes": 0}, "t")
    db = SessionLocal(); lock = db.get(m.JobLock, "followup_digest")
    if lock: db.delete(lock); db.commit()
    db.close()
    l = lead(client, h, assigned_to=uid(SALES2))
    f = fu(client, h, l["id"], 60, note="Bring samples")
    tz = timezone(timedelta(minutes=settings.COMPANY_UTC_OFFSET_MIN))
    due_local = datetime.fromisoformat(f["due_at"].replace("Z", "+00:00")).astimezone(tz)
    day = due_local.replace(hour=8, minute=0, second=0, microsecond=0)
    if due_local.hour < 9: pytest.skip("the follow-up falls before the summary hour today")
    assert run(reminders.send_digests, day) is None                                  # 08:00 local: too early
    sent = run(reminders.send_digests, day.replace(hour=9, minute=5))
    assert sent and sent >= 1
    [x] = msgs("FOLLOWUP_DIGEST", uid(SALES2))
    assert x.to == SALES2 and "TODAY (" in x.body and l["name"] in x.body and "Bring samples" in x.body and " today" in x.subject
    assert run(reminders.send_digests, day.replace(hour=15)) is None                  # same day: already sent
    # the next day it goes again, and yesterday's call now shows as overdue
    nxt = run(reminders.send_digests, day.replace(hour=9) + timedelta(days=1))
    assert nxt and nxt >= 1
    last = sorted(msgs("FOLLOWUP_DIGEST", uid(SALES2)), key=lambda r: r.created_at)[-1]
    assert "OVERDUE (" in last.body and l["name"] in last.body


def test_digest_text_lists_overdue_and_today_and_nothing_for_an_empty_day(client):
    db = SessionLocal()
    try:
        u = db.query(m.User).filter_by(email="des25@test.com").first()
        assert reminders.digest(db, u, datetime.now(timezone.utc)) is None             # nothing assigned
    finally: db.close()


def test_run_now_endpoint(client, smtp):
    h = hdr(client); run(reminders.save, {"enabled": True, "before_minutes": 30, "digest": True}, "t")
    db = SessionLocal(); lock = db.get(m.JobLock, "followup_digest")
    if lock: lock.value = ""; db.commit()
    db.close()
    l = lead(client, h, assigned_to=uid(SALES)); f = fu(client, h, l["id"], 25)
    r = client.post("/api/notifications/followup-reminders/run", headers=h).json()
    assert r["due_soon"] >= 1 and r["digests"] is not None and r["digests"] >= 1
    assert any(x["kind"] == "FOLLOWUP_DIGEST" for x in r["log"]) and len(msgs("FOLLOWUP_REMINDER", f["id"])) == 1
    r2 = client.post("/api/notifications/followup-reminders/run", headers=h).json()
    assert r2["digests"] is None and r2["digest_already_sent"] is True                # once a day
    assert client.post("/api/notifications/followup-reminders/run", headers=hdr(client, SALES)).status_code == 403


def test_whatsapp_to_the_lead_and_to_the_assignee(client):
    h = hdr(client)
    l = lead(client, h, name="Kavya Shah", phone="98765 43210", assigned_to=uid(SALES)); f = fu(client, h, l["id"], 300)
    d = client.get(f"/api/followups/{f['id']}/whatsapp?target=LEAD", headers=h).json()
    assert d["phone"] == "98765 43210" and "Kavya Shah" in d["text"] and d["problem"] is None
    r = client.post(f"/api/followups/{f['id']}/whatsapp", json={"target": "LEAD", "text": d["text"]}, headers=h)
    assert r.status_code == 201 and r.json()["whatsapp_url"].startswith("https://wa.me/919876543210?text=")
    assert "Kavya Shah" in unquote(r.json()["whatsapp_url"])
    [x] = msgs("FOLLOWUP_WHATSAPP", f["id"]); assert x.channel == "WHATSAPP" and x.status == "LINK"
    hist = client.get(f"/api/leads/{l['id']}", headers=h).json()["activity"]
    assert any("WhatsApp opened to the lead" in (a.get("text") or "") for a in hist)
    # Meera has no phone → a clear message; Arjun has one → a reminder link
    a = client.get(f"/api/followups/{f['id']}/whatsapp?target=ASSIGNEE", headers=h).json()
    assert a["phone"] is None and "Settings → Users" in a["problem"]
    assert client.post(f"/api/followups/{f['id']}/whatsapp", json={"target": "ASSIGNEE", "text": "x"}, headers=h).status_code == 409
    client.patch(f"/api/followups/{f['id']}", json={"assigned_to": uid(SALES2)}, headers=h)
    a = client.get(f"/api/followups/{f['id']}/whatsapp?target=ASSIGNEE", headers=h).json()
    assert a["name"] == "Arjun Sales" and "Kavya Shah" in a["text"]
    r = client.post(f"/api/followups/{f['id']}/whatsapp", json={"target": "ASSIGNEE", "text": a["text"]}, headers=h).json()
    assert r["whatsapp_url"].startswith("https://wa.me/919825011111?text=")
    assert client.post(f"/api/followups/{f['id']}/whatsapp", json={"target": "BOSS", "text": "x"}, headers=h).status_code == 422
    assert client.post(f"/api/followups/{f['id']}/whatsapp", json={"target": "LEAD", "text": "x", "phone": "12"}, headers=h).status_code == 422
    assert client.get(f"/api/followups/{f['id']}/whatsapp", headers=hdr(client, "des25@test.com")).status_code == 403


def test_reminder_templates_are_editable(client, smtp):
    h = hdr(client)
    t = client.get("/api/notifications/templates", headers=h).json()
    assert {"FOLLOWUP_REMINDER", "FOLLOWUP_DIGEST", "FOLLOWUP_WHATSAPP"} <= set(t)
    assert client.put("/api/notifications/templates/FOLLOWUP_DIGEST", json={"subject": "x", "body": "$client"}, headers=h).status_code == 422
    client.put("/api/notifications/templates/FOLLOWUP_REMINDER", json={"subject": "Yaad dilana: $lead", "body": "$name, call $lead on $phone at $due."}, headers=h)
    run(reminders.save, {"enabled": True, "before_minutes": 30}, "t")
    l = lead(client, h, assigned_to=uid(SALES)); f = fu(client, h, l["id"], 20)
    run(reminders.send_due)
    [x] = msgs("FOLLOWUP_REMINDER", f["id"])
    assert x.subject == f"Yaad dilana: {l['name']}" and x.body.startswith("Meera, call")
    client.delete("/api/notifications/templates/FOLLOWUP_REMINDER", headers=h)
