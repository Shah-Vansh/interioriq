"""Real-browser test of M9 Catalogue: suppliers (GSTIN check digit, duplicate phone), add a furniture item, change its price with a reason,
move stock in/out, archive it (the 3D editor's catalogue stops offering it), import materials from CSV (bad file refused with row numbers,
good file applied), export CSV, the BOQ shows the supplier, and a designer sees the catalogue read-only."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
TMP = tempfile.mkdtemp()
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}

_G = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def gstin(body14):
    t = 0
    for i, ch in enumerate(body14):
        p = _G.index(ch) * (2 if i % 2 else 1); t += p // 36 + p % 36
    return body14 + _G[(36 - t % 36) % 36]

GST = gstin(f"24AAACS{RUN[-4:]}C1Z")
BAD_GST = GST[:14] + ("A" if GST[14] != "A" else "B")
SUP = f"Shree Laminates {RUN}"; PHONE = f"97{RUN}33"[:10]
SKU = f"BED-QN-{RUN}"; NAME = f"Queen bed oak {RUN}"

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    page.goto(f"{WEB}/login"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    # ── Suppliers ──
    page.goto(f"{WEB}/catalogue/suppliers"); page.get_by_role("button", name="Add supplier").click()
    d = page.get_by_role("dialog", name="New supplier")
    d.get_by_label("Name *", exact=True).fill(SUP); d.get_by_label("Phone", exact=True).fill(f"+91 {PHONE[:5]} {PHONE[5:]}")
    d.get_by_label("City", exact=True).fill("Surat"); d.get_by_label("Lead time (days)", exact=True).fill("7"); d.get_by_label("GSTIN", exact=True).fill(BAD_GST)
    d.get_by_role("button", name="Create supplier").click(); err = d.get_by_role("alert"); err.wait_for()
    check("a GSTIN with a wrong check digit is refused", "check digit" in err.inner_text(), err.inner_text())
    d.get_by_label("GSTIN", exact=True).fill(GST.lower()); d.get_by_role("button", name="Create supplier").click()
    page.wait_for_selector(f"td >> text={SUP}")
    row = page.locator(f"tr:has-text('{SUP}')").inner_text()
    check("supplier saved with GSTIN upper-cased and lead time", GST in row and "7 days" in row, row)
    page.get_by_role("button", name="Add supplier").click(); d = page.get_by_role("dialog", name="New supplier")
    d.get_by_label("Name *", exact=True).fill("Someone Else"); d.get_by_label("Phone", exact=True).fill(f"0{PHONE}")
    d.get_by_role("button", name="Create supplier").click(); err = d.get_by_role("alert"); err.wait_for()
    check("the same phone typed with a leading 0 is a duplicate supplier", "already exists" in err.inner_text() and SUP in err.inner_text(), err.inner_text())
    page.keyboard.press("Escape")

    # ── Furniture: seeded rows, add an item ──
    page.goto(f"{WEB}/catalogue/furniture"); page.wait_for_selector("[data-sku='BED-KNG-WLT-001']")
    check("furniture page lists the real catalogue (seeded king bed with its size and price)",
          "1930 × 2030 × 1200 mm" in page.locator("[data-sku='BED-KNG-WLT-001']").inner_text() and "₹1,24,000.00" in page.locator("[data-sku='BED-KNG-WLT-001']").inner_text())
    page.get_by_role("button", name="Add furniture item").click(); d = page.get_by_role("dialog", name="New furniture item")
    d.get_by_label("SKU *", exact=True).fill(SKU.lower()); d.get_by_label("Price (₹) *", exact=True).fill("68,000")
    d.get_by_label("Name *", exact=True).fill(NAME); d.get_by_label("Category *", exact=True).fill("Bed")
    for lbl, v in (("Length (mm) *", "1650"), ("Width (mm) *", "2080"), ("Height (mm) *", "1100")): d.get_by_label(lbl, exact=True).fill(v)
    d.get_by_label("Material", exact=True).fill("Oak veneer"); d.get_by_label("Opening stock", exact=True).fill("3"); d.get_by_label("Reorder level", exact=True).fill("1")
    d.get_by_label("Supplier", exact=True).select_option(label=SUP)
    d.get_by_role("button", name="Create item").click()
    dd = page.get_by_role("dialog", name=NAME); dd.wait_for()
    check("new item opens with SKU upper-cased and price formatted", SKU in dd.inner_text() and "₹68,000.00" in page.get_by_test_id("current-price").inner_text())
    check("opening stock is in the stock history", "Opening stock" in page.get_by_test_id("stock-history").inner_text())

    # price change with reason
    dd.get_by_label("New price (₹)", exact=True).fill("71500"); dd.get_by_label("Reason for price change", exact=True).fill(f"Supplier rate revision {RUN}")
    dd.get_by_role("button", name="Change price").click(); page.wait_for_selector("[role=status] >> text=Price changed")
    ph = page.get_by_test_id("price-history").inner_text()
    check("price change is shown with old → new, reason and who", "₹68,000.00 → ₹71,500.00" in ph and f"Supplier rate revision {RUN}" in ph and "Admin User" in ph, ph[:200])

    # stock out / refused / in
    dd.get_by_label("Quantity", exact=True).fill("2"); dd.get_by_label("Reason for stock change", exact=True).fill("Issued to site IQ-1")
    dd.get_by_role("button", name="Stock out").click(); page.wait_for_selector("[role=status] >> text=Stock removed")
    check("stock out leaves 1 and flags it low", "Low: 1" in dd.inner_text())
    dd.get_by_label("Quantity", exact=True).fill("5"); dd.get_by_label("Reason for stock change", exact=True).fill("Issued again")
    dd.get_by_role("button", name="Stock out").click()
    check("removing more than is in stock is refused before sending", "Only 1 in stock" in dd.get_by_role("alert").inner_text())
    dd.get_by_label("Quantity", exact=True).fill("10"); dd.get_by_role("button", name="Stock in").click(); page.wait_for_selector("[role=status] >> text=Stock added")
    sh = page.get_by_test_id("stock-history").inner_text()
    check("stock ledger shows +10 → 11 and -2 → 1", "+10" in sh and "11 No." in sh and "-2" in sh, sh[:200])
    page.screenshot(path=f"{SHOTS}/catalogue_item.png")

    # archive: hidden from the editor's catalogue, visible under Archived, then restore
    dd.get_by_role("button", name="Archive").click(); page.wait_for_selector("[role=status] >> text=Archived")
    editor_skus = {i["sku"] for i in c.get(f"{API}/catalogue/furniture", headers=H).json()}
    check("an archived item is no longer offered to the 3D editor / designer", SKU not in editor_skus)
    page.keyboard.press("Escape"); page.wait_for_timeout(500)
    check("archived item is gone from the Active list", page.locator(f"[data-sku='{SKU}']").count() == 0)
    page.get_by_label("Status filter", exact=True).select_option("archived"); page.wait_for_selector(f"[data-sku='{SKU}']")
    page.locator(f"[data-sku='{SKU}']").click(); dd = page.get_by_role("dialog", name=NAME)
    dd.get_by_role("button", name="Restore").click(); page.wait_for_selector("[role=status] >> text=Restored")
    check("restored item is offered to the editor again", SKU in {i["sku"] for i in c.get(f"{API}/catalogue/furniture", headers=H).json()})
    page.keyboard.press("Escape")

    # ── Materials: CSV import ──
    page.goto(f"{WEB}/catalogue/materials"); page.wait_for_selector("text=Materials")
    bad = os.path.join(TMP, "bad.csv"); good = os.path.join(TMP, "materials.csv")
    open(bad, "w", encoding="utf-8").write(f"sku,name,category,unit,price,stock,supplier\nPLY-{RUN},BWP ply 18mm,Plywood,sheet,2850,40,{SUP}\n"
                                           f"LAM-{RUN},Laminate 1mm,Laminate,sheet,,10,\nMDF-{RUN},MDF 12mm,MDF,bucket,900,5,\n")
    open(good, "w", encoding="utf-8").write(f"sku,name,category,unit,price,stock,min_stock,supplier\nPLY-{RUN},BWP ply 18mm,Plywood,sheet,\"2,850\",40,10,{SUP}\n"
                                            f"LAM-{RUN},Laminate 1mm,Laminate,sheet,1450,3,5,\n")
    page.get_by_role("button", name="Import CSV").click(); d = page.get_by_role("dialog", name="Import CSV")
    d.get_by_label("CSV or Excel file", exact=True).set_input_files(bad); d.get_by_role("button", name="Preview").click()
    page.wait_for_selector("[data-testid=import-result]"); txt = d.inner_text()
    check("bad CSV: each problem is listed with its row number", "price is required" in txt and "unit must be one of" in txt and "2 with errors" in txt, txt[:300])
    check("bad CSV: the apply button is disabled", d.get_by_role("button", name="Fix the errors above, then preview again").is_disabled())
    d.get_by_label("CSV or Excel file", exact=True).set_input_files(good); d.get_by_role("button", name="Preview").click()
    page.wait_for_selector("text=Apply 2 changes"); d.get_by_role("button", name="Apply 2 changes").click()
    page.wait_for_selector("text=Imported: 2 created, 0 updated")
    check("nothing from the bad file was saved", not c.get(f"{API}/catalogue/items", params={"q": f"MDF-{RUN}", "status": "all"}, headers=H).json())
    page.keyboard.press("Escape"); page.wait_for_selector(f"[data-sku='PLY-{RUN}']")
    ply = page.locator(f"[data-sku='PLY-{RUN}']").inner_text()
    check("imported material shows price per sheet and its supplier", "₹2,850.00" in ply and "/ sheet" in ply and SUP in ply, ply)
    page.get_by_label("Stock filter", exact=True).select_option("ATTENTION"); page.wait_for_timeout(700)
    check("'Low or out of stock' filter shows the laminate (3 ≤ reorder 5) and not the ply", page.locator(f"[data-sku='LAM-{RUN}']").count() == 1 and page.locator(f"[data-sku='PLY-{RUN}']").count() == 0)
    page.get_by_label("Stock filter", exact=True).select_option("")
    with page.expect_download() as dl: page.get_by_role("button", name="Export CSV").click()
    exported = open(dl.value.path(), encoding="utf-8-sig").read()
    check("export CSV contains the imported rows", f"PLY-{RUN}" in exported and "2850.00" in exported and SUP in exported)
    # M29: Excel import + export
    from openpyxl import Workbook, load_workbook
    wb = Workbook(); ws = wb.active; ws.append(["Item Code", "Item Name", "Category", "Unit", "Rate", "Qty"]); ws.append([f"HDF-{RUN}", "HDF 8mm", "HDF", "sheet", 1199.5, 12])
    xl = os.path.join(TMP, "materials.xlsx"); wb.save(xl)
    page.get_by_role("button", name="Import CSV").click(); d = page.get_by_role("dialog", name="Import CSV")
    d.get_by_label("CSV or Excel file", exact=True).set_input_files(xl); d.get_by_role("button", name="Preview").click()
    page.wait_for_selector("text=Apply 1 change"); d.get_by_role("button", name="Apply 1 change").click(); page.wait_for_selector("text=Imported: 1 created")
    page.keyboard.press("Escape"); page.wait_for_selector(f"[data-sku='HDF-{RUN}']")
    check("Excel import created the item with its decimal price", "1,199.50" in page.locator(f"[data-sku='HDF-{RUN}']").inner_text())
    with page.expect_download() as dl: page.get_by_role("button", name="Export Excel").click()
    import io as _io; xs = load_workbook(_io.BytesIO(open(dl.value.path(), 'rb').read())).active; skus = [r[0] for r in xs.iter_rows(min_row=2, values_only=True)]
    check("Export Excel downloads a real workbook with the items", f"HDF-{RUN}" in skus and f"PLY-{RUN}" in skus)
    page.screenshot(path=f"{SHOTS}/catalogue_materials.png")

    # ── Supplier detail lists its items ──
    page.goto(f"{WEB}/catalogue/suppliers"); page.locator(f"tr:has-text('{SUP}')").click()
    page.wait_for_selector("[data-testid=supplier-items]"); si = page.get_by_test_id("supplier-items").inner_text()
    check("supplier shows the furniture and material it supplies", SKU in si and f"PLY-{RUN}" in si, si)
    page.keyboard.press("Escape")

    # ── BOQ carries the supplier ──
    pid = c.post(f"{API}/projects", json={"project_number": f"IQ-CAT-{RUN}", "name": "Catalogue check"}, headers=H).json()["id"]
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
    for label, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": label, "value": v, "source": "USER_VERIFIED"}, headers=H)
    obj = dict(id="b1", name=NAME, category="Bed", sku=SKU, price=71500, x=1300, y=1400, length=1650, width=2080, height=1100)
    c.post(f"{API}/rooms/{rid}/designs", json={"objects": [obj]}, headers=H)
    page.goto(f"{WEB}/estimation/boq")
    opt = page.locator(f"select option:has-text('IQ-CAT-{RUN}')"); opt.wait_for(state="attached", timeout=10000)
    page.locator("select").first.select_option(value=opt.get_attribute("value")); page.wait_for_selector("text=v1")
    page.get_by_role("button", name="Create BOQ").click(); page.wait_for_selector("[data-testid=grand-total]", timeout=10000)
    sup_line = page.get_by_test_id("line-supplier").first.inner_text()
    check("the BOQ line shows who supplies it", SUP in sup_line, sup_line)

    check("no browser errors or failed requests (admin)", not problems, "; ".join(problems[:5]))

    # ── Designer: read-only ──
    page.evaluate("localStorage.clear()"); page.goto(f"{WEB}/login")
    page.fill("#email", "kiran@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/catalogue/furniture"); page.wait_for_selector(f"[data-sku='{SKU}']")
    check("a designer can browse but sees no Add / Import buttons",
          page.get_by_role("button", name="Add furniture item").count() == 0 and page.get_by_role("button", name="Import CSV").count() == 0)
    page.locator(f"[data-sku='{SKU}']").click(); dd = page.get_by_role("dialog", name=NAME); dd.wait_for()
    check("a designer sees price history but cannot change price or stock",
          dd.get_by_role("button", name="Change price").count() == 0 and dd.get_by_role("button", name="Stock in").count() == 0 and "Supplier rate revision" in dd.inner_text())
    check("no browser errors or failed requests (designer)", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
