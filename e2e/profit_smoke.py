"""Real-browser test of M16 profitability: cost price + margin in the catalogue (hidden from a designer), cost history, editable draft PO rates,
the project's Profitability and Expenses cards (add + void), the Profitability report, and a site engineer who can log expenses but not see margins."""
import os, sys, tempfile, time
from datetime import date
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
SKU = f"PFT-{RUN}"; NAME = f"Lounge chair {RUN}"; PN = f"IQ-PFT-{RUN}"
sup = c.post(f"{API}/suppliers", json={"name": f"Profit Supplier {RUN}", "phone": f"93{RUN}22"[:10]}, headers=H).json()
c.post(f"{API}/users", json={"email": f"site{RUN}@studio.test", "full_name": "Site Engineer", "role": "SITE_ENGINEER", "password": "Site2026xx"}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text and "403" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    def login(email, pw="ChangeMe123!"):
        if page.url.startswith(WEB): page.evaluate("try{localStorage.clear()}catch(e){}")
        page.goto(f"{WEB}/login"); page.fill("#email", email); page.fill("#password", pw); page.click("button:has-text('Sign in')")
    login("admin@interioriq.com"); page.wait_for_url("**/dashboard")

    # catalogue: create with cost, see margin, change cost
    page.goto(f"{WEB}/catalogue/furniture"); page.get_by_role("button", name="Add furniture item").click(); d = page.get_by_role("dialog", name="New furniture item")
    d.get_by_label("SKU *", exact=True).fill(SKU); d.get_by_label("Price (₹) *", exact=True).fill("20000"); d.get_by_label("Cost price (₹, what you pay)", exact=True).fill("13,000")
    d.get_by_label("Name *", exact=True).fill(NAME); d.get_by_label("Category *", exact=True).fill("Chair")
    for lbl, v in (("Length (mm) *", "800"), ("Width (mm) *", "800"), ("Height (mm) *", "850")): d.get_by_label(lbl, exact=True).fill(v)
    d.get_by_label("Supplier", exact=True).select_option(label=sup["name"]); d.get_by_role("button", name="Create item").click()
    dd = page.get_by_role("dialog", name=NAME); dd.wait_for()
    check("new item shows its cost and 35% margin", "₹13,000.00" in page.get_by_test_id("current-cost").inner_text() and "35.0%" in page.get_by_test_id("current-cost").inner_text())
    dd.get_by_label("New cost (₹)", exact=True).fill("12000"); dd.get_by_label("Reason for cost change", exact=True).fill("Negotiated with supplier")
    dd.get_by_role("button", name="Change cost").click(); page.wait_for_selector("[role=status] >> text=Cost changed")
    ph = page.get_by_test_id("price-history").inner_text()
    check("cost change recorded in history (COST, old → new, reason)", "COST" in ph and "₹13,000.00 → ₹12,000.00" in ph and "Negotiated with supplier" in ph, ph[:200])
    page.keyboard.press("Escape"); page.wait_for_selector(f"[data-sku='{SKU}'] [data-testid=cost-cell]")
    check("catalogue list shows cost · margin", "40.0%" in page.locator(f"[data-sku='{SKU}'] [data-testid=cost-cell]").inner_text())

    # a costed project via the API (same as earlier suites), then the screens
    pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Profit penthouse"}, headers=H).json()["id"]
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Lounge", "room_type": "BEDROOM"}, headers=H).json()["id"]
    for l, v in (("Length", 4500), ("Width", 3800)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    objs = [dict(id=f"c{i}", name=NAME, category="Chair", sku=SKU, price=20000, x=300 + i * 1000, y=300, length=800, width=800, height=850) for i in range(2)]
    v = c.post(f"{API}/rooms/{rid}/designs", json={"objects": objs}, headers=H).json()["version"]
    b = c.post(f"{API}/rooms/{rid}/designs/{v}/boq", json={"gst_enabled": True}, headers=H).json()
    c.post(f"{API}/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=H)
    po = c.post(f"{API}/boqs/{b['id']}/procure", json={}, headers=H).json()["created"][0]

    # PO: draft rate is the COST and can be negotiated
    page.goto(f"{WEB}/execution/po"); page.locator(f"[data-po='{po['po_number']}']").click(); pd = page.get_by_role("dialog", name=po["po_number"])
    rate = pd.get_by_label(f"Rate {SKU}", exact=True)
    page.wait_for_function("el => el.value !== ''", arg=rate.element_handle())
    check("the PO is priced at the cost (12,000), not the selling price", rate.input_value() == "12000.00", rate.input_value())
    rate.fill("11,500"); pd.get_by_role("button", name="Save").click(); page.wait_for_selector("[role=status] >> text=Saved")
    check("negotiated rate saved and the PO total updated", "₹23,000.00" in pd.inner_text())
    page.keyboard.press("Escape")

    # project page: profitability + expenses
    page.goto(f"{WEB}/projects/{pid}"); page.wait_for_selector("[data-testid=profit-card]")
    p0 = c.get(f"{API}/projects/{pid}/profit", headers=H).json()
    card = page.get_by_test_id("profit-card").inner_text()
    check("profitability card shows ex-GST revenue and the PO cost", "₹23,000.00" in card and p0["revenue"][:3] in card.replace(",", "") and "GST" in card)
    page.get_by_role("button", name="Add expense").click(); d = page.get_by_role("dialog", name="Add expense")
    d.get_by_label("Category").select_option("LABOUR"); d.get_by_label("Amount").fill("4,500"); d.get_by_label("Paid to").fill("Upholstery team")
    d.get_by_role("button", name="Save expense").click(); page.wait_for_selector("[data-testid=expenses] >> text=Upholstery team")
    page.wait_for_timeout(1200)
    p1 = c.get(f"{API}/projects/{pid}/profit", headers=H).json()
    check("expense is counted in the actual cost", p1["actual"]["total"] == "27500.00" and p1["actual"]["expenses"] == {"LABOUR": "4500.00"}, p1["actual"]["total"])
    check("the card refreshed to the new profit", p1["actual"]["profit"].lstrip("-").split(".")[0][-3:] in page.get_by_test_id("profit-actual").inner_text().replace(",", ""))
    page.locator("[data-testid=expenses] li", has_text="Upholstery team").get_by_role("button", name="Void").click()
    vd = page.get_by_role("dialog", name="Void expense"); vd.get_by_label("Reason").fill("Entered twice"); vd.get_by_role("button", name="Void expense").click()
    page.wait_for_selector("[data-testid=expenses] >> text=void: Entered twice")
    check("voided expense drops out of the cost", c.get(f"{API}/projects/{pid}/profit", headers=H).json()["actual"]["total"] == "23000.00")
    page.screenshot(path=f"{SHOTS}/profit_project.png", full_page=True)

    # report
    page.goto(f"{WEB}/reports/profitability"); page.wait_for_selector(f"[data-profit='{PN}']")
    check("profitability report lists the project with its actual cost", "₹23,000.00" in page.locator(f"[data-profit='{PN}']").inner_text())
    check("no browser errors or failed requests (admin)", not problems, "; ".join(problems[:5]))

    # designer: no costs anywhere in the catalogue
    login("kiran@interioriq.com"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/catalogue/furniture"); page.wait_for_selector(f"[data-sku='{SKU}']")
    check("a designer sees no cost column", page.locator("[data-testid=cost-cell]").count() == 0 and "Cost · margin" not in page.locator("thead").inner_text())

    # site engineer: expenses yes, margins no
    login(f"site{RUN}@studio.test", "Site2026xx"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/projects/{pid}"); page.wait_for_selector("text=Add expense")
    check("a site engineer can log expenses but sees no profitability", page.locator("[data-testid=profit-card]").count() == 0 and page.get_by_role("button", name="Add expense").count() == 1)
    check("no browser errors or failed requests (other roles)", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
