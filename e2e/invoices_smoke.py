"""Real-browser test of OPTIONAL GST: company default switch, the BOQ 'Include GST' switch, tax invoice (CGST/SGST) vs plain invoice (no GST),
milestone invoicing, cancel, the Invoices list, and the client seeing the invoice in the portal."""
import os, sys, tempfile, time
import httpx, pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-GST-{RUN}"; CLIENT = f"Rhea Mehta {RUN}"

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)
def pdf_text(path): d = pdfium.PdfDocument(path); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

cl = c.post(f"{API}/clients", json={"name": CLIENT, "phone": f"96{RUN}44"[:10]}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Mehta apartment", "client_id": cl["id"], "site_address": "Bodakdev, Ahmedabad"}, headers=H).json()["id"]
rids = []
for name in ("Bedroom GST", "Bedroom NOGST"):
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": name, "room_type": "BEDROOM"}, headers=H).json()["id"]; rids.append(rid)
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)   # tolerate a busy machine
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    def download(click):
        with page.expect_download() as dl: click()
        return dl.value.path()
    def login(email, pw="ChangeMe123!"):
        if page.url.startswith(WEB): page.evaluate("try{localStorage.clear()}catch(e){}")
        page.goto(f"{WEB}/login"); page.fill("#email", email); page.fill("#password", pw); page.click("button:has-text('Sign in')")
    login("admin@interioriq.com"); page.wait_for_url("**/dashboard")

    # Settings → Company: GSTIN + GST default OFF
    page.goto(f"{WEB}/settings/company"); page.wait_for_selector("text=Company profile")
    page.get_by_label("GSTIN", exact=True).fill("27AAPFU0939F1ZV")
    sw = page.get_by_role("switch", name="Charge GST by default (new quotations start with GST on)")
    if sw.get_attribute("aria-checked") == "true": sw.click()
    page.get_by_role("button", name="Save", exact=True).click(); page.wait_for_selector("[role=status]")
    check("company GST default can be switched off", sw.get_attribute("aria-checked") == "false")

    # BOQ screen: the switch starts OFF (company default) → BOQ without GST
    page.goto(f"{WEB}/estimation/boq")
    def pick(project_label, room):
        page.wait_for_selector(f"select option:has-text('{PN}')", state="attached")
        sel = page.locator("select").first; sel.select_option(label=next(o for o in sel.locator("option").all_inner_texts() if o.startswith(PN))); page.wait_for_timeout(700)
        rs = page.locator("select").nth(1); rs.select_option(label=room); page.wait_for_timeout(900)
    pick(PN, "Bedroom NOGST")
    gsw = page.get_by_role("switch", name="Include GST"); gsw.wait_for()
    check("BOQ 'Include GST' follows the company default (off)", gsw.get_attribute("aria-checked") == "false")
    page.get_by_role("button", name="Create BOQ").first.click(); page.wait_for_selector("[data-testid=grand-total]")
    summ = page.get_by_test_id("boq-summary").inner_text()
    check("a GST-off BOQ shows no GST line and 'Grand total' without GST", "GST" not in summ, summ[:200])
    t = pdf_text(download(lambda: page.get_by_role("button", name="Quotation PDF").click()))
    check("its quotation PDF says GST is not charged", "GST is not charged" in t and "GST (" not in t)

    # Same screen: switch ON for the other room → 18% GST
    pick(PN, "Bedroom GST"); gsw = page.get_by_role("switch", name="Include GST"); gsw.click()
    check("the switch turns GST on", gsw.get_attribute("aria-checked") == "true")
    page.get_by_role("button", name="Create BOQ").first.click(); page.wait_for_selector("text=Grand total (incl. GST)")
    check("a GST-on BOQ shows the GST line", "GST (18%)" in page.get_by_test_id("boq-summary").inner_text())

    qs = {q["room_name"]: q for q in c.get(f"{API}/quotations", params={"project_id": pid}, headers=H).json()}
    for q in qs.values(): c.post(f"{API}/boqs/{q['id']}/status", json={"status": "APPROVED"}, headers=H)

    # Project page: tax invoice for the GST quotation
    page.goto(f"{WEB}/projects/{pid}"); page.get_by_role("button", name="Raise invoice").click(); d = page.get_by_role("dialog", name="Raise invoice")
    d.get_by_label("Quotation", exact=True).select_option(value=qs["Bedroom GST"]["id"]); page.wait_for_timeout(300)
    check("the drawer says it will be a TAX INVOICE", "TAX INVOICE" in d.get_by_test_id("gst-mode").inner_text())
    d.get_by_role("button", name="Issue tax invoice").click(); page.wait_for_selector("[data-testid=invoice-list] [data-invoice]")
    inv_no = page.locator("[data-testid=invoice-list] [data-invoice]").first.get_attribute("data-invoice")
    row = page.locator(f"[data-invoice='{inv_no}']")
    check("tax invoice issued for the first milestone with CGST + SGST", "Tax invoice" in row.inner_text() and "CGST" in row.inner_text() and "SGST" in row.inner_text(), row.inner_text())
    t = pdf_text(download(lambda: row.get_by_role("button", name=f"PDF {inv_no}").click()))
    check("tax invoice PDF: title, GSTIN, CGST/SGST 9%, place of supply, amount in words",
          "TAX INVOICE" in t and "27AAPFU0939F1ZV" in t and "CGST 9%" in t and "SGST 9%" in t and "27 - Maharashtra" in t and "Rupees" in t)

    # plain invoice for the GST-off quotation
    page.get_by_role("button", name="Raise invoice").click(); d = page.get_by_role("dialog", name="Raise invoice")
    d.get_by_label("Quotation", exact=True).select_option(value=qs["Bedroom NOGST"]["id"]); page.wait_for_timeout(300)
    check("the drawer says it will be a plain invoice with no GST", "no GST" in d.get_by_test_id("gst-mode").inner_text())
    d.get_by_text("Other amount").click(); d.get_by_label("Amount", exact=True).fill("25,000"); d.get_by_label("Description", exact=True).fill("Advance for hardware")
    d.get_by_role("button", name="Issue invoice").click(); page.wait_for_selector("[data-testid=invoice-list] >> text=Advance for hardware")
    plain = page.locator("[data-testid=invoice-list] li", has_text="Advance for hardware")
    check("plain invoice shows 'No GST'", "No GST" in plain.inner_text() and "₹25,000.00" in plain.inner_text())
    plain_no = plain.get_attribute("data-invoice")
    t = pdf_text(download(lambda: plain.get_by_role("button", name=f"PDF {plain_no}").click()))
    check("plain invoice PDF has no GST at all", "TAX INVOICE" not in t and "GST is not charged" in t and "CGST" not in t and "IGST" not in t)

    # over-invoicing refused with a reason
    page.get_by_role("button", name="Raise invoice").click(); d = page.get_by_role("dialog", name="Raise invoice")
    d.get_by_label("Quotation", exact=True).select_option(value=qs["Bedroom NOGST"]["id"]); d.get_by_text("Other amount").click()
    d.get_by_label("Amount", exact=True).fill("99,99,99,999"); d.get_by_role("button", name="Issue invoice").click()
    d.get_by_role("alert").wait_for()
    check("invoicing more than the quotation is refused", "left to invoice" in d.get_by_role("alert").inner_text())
    page.keyboard.press("Escape")

    # cancel the plain invoice
    plain.get_by_role("button", name="Cancel").click(); d = page.get_by_role("dialog", name="Cancel invoice")
    d.get_by_label("Reason", exact=True).fill("Raised by mistake"); d.get_by_role("button", name="Cancel invoice").click()
    page.wait_for_selector("[data-testid=invoice-list] >> text=Cancelled: Raised by mistake")
    check("cancelled invoice keeps its number and shows the reason", page.locator(f"[data-invoice='{plain_no}']").count() == 1)
    page.screenshot(path=f"{SHOTS}/gst_project.png", full_page=True)

    # Estimation → Invoices list
    page.goto(f"{WEB}/estimation/invoices"); page.wait_for_selector(f"[data-invoice='{inv_no}']")
    page.get_by_label("Type filter").select_option("PLAIN"); page.wait_for_timeout(700)
    check("Invoices list filters to invoices without GST", page.locator(f"[data-invoice='{plain_no}']").count() == 1 and page.locator(f"[data-invoice='{inv_no}']").count() == 0)
    check("no browser errors or failed requests (staff)", not problems, "; ".join(problems[:5]))

    # client sees the issued invoice in the portal
    c.post(f"{API}/users", json={"email": f"rhea{RUN}@example.com", "full_name": CLIENT, "role": "CLIENT", "password": "Rhea2026xx", "client_id": cl["id"]}, headers=H)
    login(f"rhea{RUN}@example.com", "Rhea2026xx"); page.wait_for_url("**/client-portal"); page.wait_for_selector("[data-testid=portal-invoices]")
    pi = page.get_by_test_id("portal-invoices").inner_text()
    check("the client sees the issued tax invoice (not the cancelled one)", inv_no in pi and plain_no not in pi and "incl. GST" in pi)
    t = pdf_text(download(lambda: page.get_by_role("button", name=f"PDF {inv_no}").click()))
    check("the client can download their invoice PDF", inv_no in t)
    check("no browser errors or failed requests (client)", not problems, "; ".join(problems[:5]))
    br.close()

c.put(f"{API}/settings/company", json={"gst_enabled": True}, headers=H)
print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
