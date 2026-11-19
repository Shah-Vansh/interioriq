"""Real-browser, end-to-end business flow through the actual screens:
quotation sent+approved → payment → procurement (stock + PO) → PO issued + received → work orders to READY → cutting list →
delivery scheduled/dispatched/delivered → installation done → QC fail → snag fixed → all pass → handover + certificate →
project completed; then drawings, dashboard/reports/AI, settings (company, users, roles, system, AI), contacts, photos, global search,
and a real CLIENT login that only sees its own portal and approves a quotation there."""
import io, os, sys, tempfile, time
import httpx, pypdfium2 as pdfium
from PIL import Image
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]; TMP = tempfile.mkdtemp()
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-OPS-{RUN}"; CLIENT = f"Kavya Desai {RUN}"; SUP = f"Om Furniture {RUN}"

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)
def pdf_text(path): d = pdfium.PdfDocument(path); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

# ── data that the earlier suites already prove through their own screens ──
sup = c.post(f"{API}/suppliers", json={"name": SUP, "phone": f"98{RUN}77"[:10]}, headers=H).json()
chair = c.post(f"{API}/catalogue/items", json={"sku": f"CHR-{RUN}", "name": f"Accent chair {RUN}", "category": "Chair", "price": "15000", "stock": 1, "length_mm": 700, "width_mm": 700, "height_mm": 850, "supplier_id": sup["id"]}, headers=H).json()
ward = c.post(f"{API}/catalogue/items", json={"sku": f"WRD-{RUN}", "name": f"Sliding wardrobe {RUN}", "category": "Wardrobe", "price": "120000", "length_mm": 2400, "width_mm": 600, "height_mm": 2100}, headers=H).json()
ply = c.post(f"{API}/catalogue/items", json={"sku": f"PLY-{RUN}", "name": "BWP ply 18mm", "kind": "MATERIAL", "category": "Plywood", "unit": "sheet", "price": "2850", "supplier_id": sup["id"]}, headers=H).json()
cl = c.post(f"{API}/clients", json={"name": CLIENT, "phone": f"97{RUN}55"[:10], "address": "B-12 Prahladnagar"}, headers=H).json()
from datetime import date, timedelta
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Desai residence", "client_id": cl["id"], "site_address": "B-12 Prahladnagar, Ahmedabad",
                                       "target_date": (date.today() + timedelta(days=45)).isoformat()}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4500), ("Width", 3800), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
objs = [dict(id="w", name=ward["name"], category="Wardrobe", sku=ward["sku"], price=120000, x=50, y=50, length=2400, width=600, height=2100),
        dict(id="c1", name=chair["name"], category="Chair", sku=chair["sku"], price=15000, x=3000, y=2600, length=700, width=700, height=850),
        dict(id="c2", name=chair["name"], category="Chair", sku=chair["sku"], price=15000, x=3700, y=2600, length=700, width=700, height=850)]
v = c.post(f"{API}/rooms/{rid}/designs", json={"objects": objs}, headers=H).json()["version"]
boq = c.post(f"{API}/rooms/{rid}/designs/{v}/boq", json={}, headers=H).json(); QT = boq["quotation_no"]
# a second project for the same client, for the portal approval
pid2 = c.post(f"{API}/projects", json={"project_number": f"{PN}-B", "name": "Desai farmhouse", "client_id": cl["id"]}, headers=H).json()["id"]
rid2 = c.post(f"{API}/projects/{pid2}/rooms", json={"name": "Guest room", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, vv in (("Length", 4200), ("Width", 3600)): c.put(f"{API}/rooms/{rid2}/measurements", json={"label": l, "value": vv, "source": "USER_VERIFIED"}, headers=H)
v2 = c.post(f"{API}/rooms/{rid2}/designs", json={"objects": objs[1:2]}, headers=H).json()["version"]
boq2 = c.post(f"{API}/rooms/{rid2}/designs/{v2}/boq", json={}, headers=H).json()
c.post(f"{API}/boqs/{boq2['id']}/status", json={"status": "SENT"}, headers=H)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    def login(email, pw="ChangeMe123!"):
        page.evaluate("try{localStorage.clear()}catch(e){}") if page.url.startswith(WEB) else None
        page.goto(f"{WEB}/login"); page.fill("#email", email); page.fill("#password", pw); page.click("button:has-text('Sign in')")
    def pick_project(label=PN):
        sel = page.get_by_label("Project", exact=True); sel.wait_for()
        page.wait_for_selector(f"select[aria-label=Project] option:has-text('{label} ·')", state="attached")
        sel.select_option(label=next(o for o in sel.locator("option").all_inner_texts() if o.startswith(label + " ·"))); page.wait_for_timeout(700)
    def download(click):
        with page.expect_download() as dl: click()
        return dl.value.path()

    login("admin@interioriq.com"); page.wait_for_url("**/dashboard")

    # Settings → Company: board SKU so procurement orders sheets automatically
    page.goto(f"{WEB}/settings/company"); page.wait_for_selector("text=Company profile")
    page.get_by_label("18mm carcass board SKU (for cutting-list purchasing)", exact=True).fill(ply["sku"].lower())
    page.get_by_role("button", name="Save", exact=True).click(); page.wait_for_selector("[role=status]")
    check("company settings save (board SKU upper-cased)", page.get_by_label("18mm carcass board SKU (for cutting-list purchasing)", exact=True).input_value() == ply["sku"])

    # Quotations: send then approve
    page.goto(f"{WEB}/estimation/quotations"); row = page.locator(f"[data-quote='{QT}']"); row.wait_for()
    row.get_by_role("button", name=f"Mark sent {QT}").click(); page.wait_for_selector(f"[data-quote='{QT}'] [data-status=SENT]")
    row.get_by_role("button", name=f"Approve {QT}").click(); page.wait_for_selector(f"[data-quote='{QT}'] [data-status=APPROVED]")
    check("quotation sent then approved from the Quotations screen", row.locator("[data-status=APPROVED]").count() == 1)

    # Project page: stage + payment
    page.goto(f"{WEB}/projects/{pid}"); page.wait_for_selector("[data-testid=stepper]")
    check("project page shows the Procurement stage after approval", "Procurement" in page.locator("[data-testid=stepper] li.bg-amber-700").inner_text())
    page.get_by_role("button", name="Record payment").click(); d = page.get_by_role("dialog", name="Record payment")
    d.get_by_label("Amount (₹)", exact=True).fill("1,00,000"); d.get_by_label("Reference (UTR / cheque no.)", exact=True).fill("UTR998877")
    d.get_by_role("button", name="Save payment").click(); page.wait_for_selector("[data-testid=payments] >> text=UTR998877")
    check("payment recorded and shown on the project", "₹1,00,000.00" in page.get_by_test_id("pay-Received").inner_text())
    page.screenshot(path=f"{SHOTS}/ops_project.png", full_page=True)

    # Procurement
    page.goto(f"{WEB}/execution/procurement"); pick_project()
    page.get_by_role("button", name="Raise purchase orders").click(); page.wait_for_selector("[data-testid=procure-result]")
    res = page.get_by_test_id("procure-result").inner_text()
    check("procurement allocates 1 chair from stock and drafts a PO", f"{chair['sku']} × 1" in res and f"PO-{PN}-01" in res, res)

    # Purchase order: issue, receive, PDF
    page.goto(f"{WEB}/execution/po"); page.locator(f"[data-po='PO-{PN}-01']").click(); dd = page.get_by_role("dialog", name=f"PO-{PN}-01")
    lines_txt = dd.inner_text()
    check("PO has the missing chair and the boards from the cutting list", chair["sku"] in lines_txt and ply["sku"] in lines_txt)
    dd.get_by_role("button", name="Issue PO").click(); page.wait_for_selector("[role=status] >> text=Issued")
    for sku in (chair["sku"], ply["sku"]):
        box = dd.get_by_label(f"Receive {sku}", exact=True); box.fill(box.get_attribute("placeholder").replace("max ", ""))
    dd.get_by_role("button", name="Receive goods").click(); page.wait_for_selector("[role=status] >> text=Goods received")
    check("PO fully received", dd.locator("[data-status=RECEIVED]").count() == 1)
    t = pdf_text(download(lambda: dd.get_by_role("button", name="PDF").click()))
    check("PO PDF has number, supplier and delivery address", f"PO-{PN}-01" in t and SUP in t and "Prahladnagar" in t)
    page.keyboard.press("Escape")

    # Manufacturing → READY
    page.goto(f"{WEB}/execution/manufacturing"); pick_project()
    page.get_by_role("button", name="Create work orders from approved quotations").click(); page.wait_for_selector(f"[data-wo='WO-{PN}-001']")
    for _ in range(5):
        page.get_by_label(f"Advance WO-{PN}-001", exact=True).click(); page.wait_for_timeout(500)
    check("work order moved through the workshop to READY", page.locator(f"[data-stage=READY] [data-wo='WO-{PN}-001']").count() == 1)
    with page.expect_download() as dl: page.get_by_label(f"Shop drawing PDF WO-{PN}-001", exact=True).click()
    import pypdfium2 as _pdf; _t = _pdf.PdfDocument(dl.value.path())[0].get_textpage().get_text_range()
    check("shop drawing PDF downloads with elevations and the cutting list", "FRONT ELEVATION" in _t and "CUTTING LIST" in _t and f"WO-{PN}-001" in _t)
    page.goto(f"{WEB}/execution/cutting"); pick_project(); page.wait_for_selector("[data-testid=sheet-total]")
    check("cutting list shows panels and sheet totals", "18mm sheets" in page.get_by_test_id("sheet-total").inner_text() and page.locator("text=Shutter").count() >= 1)

    # Delivery
    page.goto(f"{WEB}/execution/delivery"); pick_project(); page.wait_for_selector("text=Ready to deliver")
    page.get_by_label(f"Deliver {chair['name']}", exact=True).fill("2"); page.get_by_label(f"Deliver {ward['name']}", exact=True).fill("1")
    page.get_by_label("Vehicle", exact=True).fill("GJ01XY4321"); page.get_by_role("button", name="Schedule delivery").click()
    page.wait_for_selector(f"[data-dn='DN-{PN}-01']"); dn = page.locator(f"[data-dn='DN-{PN}-01']")
    dn.get_by_role("button", name="Dispatch").click(); page.wait_for_selector(f"[data-dn='DN-{PN}-01'] [data-status=DISPATCHED]")
    dn.get_by_label(f"Received by DN-{PN}-01", exact=True).fill("Kavya Desai"); dn.get_by_role("button", name="Mark delivered").click()
    page.wait_for_selector(f"[data-dn='DN-{PN}-01'] [data-status=DELIVERED]")
    t = pdf_text(download(lambda: dn.get_by_role("button", name="Challan").click()))
    check("delivery note delivered and the challan PDF lists the goods", f"DN-{PN}-01" in t and ward["name"] in t)

    # Installation
    page.goto(f"{WEB}/execution/installation"); pick_project(); page.wait_for_selector("[data-task]")
    for title in page.locator("[data-task]").evaluate_all("els => els.map(e => e.dataset.task)"):
        page.get_by_label(f"Status of {title}", exact=True).select_option("DONE"); page.wait_for_timeout(600)
    check("all installation tasks done", "2 of 2 done" in page.locator("main").inner_text())

    # QC, snag, handover
    page.goto(f"{WEB}/execution/qc"); pick_project()
    page.get_by_role("button", name="Start QC inspection").click(); page.wait_for_selector("[data-testid=qc-checks]")
    first = page.locator("[data-check]").first.get_attribute("data-check")
    page.get_by_label(f"Fail {first}", exact=True).click()
    page.wait_for_selector("[role=alert] >> text=Describe what failed", timeout=8000)
    check("failing a check without a note is refused", page.locator("[role=alert]", has_text="Describe what failed").count() == 1)
    page.get_by_label(f"QC note {first}", exact=True).fill("Shutter gap uneven"); page.get_by_label(f"Fail {first}", exact=True).click()
    page.wait_for_selector("[data-testid=snags] >> text=Shutter gap uneven")
    snag_title = page.locator("[data-testid=snags] li p").first.inner_text()
    page.get_by_label(f"Fix note {snag_title}", exact=True).fill("Hinges re-adjusted"); page.get_by_role("button", name="Mark fixed").click()
    page.wait_for_selector("text=Snag fixed")
    check("handover is blocked while checks are open", page.locator("[data-testid=blockers]").count() == 1)
    for title in page.locator("[data-check]").evaluate_all("els => els.map(e => e.dataset.check)"):
        page.get_by_label(f"Pass {title}", exact=True).click(); page.wait_for_timeout(450)
    page.wait_for_selector("text=Ready for handover")
    page.get_by_label("Received by (client name)", exact=True).fill("Kavya Desai"); page.get_by_role("button", name="Record handover").click()
    page.wait_for_selector("[data-testid=handover-done]")
    t = pdf_text(download(lambda: page.get_by_role("button", name="Handover certificate", exact=True).click()))
    check("handover recorded and certificate PDF printed", "HANDOVER CERTIFICATE" in t and "Kavya Desai" in t and ward["name"] in t)
    page.goto(f"{WEB}/projects/{pid}"); page.wait_for_selector("[data-testid=timeline]")
    tl = page.get_by_test_id("timeline").inner_text()
    check("project is Completed and the timeline tells the story", "Completed" in page.locator("[data-testid=stepper] li.bg-amber-700").inner_text()
          and "Handed over to Kavya Desai" in tl and "QC failed" in tl and "Goods received" in tl)
    page.screenshot(path=f"{SHOTS}/ops_completed.png", full_page=True)

    # Drawings (pick THIS project: other suites' projects may sort first)
    def pick_room_project():
        first = page.locator("select").first; page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
        first.select_option(label=next(o for o in first.locator("option").all_inner_texts() if o.startswith(PN + " ·"))); page.wait_for_timeout(900)
    page.goto(f"{WEB}/design/ceiling"); pick_room_project(); page.wait_for_selector("[data-testid=ceiling-qty]")
    check("ceiling plan drawn with downlights and a wardrobe spotlight", page.locator("[data-light=DOWNLIGHT]").count() >= 2 and page.locator("[data-light=SPOTLIGHT]").count() >= 1)
    page.goto(f"{WEB}/design/electrical"); pick_room_project(); page.wait_for_selector("[data-point]")
    check("electrical schedule lists points incl. the assumed switchboard", page.locator("[data-point=SWITCHBOARD]").count() == 1 and "ASSUMED" in page.locator("main").inner_text())
    page.goto(f"{WEB}/design/elevations"); pick_room_project(); page.wait_for_selector("[data-wall=SOUTH]")
    check("four wall elevations", page.locator("svg[data-wall]").count() == 4)
    page.goto(f"{WEB}/design/plans"); pick_room_project(); page.wait_for_selector("svg[aria-label='Floor plan']")
    page.goto(f"{WEB}/design/cad"); pick_room_project(); page.wait_for_selector("text=Ceiling plan")
    path = download(lambda: page.get_by_role("button", name="Download Ceiling plan").click())
    check("CAD page downloads a DXF", open(path, "rb").read(200).decode("latin1").find("SECTION") >= 0)
    page.goto(f"{WEB}/design/versions"); pick_room_project(); page.wait_for_selector("[data-testid=versions]")

    # Photos
    img = os.path.join(TMP, "site.png"); Image.new("RGB", (64, 48), (180, 140, 90)).save(img)
    page.goto(f"{WEB}/survey/photos"); pick_room_project(); page.get_by_label("Upload images").set_input_files(img); page.wait_for_selector("[data-testid=gallery] img")
    check("site photo uploads and shows as an image", page.locator("[data-testid=gallery] figure").count() == 1)

    # Dashboard / reports / AI
    page.goto(f"{WEB}/dashboard"); page.wait_for_selector("[data-testid=dash-activity]")
    check("dashboard shows real numbers and activity", page.get_by_test_id("stat-Received this month").inner_text() != "₹0.00" and PN in page.get_by_test_id("dash-activity").inner_text())
    page.goto(f"{WEB}/reports/revenue"); page.wait_for_selector("text=By month")
    check("revenue report shows the payment", "₹1,00,000.00" in page.locator("main").inner_text())
    page.goto(f"{WEB}/reports/projects"); page.wait_for_selector("select[aria-label='Which projects']"); page.get_by_label("Which projects").select_option("all")
    page.wait_for_selector(f"[data-project='{PN}']", timeout=10000)
    check("projects report includes the completed project", page.locator(f"[data-project='{PN}']").count() == 1)
    page.goto(f"{WEB}/reports/ai"); page.wait_for_selector("text=The rules")
    page.goto(f"{WEB}/settings/roles"); page.wait_for_selector("[data-testid=roles-matrix]")
    page.goto(f"{WEB}/settings/system"); page.wait_for_selector("[data-testid=engines]")
    page.goto(f"{WEB}/settings/ai"); page.wait_for_selector("text=Local LLM (Ollama)")

    # Contacts
    page.goto(f"{WEB}/crm/contacts"); page.get_by_role("button", name="Add contact").click(); d = page.get_by_role("dialog", name="New contact")
    d.get_by_label("Client *", exact=True).select_option(label=CLIENT); d.get_by_label("Name *", exact=True).fill(f"Ar. Neel Shah {RUN}"); d.get_by_label("Relation", exact=True).fill("Architect")
    d.get_by_role("button", name="Create contact").click(); page.wait_for_selector(f"td >> text=Ar. Neel Shah {RUN}")
    check("contact added for the client", page.locator(f"tr:has-text('Ar. Neel Shah {RUN}')").count() == 1)

    # Global search
    page.get_by_label("Search everything").fill(PN); page.wait_for_selector("[role=listbox] [role=option]")
    page.locator("[role=option]", has_text="Desai residence").first.click(); page.wait_for_url(f"**/projects/{pid}")
    check("global search opens the project", page.url.endswith(f"/projects/{pid}"))

    # Users: create a CLIENT login through the screen
    page.goto(f"{WEB}/settings/users"); page.get_by_role("button", name="Add user").click(); d = page.get_by_role("dialog", name="New user")
    d.get_by_label("Email *", exact=True).fill(f"kavya{RUN}@example.com"); d.get_by_label("Full name *", exact=True).fill("Kavya Desai")
    d.get_by_label("Role", exact=True).select_option("CLIENT"); d.get_by_label("Linked client", exact=True).select_option(label=CLIENT)
    d.get_by_label("Password * (8+ characters, letters and digits)", exact=True).fill("Kavya2026x"); d.get_by_role("button", name="Create user").click()
    page.wait_for_selector(f"[data-user='kavya{RUN}@example.com']")
    check("no browser errors or failed requests (staff)", not problems, "; ".join(problems[:5]))

    # Client portal as the client
    login(f"kavya{RUN}@example.com", "Kavya2026x"); page.wait_for_url("**/client-portal"); page.wait_for_selector("aside nav a[href='/client-portal']")
    nav = page.locator("aside nav").inner_text()
    check("a client lands on the portal and the sidebar shows only the portal", "Client Portal" in nav and "Dashboard" not in nav and "Catalogue" not in nav)
    page.goto(f"{WEB}/dashboard"); page.wait_for_url("**/client-portal")
    check("a client opening a staff URL is sent back to the portal", page.url.endswith("/client-portal"))
    page.wait_for_selector("[data-testid=portal-timeline]")
    check("the portal shows the completed project with its handover", "Handed over to Kavya Desai" in page.locator("main").inner_text())
    page.get_by_label("Your project").select_option(label="Desai farmhouse"); page.wait_for_selector("text=Approve quotation")
    page.get_by_role("button", name="Approve quotation").click(); page.wait_for_selector("text=Thank you — quotation approved.")
    check("the client approves a sent quotation in the portal", page.locator("[data-testid=portal-quotes] [data-status=APPROVED]").count() == 1)
    page.screenshot(path=f"{SHOTS}/ops_portal.png", full_page=True)
    check("no browser errors or failed requests (client)", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
