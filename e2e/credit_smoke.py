"""Real-browser test of M33 credit notes: on the project page issue a credit note against an invoice (GST reversed in the same split),
totals show Credited and the lower receivable, the PDF downloads, the invoice can't be cancelled while credited, the note can be
cancelled with a reason, and the client portal lists the issued note."""
import os, sys, tempfile, time
import httpx
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
c.put(f"{API}/settings/company", json={"gstin": "27AAPFU0939F1ZV", "gst_enabled": True, "invoice_prefix": "INV"}, headers=H)
cl = c.post(f"{API}/clients", json={"name": f"Credit Chitra {RUN}", "phone": f"94{RUN}77"[:10], "email": f"chitra{RUN}@client.test"}, headers=H).json()
pid = c.post(f"{API}/projects", json={"project_number": f"IQ-CRN-{RUN}", "name": "Credit villa", "client_id": cl["id"]}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
ver = c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H).json()["version"]
b = c.post(f"{API}/rooms/{rid}/designs/{ver}/boq", json={"gst_enabled": True}, headers=H).json()
c.post(f"{API}/boqs/{b['id']}/status", json={"status": "APPROVED"}, headers=H)
inv = c.post(f"{API}/projects/{pid}/invoices", json={"boq_id": b["id"], "amount": "118000.00", "description": "Advance"}, headers=H).json()
c.post(f"{API}/users", json={"email": f"chitra{RUN}@client.test", "full_name": "Chitra", "role": "CLIENT", "password": "ChangeMe123!", "client_id": cl["id"]}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True); page = ctx.new_page(); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status != 409 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    page.goto(f"{WEB}/projects/{pid}"); row = page.locator(f"[data-invoice='{inv['invoice_no']}']"); row.wait_for()
    row.get_by_role("button", name=f"Credit note for {inv['invoice_no']}").click(); d = page.get_by_role("dialog", name="Credit note"); d.wait_for()
    d.get_by_label("Credit amount").fill("11,800"); d.get_by_label("Credit reason").fill("Laminate changed to a cheaper finish")
    d.get_by_role("button", name="Issue credit note").click(); d.wait_for(state="detached")
    cn = page.get_by_test_id("credit-note-list"); cn.wait_for()
    check("credit note listed against the invoice", inv["invoice_no"] in cn.inner_text() and "11,800.00" in cn.inner_text())
    check("totals show Credited and the lower receivable", "11,800.00" in page.get_by_test_id("inv-Credited").inner_text() and "1,06,200.00" in page.get_by_test_id("inv-Receivable").inner_text(),
          page.get_by_test_id("inv-Receivable").inner_text())
    check("invoice row shows credited + net", "net" in row.inner_text() and "1,06,200.00" in row.inner_text())
    note_no = cn.locator("b.font-mono").first.inner_text()
    with page.expect_download() as dl: cn.get_by_role("button", name=f"PDF {note_no}").click()
    d0 = pdfium.PdfDocument(dl.value.path()); t = d0[0].get_textpage().get_text_range()
    check("credit note PDF names the invoice and reverses CGST/SGST", "CREDIT NOTE" in t and inv["invoice_no"] in t and "CGST" in t and "SGST" in t)
    page.screenshot(path=f"{SHOTS}/credit_note.png", full_page=True)
    row.get_by_role("button", name="Cancel", exact=True).click(); dd = page.get_by_role("dialog", name="Cancel invoice"); dd.get_by_label("Reason").fill("Wrong client")
    dd.get_by_role("button", name="Cancel invoice").click(); dd.get_by_role("alert").wait_for()
    check("invoice with a credit note can't be cancelled", "credit notes" in dd.get_by_role("alert").inner_text())
    page.keyboard.press("Escape")

    # client portal sees the issued note
    cp = br.new_page(viewport={"width": 1400, "height": 1000})
    cp.goto(f"{WEB}/login"); cp.fill("#email", f"chitra{RUN}@client.test"); cp.fill("#password", "ChangeMe123!"); cp.click("button:has-text('Sign in')"); cp.wait_for_url("**/client-portal**")
    cp.get_by_text("Credit villa").first.click(); cp.get_by_test_id("portal-credit-notes").wait_for()
    check("client portal lists the credit note", note_no in cp.get_by_test_id("portal-credit-notes").inner_text())
    cp.close()

    # cancel the note → totals back
    cn.get_by_role("button", name="Cancel", exact=True).click(); dc = page.get_by_role("dialog", name="Cancel credit note"); dc.get_by_label("Reason").fill("Issued by mistake")
    dc.get_by_role("button", name="Cancel credit note").click(); dc.wait_for(state="detached"); page.wait_for_timeout(800)
    check("cancelled note keeps its number; receivable back to full", "Issued by mistake" in cn.inner_text() and "1,18,000.00" in page.get_by_test_id("inv-Receivable").inner_text())
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

c.put(f"{API}/settings/company", json={"gstin": "", "gst_enabled": True}, headers=H)
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
