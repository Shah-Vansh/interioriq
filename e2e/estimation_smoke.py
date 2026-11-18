"""Real-browser test: design -> BOQ -> PDF. Expected totals were derived by hand, independently of the code."""
import os, sys
import httpx, pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}

def project(number, name):
    pid = c.post(f"{API}/projects", json={"project_number": number, "name": name}, headers=H).json()["id"]
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
    for label, v in (("Length", 4250), ("Width", 3600)):
        c.put(f"{API}/rooms/{rid}/measurements", json={"label": label, "value": v, "source": "USER_VERIFIED"}, headers=H)
    return rid

good = project("IQ-EST", "BOQ E2E")                                    # bed (124,000) + wardrobe (185,000) from the catalogue
design = c.post(f"{API}/rooms/{good}/designs/generate", json={}, headers=H).json()
c.post(f"{API}/rooms/{good}/designs", json={"objects": design["objects"]}, headers=H)
bad = project("IQ-EST-BAD", "Invalid layout")                          # two chairs on top of each other
chair = dict(id="a", name="Chair", category="Chair", sku="", price=100, x=100, y=100, length=500, width=500, height=800)
c.post(f"{API}/rooms/{bad}/designs", json={"objects": [chair, {**chair, "id": "b", "x": 300}]}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)
def text_of(path):
    d = pdfium.PdfDocument(path); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1500, "height": 1000}); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and "/boq" not in r.url else None)
    page.goto(f"{WEB}/login"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    def pick(label):
        page.wait_for_selector(f"select option:has-text('{label.split(' ')[0]}')", state="attached", timeout=10000)
        page.locator("select").first.select_option(label=label); page.wait_for_timeout(900)

    page.goto(f"{WEB}/estimation/boq"); pick("IQ-EST · BOQ E2E")
    page.wait_for_selector("text=v1"); page.get_by_role("button", name="Create BOQ").click()
    page.wait_for_selector("[data-testid=grand-total]", timeout=10000)
    check("grand total shown = hand-calculated 4,76,753.19", page.locator("[data-testid=grand-total]").inner_text() == "Rs. 4,76,753.19", page.locator("[data-testid=grand-total]").inner_text())
    check("both catalogue items are listed with their SKUs", page.get_by_text("BED-KNG-WLT-001").count() >= 1 and page.get_by_text("WAR-SLD-WLT-001").count() >= 1)
    page.screenshot(path="/tmp/shots/boq.png")

    with page.expect_download() as dl: page.get_by_role("button", name="Quotation PDF").click()
    d = dl.value; txt = text_of(d.path())
    check("downloaded PDF is named after the quotation number", d.suggested_filename == "QT-IQ-EST-01.pdf", d.suggested_filename)
    check("the PDF contains the same total, the quotation number and the items", all(s in txt for s in ("4,76,753.19", "QT-IQ-EST-01", "King Bed", "6-Door Wardrobe")))

    page.get_by_text("Rates used for new BOQs").click(); page.get_by_label("Labour %").fill("0")
    page.get_by_role("button", name="Create BOQ").click(); page.wait_for_selector("text=QT-IQ-EST-02", timeout=10000)
    check("labour 0% gives the second hand-calculated total 4,41,438.14", page.locator("[data-testid=grand-total]").inner_text() == "Rs. 4,41,438.14", page.locator("[data-testid=grand-total]").inner_text())
    page.get_by_role("button", name="QT-IQ-EST-01").click(); page.wait_for_timeout(600)
    check("the first BOQ is unchanged (versions are frozen)", page.locator("[data-testid=grand-total]").inner_text() == "Rs. 4,76,753.19")

    page.goto(f"{WEB}/estimation/quotations"); pick("IQ-EST · BOQ E2E"); page.wait_for_selector("tbody tr")
    check("Quotations lists both versions", page.locator("tbody tr").count() == 2)
    with page.expect_download() as dl2: page.get_by_role("button", name="PDF").first.click()
    check("a quotation PDF downloads from the Quotations page", dl2.value.suggested_filename.endswith(".pdf") and "Grand total" in text_of(dl2.value.path()))

    page.goto(f"{WEB}/estimation/boq"); pick("IQ-EST-BAD · Invalid layout"); page.wait_for_selector("text=has errors")
    check("an invalid design cannot be priced (button disabled, reason shown)", page.get_by_role("button", name="Create BOQ").is_disabled() and page.get_by_text("can't be priced").count() == 1)
    br.close()

check("no browser errors", not problems, str(problems) if problems else "")
print("RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
