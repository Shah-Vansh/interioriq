"""Real-browser test of M17 payables: record a supplier bill against a PO (blocked when more than received unless approved), an overhead bill,
pay oldest-due first, ageing + statement, void a payment, the project's real cash line, payment terms on the supplier, and role limits."""
import os, sys, tempfile, time
from datetime import date, timedelta
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
SUP = f"Payables Traders {RUN}"
sup = c.post(f"{API}/suppliers", json={"name": SUP, "phone": f"92{RUN}11"[:10], "payment_terms_days": 15}, headers=H).json()
it = c.post(f"{API}/catalogue/items", json={"sku": f"PAY-{RUN}", "name": f"Bar stool {RUN}", "category": "Chair", "price": "1500", "cost_price": "1000",
                                            "length_mm": 450, "width_mm": 450, "height_mm": 750, "supplier_id": sup["id"]}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": f"IQ-PAY-{RUN}", "name": "Payables cafe"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Counter", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
objs = [dict(id=f"s{i}", name=it["name"], category="Chair", sku=it["sku"], price=1500, x=300 + i * 700, y=300, length=450, width=450, height=750) for i in range(3)]
v = c.post(f"{API}/rooms/{rid}/designs", json={"objects": objs}, headers=H).json()["version"]
b = c.post(f"{API}/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": False}, headers=H).json(); c.post(f"{API}/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=H)
po = c.get(f"{API}/purchase-orders/{c.post(f'{API}/boqs/' + b['id'] + '/procure', json={}, headers=H).json()['created'][0]['id']}", headers=H).json()
c.post(f"{API}/purchase-orders/{po['id']}/issue", headers=H)
c.post(f"{API}/purchase-orders/{po['id']}/receive", json={"lines": [{"line_id": po["lines"][0]["id"], "qty": 2}]}, headers=H)       # 2 of 3 received = Rs 2,000
c.post(f"{API}/projects/{pid}/payments", json={"boq_id": b["id"], "amount": "3000", "received_on": date.today().isoformat(), "mode": "UPI"}, headers=H)
c.post(f"{API}/users", json={"email": f"proc{RUN}@studio.test", "full_name": "Procurement", "role": "PROCUREMENT_MANAGER", "password": "Proc2026xx"}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    def login(email, pw="ChangeMe123!"):
        if page.url.startswith(WEB): page.evaluate("try{localStorage.clear()}catch(e){}")
        page.goto(f"{WEB}/login"); page.fill("#email", email); page.fill("#password", pw); page.click("button:has-text('Sign in')")
    login("admin@interioriq.com"); page.wait_for_url("**/dashboard")

    # bill against the PO: over-billing is caught, then the matched bill is saved
    page.goto(f"{WEB}/finance/payables"); page.get_by_role("button", name="Record bill").click(); d = page.get_by_role("dialog", name="Record bill")
    d.get_by_label("Purchase order").select_option(value=po["id"]); d.get_by_label("Taxable value").fill("3000"); page.wait_for_selector("[data-testid=po-check] >> text=MORE than was received")
    check("the form shows goods received (Rs 2,000) and flags over-billing", "₹2,000.00" in d.get_by_test_id("po-check").inner_text())
    d.get_by_label("Bill number").fill(f"PT-{RUN}-1"); d.get_by_role("button", name="Save bill").click(); d.get_by_role("alert").wait_for()
    check("saving more than received without a reason is refused", "approval reason" in d.get_by_role("alert").inner_text())
    d.get_by_label("Taxable value").fill("2,000"); page.wait_for_timeout(600); d.get_by_role("button", name="Save bill").click()
    page.wait_for_selector(f"[data-bill='PT-{RUN}-1']"); row = page.locator(f"[data-bill='PT-{RUN}-1']").inner_text()
    due = (date.today() + timedelta(days=15)).strftime("%d %b %Y")
    check("matched bill saved with the due date from the 15-day terms", "matched to goods received" in row and due in row and "₹2,000.00" in row, row[:200])

    # an older overhead bill (no PO) that is already overdue
    page.get_by_role("button", name="Record bill").click(); d = page.get_by_role("dialog", name="Record bill")
    d.get_by_label("Supplier").select_option(label=SUP); d.get_by_label("Bill number").fill(f"PT-{RUN}-OLD")
    d.locator("input[type=date]").first.fill((date.today() - timedelta(days=40)).isoformat()); d.get_by_label("Taxable value").fill("500"); d.get_by_label("GST on the bill").fill("90")
    d.get_by_role("button", name="Save bill").click(); page.wait_for_selector(f"[data-bill='PT-{RUN}-OLD']")
    check("overhead bill is overdue (40 − 15 = 25 days)", "25d late" in page.locator(f"[data-bill='PT-{RUN}-OLD']").inner_text())

    # pay 1,000: oldest due first → the overdue bill (590) fully, then 410 on the PO bill
    page.get_by_role("button", name="Record payment").click(); d = page.get_by_role("dialog", name="Record payment")
    d.get_by_label("Supplier").select_option(value=sup["id"]); d.get_by_label("Amount").fill("1000"); d.get_by_label("Reference").fill(f"NEFT{RUN}")
    d.get_by_role("button", name="Save payment").click(); page.wait_for_selector(f"[data-payment='NEFT{RUN}']")
    alloc = page.locator(f"[data-payment='NEFT{RUN}']").inner_text()
    check("payment settled the overdue bill first, then part of the next", f"PT-{RUN}-OLD ₹590.00" in alloc and f"PT-{RUN}-1 ₹410.00" in alloc, alloc)

    # overview + statement
    page.get_by_role("tab", name="Overview").click(); page.wait_for_selector(f"[data-supplier='{SUP}']")
    check("ageing and supplier balance are shown", "₹1,590.00" in page.locator(f"[data-supplier='{SUP}']").inner_text() and page.get_by_test_id("ageing").count() == 1)
    page.locator(f"[data-supplier='{SUP}']").get_by_role("button", name="Statement").click(); page.wait_for_selector("[data-testid=statement-balance]")
    check("statement balance = 2,590 billed − 1,000 paid", page.get_by_test_id("statement-balance").inner_text() == "₹1,590.00")
    page.keyboard.press("Escape")

    # project cash line uses real supplier payments
    page.goto(f"{WEB}/projects/{pid}"); page.wait_for_selector("[data-testid=cash-line]")
    cash = page.get_by_test_id("cash-line").inner_text()
    check("project cash = 3,000 received − 410 paid to suppliers for this project", "paid to suppliers ₹410.00" in cash and "₹2,590.00" in cash, cash)

    # void the payment → balances return
    page.goto(f"{WEB}/finance/payables"); page.get_by_role("tab", name="Payments").click()
    page.locator(f"[data-payment='NEFT{RUN}']").get_by_role("button", name="Void").click(); vd = page.get_by_role("dialog", name="Void")
    vd.get_by_label("Reason").fill("Wrong supplier account"); vd.get_by_role("button", name="Void").click(); page.wait_for_selector(f"[data-payment='NEFT{RUN}'] >> text=void: Wrong supplier account")
    page.get_by_role("tab", name="Bills").click(); page.wait_for_selector(f"[data-bill='PT-{RUN}-OLD']")
    check("voiding the payment re-opens both bills", "open" in page.locator(f"[data-bill='PT-{RUN}-OLD']").inner_text().lower())
    page.screenshot(path=f"{SHOTS}/payables.png", full_page=True)

    # supplier drawer: terms + statement
    page.goto(f"{WEB}/catalogue/suppliers"); page.locator(f"tr:has-text('{SUP}')").click(); sd = page.get_by_role("dialog", name="Edit supplier")
    check("supplier shows its payment terms", sd.get_by_label("Payment terms (days after bill date; blank = 30)", exact=True).input_value() == "15")
    sd.get_by_role("button", name="Statement (bills & payments)").click(); page.wait_for_selector("[data-testid=statement-balance]")
    check("statement opens from the supplier", page.get_by_test_id("statement-balance").inner_text() == "₹2,590.00")
    page.goto(f"{WEB}/reports/ai"); page.wait_for_selector("text=The rules")
    check("the overdue bill shows up in the AI alerts", page.locator("[data-rule=BILL_OVERDUE]", has_text=f"PT-{RUN}-OLD").count() == 1)
    check("no browser errors or failed requests (admin)", not problems, "; ".join(problems[:5]))

    # procurement: records bills, can't pay
    login(f"proc{RUN}@studio.test", "Proc2026xx"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/finance/payables"); page.wait_for_selector("text=Owed to suppliers")
    check("procurement can record bills but not pay suppliers", page.get_by_role("button", name="Record bill").count() == 1 and page.get_by_role("button", name="Record payment").count() == 0)
    check("no browser errors or failed requests (procurement)", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
