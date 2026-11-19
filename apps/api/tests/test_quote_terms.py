"""M26 payment schedule + terms: company defaults (validated, must total 100%), each quotation keeps its own copy, editable until approved /
paid / invoiced, used by the PDF, the payment tracker and milestone invoices; amounts split on the server and sum exactly."""
from decimal import Decimal as D

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import models as m


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        if not db.query(m.User).filter_by(email="site26@test.com").first():
            db.add(m.User(email="site26@test.com", full_name="Site", role="SITE_ENGINEER", password_hash=hash_password("ChangeMe123!")))
        db.commit(); db.close()
        yield c
        c.delete("/api/settings/quote-terms", headers=hdr(c))


def hdr(c, email="admin@interioriq.com"):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]}


def pdf_text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))


_n = [0]
def job(c, h, approve=False):
    _n[0] += 1; n = _n[0]
    cl = c.post("/api/clients", json={"name": f"Terms client {n}", "phone": f"9{n + 260000000:09d}"}, headers=h).json()
    pid = c.post("/api/projects", json={"project_number": f"IQ-TRM-{n}", "name": "Terms flat", "client_id": cl["id"]}, headers=h).json()["id"]
    rid = c.post(f"/api/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=h).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"/api/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=h)
    objs = [dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]
    v = c.post(f"/api/rooms/{rid}/designs", json={"objects": objs}, headers=h).json()["version"]
    b = c.post(f"/api/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=h).json()
    if approve: c.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    return pid, b


THREE = [{"label": "Booking advance", "pct": "40"}, {"label": "Before delivery", "pct": "33.33"}, {"label": "On handover", "pct": "26.67"}]


def test_company_default_is_validated(client):
    h = hdr(client)
    d = client.get("/api/settings/quote-terms", headers=h).json()
    assert [r["label"] for r in d["schedule"]][0] == "Agreement signing" and sum(D(r["pct"]) for r in d["schedule"]) == 100 and len(d["terms"]) == 5
    for bad, word in (([{"label": "A", "pct": "60"}, {"label": "B", "pct": "30"}], "add up to 90"), ([], "at least one"),
                      ([{"label": "A", "pct": "50"}, {"label": "a", "pct": "50"}], "twice"), ([{"label": "A", "pct": "100.001"}], "at most 100"),
                      ([{"label": "A", "pct": "33.333"}, {"label": "B", "pct": "66.667"}], "2 decimals"), ([{"label": "", "pct": "100"}], "enter a name"),
                      ([{"label": "A", "pct": "x"}], "number"), ([{"label": "A", "pct": "-10"}, {"label": "B", "pct": "110"}], "more than 0")):
        r = client.put("/api/settings/quote-terms", json={"schedule": bad, "terms": []}, headers=h)
        assert r.status_code == 422 and word in r.json()["detail"], (bad, r.text)
    assert client.put("/api/settings/quote-terms", json={"schedule": THREE, "terms": ["x"]}, headers=hdr(client, "site26@test.com")).status_code == 403
    d = client.put("/api/settings/quote-terms", json={"schedule": THREE, "terms": ["  50% advance is non-refundable after production starts. ", ""]}, headers=h).json()
    assert d["customised"] and [r["pct"] for r in d["schedule"]] == ["40", "33.33", "26.67"] and d["terms"] == ["50% advance is non-refundable after production starts."]


def test_new_quotation_copies_the_default_and_keeps_it(client):
    h = hdr(client)
    client.put("/api/settings/quote-terms", json={"schedule": THREE, "terms": ["Booking is confirmed on the advance."]}, headers=h)
    _, b = job(client, h)
    t = client.get(f"/api/boqs/{b['id']}/terms", headers=h).json()
    assert t["own"] and [r["label"] for r in t["schedule"]] == ["Booking advance", "Before delivery", "On handover"] and t["editable"]
    assert sum(D(r["amount"]) for r in t["schedule"]) == D(b["totals"]["grand_total"])                  # exact to the paisa
    # changing the company default later does not touch this quotation
    client.delete("/api/settings/quote-terms", headers=h)
    assert [r["label"] for r in client.get(f"/api/boqs/{b['id']}/terms", headers=h).json()["schedule"]][0] == "Booking advance"
    pdf = pdf_text(client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content)
    assert "Booking advance" in pdf and "33.33" in pdf and "Booking is confirmed on the advance." in pdf and "Agreement signing" not in pdf


def test_edit_a_quotation_then_it_drives_payments_and_invoices(client):
    h = hdr(client); pid, b = job(client, h)
    two = [{"label": "Advance", "pct": "50"}, {"label": "Balance on installation", "pct": "50"}]
    r = client.put(f"/api/boqs/{b['id']}/terms", json={"schedule": two, "terms": ["Prices include delivery within Mumbai."]}, headers=h)
    assert r.status_code == 200 and [x["amount"] for x in r.json()["schedule"]] == [f"{D(b['totals']['grand_total']) / 2:.2f}"] * 2
    assert client.put(f"/api/boqs/{b['id']}/terms", json={"schedule": [{"label": "A", "pct": "99"}]}, headers=h).status_code == 422
    assert client.put(f"/api/boqs/{b['id']}/terms", json={"schedule": two}, headers=hdr(client, "site26@test.com")).status_code == 403
    tl = client.get(f"/api/projects/{pid}/timeline", headers=h)
    if tl.status_code == 200: assert "payment schedule" in tl.text
    pdf = pdf_text(client.get(f"/api/boqs/{b['id']}/quotation.pdf", headers=h).content)
    assert "Balance on installation" in pdf and "Prices include delivery within Mumbai." in pdf
    client.post(f"/api/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=h)
    s = client.get(f"/api/projects/{pid}/payments", headers=h).json()
    assert [x["stage"] for x in s["schedule"]] == ["Advance", "Balance on installation"] and [x["pct"] for x in s["schedule"]] == ["50", "50"]
    inv = client.get(f"/api/projects/{pid}/invoices", headers=h).json()["quotations"][0]
    assert [x["stage"] for x in inv["milestones"]] == ["Advance", "Balance on installation"]
    # approved → final
    t = client.get(f"/api/boqs/{b['id']}/terms", headers=h).json()
    assert not t["editable"] and "approved" in t["locked_reason"]
    assert client.put(f"/api/boqs/{b['id']}/terms", json={"schedule": two}, headers=h).status_code == 409


def test_old_quotations_keep_the_builtin_schedule(client):
    h = hdr(client); pid, b = job(client, h, approve=True)
    db = SessionLocal()
    try:
        row = db.get(m.Boq, b["id"]); p = dict(row.params); p.pop("payment_schedule"); p.pop("terms"); row.params = p; db.commit()     # as saved before M26
    finally: db.close()
    t = client.get(f"/api/boqs/{b['id']}/terms", headers=h).json()
    assert not t["own"] and [r["pct"] for r in t["schedule"]] == ["30", "20", "25", "20", "5"] and len(t["terms"]) == 5
    assert [x["stage"] for x in client.get(f"/api/projects/{pid}/payments", headers=h).json()["schedule"]][0] == "Agreement signing"
