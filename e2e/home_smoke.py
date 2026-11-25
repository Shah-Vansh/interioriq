"""Real-browser test of whole-home design: pick a style and 'Design my home' (every room gets a layout + design concept), edit one room's
feature wall, place rooms on the home plan and download the whole-house DXF, view the whole home in 3D, download the design presentation
(also from the client portal)."""
import os, sys, tempfile, time
import httpx
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=180)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
cl = c.post(f"{API}/clients", json={"name": f"Home Hema {RUN}", "phone": f"91{RUN}44"[:10]}, headers=H).json()
PN = f"HOME-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Hema residence", "client_id": cl["id"]}, headers=H).json()["id"]
for name, rt, L, W, ops in (("Verandah", "VERANDAH", 3600, 1800, [("DOOR", "N", 1300)]), ("Foyer", "FOYER", 1800, 1500, [("DOOR", "S", 400)]),
                            ("Living", "LIVING", 5200, 4000, [("DOOR", "S", 300), ("WINDOW", "W", 1000)]), ("Kitchen", "KITCHEN", 3600, 3000, [("DOOR", "S", 2500)]),
                            ("Master bedroom", "MASTER_BEDROOM", 4250, 3600, [("DOOR", "S", 300), ("WINDOW", "E", 1200)]), ("Bath", "BATHROOM", 2400, 1800, [("DOOR", "S", 1400)]),
                            ("Pooja", "POOJA", 1500, 1200, [("DOOR", "S", 100)])):
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": name, "room_type": rt}, headers=H).json()["id"]
    for l, v in (("Length", L), ("Width", W), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    for k, w, o in ops:
        b = {"kind": k, "wall": w, "offset_mm": o, "width_mm": 900 if k == "DOOR" else 1400, "height_mm": 2100 if k == "DOOR" else 1300}
        b.update({"sill_mm": 800} if k == "WINDOW" else {"swing": "OUTWARD"})
        c.post(f"{API}/rooms/{rid}/openings", json=b, headers=H).raise_for_status()
c.post(f"{API}/users", json={"email": f"hema{RUN}@client.test", "full_name": "Hema", "role": "CLIENT", "password": "ChangeMe123!", "client_id": cl["id"]}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

def pdf_text(path): d = pdfium.PdfDocument(path); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = br.new_context(viewport={"width": 1500, "height": 950}, accept_downloads=True); page = ctx.new_page(); problems = []
    page.set_default_timeout(90000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    page.goto(f"{WEB}/design/home"); page.wait_for_selector(f"select[aria-label=Project] option:has-text('{PN}')", state="attached")
    page.get_by_label("Project", exact=True).select_option(label=f"{PN} · Hema residence"); page.locator("[data-style=traditional]").wait_for()
    page.locator("[data-style=traditional]").click(); page.get_by_role("button", name="Design my home — Traditional Indian").click()
    res = page.get_by_test_id("design-result"); res.wait_for(timeout=180000)
    check("Design my home styles every room", "applied to 7 room(s)" in res.inner_text(), res.inner_text()[:200])
    table = page.get_by_test_id("room-concepts"); table.get_by_text("Moisture-resistant grid ceiling").first.wait_for()   # the table reloads after the result
    check("room table shows feature walls and ceilings", "Backlit jaali panel" in table.inner_text() and "Moisture-resistant grid ceiling" in table.inner_text())
    page.get_by_role("button", name="Edit design of Living").click(); d = page.get_by_role("dialog", name="Edit room design"); d.wait_for()
    d.get_by_label("Feature wall").select_option("STONE"); d.get_by_role("button", name="Save design").click(); d.wait_for(state="detached"); page.wait_for_timeout(1200)
    check("room design edited (stone feature wall)", "Stone cladding" in page.locator("[data-room='Living']").inner_text())
    page.screenshot(path=f"{SHOTS}/home_concept.png", full_page=True)

    page.get_by_role("tab", name="Home plan").click(); page.get_by_role("button", name="Place new rooms").click(); page.get_by_test_id("home-plan").wait_for()
    check("all rooms on the home plan", page.locator("[data-plan-room]").count() == 7)
    with page.expect_download() as dl: page.get_by_role("button", name="Whole-house DXF").click()
    check("whole-house DXF downloads", "INSERT" in open(dl.value.path(), encoding="utf-8", errors="ignore").read())
    page.screenshot(path=f"{SHOTS}/home_plan.png")

    page.get_by_role("tab", name="Whole home 3D").click(); page.get_by_test_id("home-3d").locator("canvas").wait_for(); page.wait_for_timeout(6000)
    page.screenshot(path=f"{SHOTS}/home_3d.png")
    check("whole home renders in 3D", page.get_by_test_id("home-3d").locator("canvas").count() == 1)

    with page.expect_download() as dl: page.get_by_role("button", name="Design presentation (PDF)").click()
    t = pdf_text(dl.value.path())
    check("design presentation PDF", "Interior design proposal" in t and "Traditional Indian style" in t and "Stone cladding" in t and "Pooja" in t)
    page.get_by_role("tab", name="Design concept").click()
    with page.expect_download() as dl: page.get_by_role("button", name="Working drawings (PDF)").click()
    t = pdf_text(dl.value.path())
    check("working drawings PDF (site sheets in feet-inches)", all(s in t for s in ("INTERIOR FOR RESIDENTIAL", "LIGHT DETAIL", "MASTER BEDROOM", "ELEVATION", "COUNTER PLAN", "ALL DIMENSIONS IN FEET")))
    page.get_by_label("Drawing units").select_option("mm")
    with page.expect_download() as dl: page.get_by_role("button", name="Working drawings of Kitchen").click()
    t = pdf_text(dl.value.path())
    check("one room's drawings in millimetres", "COUNTER PLAN" in t and "MILLIMETRES" in t and "LIGHT DETAIL" not in t)
    page.get_by_label("Drawing units").select_option("ftin"); page.wait_for_timeout(500)
    check("no page errors", not problems, "; ".join(problems[:5]))

    cp = ctx.new_page(); cp.set_default_timeout(60000)
    cp.goto(f"{WEB}/login"); cp.fill("#email", f"hema{RUN}@client.test"); cp.fill("#password", "ChangeMe123!"); cp.click("button:has-text('Sign in')"); cp.wait_for_url("**/client-portal**")
    cp.get_by_text("Hema residence").first.click()
    with cp.expect_download() as dl: cp.get_by_role("button", name="Download design presentation").click()
    check("client downloads the presentation from the portal", "Interior design proposal" in pdf_text(dl.value.path()))
    br.close()

print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
