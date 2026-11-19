"""M29 Excel catalogue import/export: .xlsx goes through the SAME validation as CSV (aliases, ₹/lakh formats, errors by Excel row number,
all-or-nothing apply); number cells come in without float noise; old .xls / broken files get a clear message; export.xlsx round-trips."""
import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c: yield c


def hdr(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}


def xlsx(rows) -> bytes:
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def post(c, h, data, apply=False, kind="FURNITURE", name="prices.xlsx"):
    return c.post("/api/catalogue/import", params={"kind": kind, "apply": apply},
                  files={"file": (name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, headers=h)


RUN = str(int(time.time()))[-6:]


def test_excel_preview_errors_by_row_and_apply(client):
    h = hdr(client)
    good = [["Item Code", "Item Name", "Category", "Rate", "Qty", "Length", "Width", "Height"],
            [f"XL-{RUN}-1", "Teak console", "Console", 18500, 4, 1200, 400, 800],
            [f"XL-{RUN}-2", "Walnut stool", "Stool", 3499.5, 10, 450.0, 450, 460],
            [], [f"XL-{RUN}-3", "Cane chair", "Chair", "₹ 1,24,000", 1, 600, 600, 900]]
    prev = post(client, h, xlsx(good)).json()
    assert prev["applied"] is False and prev["summary"]["create"] == 3 and prev["errors"] == [], prev
    bad = good[:2] + [[f"XL-{RUN}-4", "No size sofa", "Sofa", 5000, 1]]               # furniture without L×W×H
    res = post(client, h, xlsx(bad), apply=True).json()
    assert res["applied"] is False and res["errors"] and res["errors"][0]["row"] == 3       # Excel row number
    assert not any(i["sku"] == f"XL-{RUN}-1" for i in client.get("/api/catalogue/items?kind=FURNITURE", headers=h).json())   # all or nothing
    res = post(client, h, xlsx(good), apply=True).json(); assert res["applied"] is True
    items = {i["sku"]: i for i in client.get("/api/catalogue/items?kind=FURNITURE", headers=h).json()}
    assert items[f"XL-{RUN}-2"]["price"] == "3499.50" and items[f"XL-{RUN}-2"]["length_mm"] == 450 and items[f"XL-{RUN}-3"]["price"] == "124000.00"


def test_bad_workbooks_are_explained(client):
    h = hdr(client)
    r = post(client, h, b"\xd0\xcf\x11\xe0" + b"\x00" * 100, name="old.xls"); assert r.status_code == 422 and ".xlsx" in r.json()["detail"]
    r = post(client, h, b"PK\x03\x04garbage", name="broken.xlsx"); assert r.status_code == 422 and "not a readable Excel" in r.json()["detail"]
    r = post(client, h, xlsx([]), name="empty.xlsx"); assert r.status_code == 422 and "empty" in r.json()["detail"]
    r = post(client, h, xlsx([["Product", "Price"], ["x", 1]])); assert r.status_code == 422 and "Missing column" in r.json()["detail"]


def test_export_xlsx_round_trips(client):
    h = hdr(client)
    r = client.get("/api/catalogue/export.xlsx", params={"kind": "FURNITURE"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    ws = load_workbook(io.BytesIO(r.content)).active
    head = [c.value for c in ws[1]]; assert head[:3] == ["sku", "name", "kind"]
    price = ws.cell(row=2, column=head.index("price") + 1); assert isinstance(price.value, (int, float))
    res = post(client, h, r.content, name="catalogue-furniture.xlsx").json()
    assert res["errors"] == [] and res["summary"]["create"] == 0 and res["summary"]["update"] == 0, res["summary"]
