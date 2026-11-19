"""Real-browser test of M34: per-supplier prices in the catalogue drawer (the server picks the cheapest valid quote; ending it falls back to
the default supplier) and Finance → Accounting export (summary counts, Tally XML that balances, day-book CSV, ledger names saved)."""
import os, sys, tempfile, time
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
A = c.post(f"{API}/suppliers", json={"name": f"Default Ply {RUN}", "phone": f"93{RUN}11"[:10]}, headers=H).json()
B = c.post(f"{API}/suppliers", json={"name": f"Cheap Ply {RUN}", "phone": f"93{RUN}22"[:10]}, headers=H).json()
SKU = f"PLY-Q-{RUN}"
item = c.post(f"{API}/catalogue/items", json={"sku": SKU, "name": "BWP ply 18mm", "kind": "MATERIAL", "category": "Plywood", "unit": "sheet", "price": "3200", "cost_price": "2800",
                                               "supplier_id": A["id"]}, headers=H).json()
# something to export today: a plain invoice + a receipt
c.put(f"{API}/settings/company", json={"gst_enabled": False}, headers=H)
cl = c.post(f"{API}/clients", json={"name": f"Export Esha {RUN}", "phone": f"95{RUN}33"[:10]}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": f"IQ-EXP-{RUN}", "name": "Export flat", "client_id": cl["id"]}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
ver = c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H).json()["version"]
b = c.post(f"{API}/rooms/{rid}/designs/{ver}/boq", json={"gst_enabled": False}, headers=H).json(); c.post(f"{API}/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=H)
c.post(f"{API}/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "40000.00"}, headers=H).raise_for_status()
c.post(f"{API}/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "40000.00", "received_on": date.today().isoformat(), "mode": "BANK"}, headers=H).raise_for_status()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True); page = ctx.new_page(); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    page.goto(f"{WEB}/catalogue/materials"); page.locator(f"tr[data-sku='{SKU}']").click(); sp = page.get_by_test_id("supplier-prices"); sp.wait_for()
    check("no quotes: buys from the default supplier at cost", A["name"] in sp.get_by_test_id("best-price").inner_text() and "2,800.00" in sp.get_by_test_id("best-price").inner_text())
    sp.get_by_role("button", name="Add supplier price").click()
    sp.get_by_label("Quote supplier").select_option(B["id"]); sp.get_by_label("Quote price").fill("2,650"); sp.get_by_label("Quote lead days").fill("4")
    sp.get_by_role("button", name="Save supplier price").click(); sp.locator(f"[data-quote='{B['name']}']").wait_for(); page.wait_for_timeout(500)
    best = sp.get_by_test_id("best-price").inner_text()
    check("the cheaper valid quote wins", B["name"] in best and "2,650.00" in best and "cheapest valid quote" in best, best)
    page.once("dialog", lambda d: d.accept("Rates revised"))
    sp.get_by_role("button", name=f"End price from {B['name']}").click(); page.wait_for_timeout(1200)
    check("ending the quote falls back to the default supplier", A["name"] in sp.get_by_test_id("best-price").inner_text())
    page.keyboard.press("Escape")

    page.goto(f"{WEB}/finance/accounting-export"); s = page.get_by_test_id("export-summary")
    page.wait_for_function("() => /voucher/.test(document.querySelector('[data-testid=export-summary]')?.textContent || '')")
    check("summary counts this month's vouchers", "sales" in s.inner_text() and "receipt" in s.inner_text(), s.inner_text())
    with page.expect_download() as dl: page.get_by_role("button", name="Tally XML").click()
    root = ET.parse(dl.value.path()).getroot(); vs = root.findall(".//VOUCHER")
    check("Tally XML has vouchers that each balance", vs and all(sum(Decimal(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")) == 0 for v in vs))
    check("our client is a Sundry Debtors ledger", any(l.get("NAME") == f"Export Esha {RUN}" and l.findtext("PARENT") == "Sundry Debtors" for l in root.findall(".//LEDGER")))
    with page.expect_download() as dl: page.get_by_role("button", name="Day book (CSV)").click()
    check("day book CSV downloads", f"Export Esha {RUN}" in open(dl.value.path(), encoding="utf-8-sig").read())
    page.get_by_label("Bank ledger (UPI / cheque / card / bank)").fill(f"HDFC {RUN}"); page.get_by_role("button", name="Save ledger names").click(); page.get_by_text("Ledger names saved").wait_for()
    check("ledger name saved on the server", c.get(f"{API}/settings/tally", headers=H).json()["values"]["bank"] == f"HDFC {RUN}")
    page.screenshot(path=f"{SHOTS}/accounting_export.png", full_page=True)
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

c.put(f"{API}/settings/tally", json={"bank": "Bank Account"}, headers=H); c.put(f"{API}/settings/company", json={"gst_enabled": True}, headers=H)
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
