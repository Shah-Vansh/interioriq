"""Real-browser test of M41 room shells: on Survey → Rooms make a room L-shaped, set a sloped ceiling, add a beam and a column, put a door on
the inner wall of the L; a generated layout keeps clear of all of it; the plan, elevations, ceiling drawings and the 3D editor draw it; the
working drawings print it."""
import os, sys, tempfile, time
import httpx
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=120)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-SH-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Odd-shaped flat"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master bedroom", "room_type": "MASTER_BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4800), ("Width", 4200), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

def pdf_text(b): d = pdfium.PdfDocument(b); return "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))

with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = br.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True); page = ctx.new_page(); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    def pick_project():
        page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
        s = page.locator("main select").first; s.select_option(label=next(o for o in s.locator("option").all_inner_texts() if o.startswith(PN + " ·"))); page.wait_for_timeout(1200)

    page.goto(f"{WEB}/survey/rooms"); pick_project(); card = page.get_by_test_id("shell-card"); card.wait_for()
    # L-shape: cut the north-east corner 1500 × 1500
    card.get_by_label("Room shape", exact=True).select_option("CUTS"); card.get_by_label("Cut NE corner").check()
    card.get_by_label("NE cut length").fill("1500"); card.get_by_label("NE cut width").fill("1500"); card.get_by_role("button", name="Save shape").click()
    page.wait_for_selector("text=Room shape saved")
    check("L-shaped room saved (6 walls, area less the cut)", "6 walls" in card.get_by_test_id("shell-summary").inner_text() and "17.91 sq.m" in card.get_by_test_id("shell-summary").inner_text(),
          card.get_by_test_id("shell-summary").inner_text())
    check("plan draws the L", card.locator("[data-outline='6']").count() == 1)
    # a cut too big is refused with the reason
    card.get_by_label("NE cut length").fill("4700"); card.get_by_role("button", name="Save shape").click(); page.wait_for_selector("text=leaves less than")
    check("impossible cut refused with a reason", page.locator("text=leaves less than").count() >= 1)
    card.get_by_label("NE cut length").fill("1500")
    # sloped ceiling
    card.get_by_label("Ceiling type").select_option("SLOPED"); card.get_by_label("Lowest ceiling").fill("2700"); card.get_by_label("Highest ceiling").fill("3300")
    card.get_by_label("High side").select_option("N"); card.get_by_role("button", name="Save ceiling").click(); page.wait_for_selector("text=Ceiling saved")
    check("sloped ceiling saved", "ceiling 2700–3300 mm" in card.get_by_test_id("shell-summary").inner_text())
    # beam + column
    card.get_by_label("Structure type").select_option("BEAM"); card.get_by_label("Structure x").fill("0"); card.get_by_label("Structure y").fill("2000")
    card.get_by_label("Structure length").fill("4800"); card.get_by_label("Structure width").fill("230"); card.get_by_label("Structure depth").fill("450")
    card.get_by_role("button", name="Add beam").click(); page.wait_for_selector("[data-structure-row='Beam 1']")
    card.get_by_label("Structure type").select_option("COLUMN"); card.get_by_label("Structure x").fill("0"); card.get_by_label("Structure y").fill("0")
    card.get_by_label("Structure length").fill("350"); card.get_by_label("Structure width").fill("350"); card.get_by_role("button", name="Add column").click()
    page.wait_for_selector("[data-structure-row='Column 1']")
    check("beam and column recorded and drawn", card.locator("[data-structure=BEAM]").count() == 1 and card.locator("[data-structure=COLUMN]").count() == 1)
    # door on the inner wall of the L (wall 4 = x 3300, y 2700→4200)
    oc = page.get_by_test_id("openings-card"); oc.wait_for()
    oc.get_by_label("Wall").select_option("e3"); oc.get_by_label("Offset").fill("300"); oc.get_by_role("button", name="Add door").click()
    page.wait_for_selector("[data-opening-row='Door 1']")
    check("door on the inner wall of the L", "Wall 4" in oc.locator("[data-opening-row='Door 1']").inner_text())
    page.screenshot(path=f"{SHOTS}/shape_survey.png", full_page=True)

    g = c.post(f"{API}/rooms/{rid}/designs/generate", json={"catalogue_filter_in_stock": False}, headers=H).json()
    bed = next(o for o in g["objects"] if o["category"] == "Bed")
    check("generated layout is valid and avoids the cut + column", g["validation"]["valid"] and not (bed["x"] + bed["length"] > 3300 and bed["y"] + bed["width"] > 2700)
          and not any(o["x"] < 350 and o["y"] < 350 for o in g["objects"]), str(g["validation"]["errors"]))
    c.post(f"{API}/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=H).raise_for_status()

    page.goto(f"{WEB}/design/plans"); pick_project(); page.wait_for_selector("svg[aria-label='Floor plan'] [data-outline='6']")
    check("design plan draws the L, beam, column and the door", page.locator("svg[aria-label='Floor plan'] [data-structure]").count() == 2 and page.locator("svg[aria-label='Floor plan'] [data-opening=DOOR]").count() == 1)
    page.goto(f"{WEB}/design/elevations"); pick_project(); page.wait_for_selector("[data-wall=WEST]")
    check("elevations show the sloped ceiling and the beam", page.locator("[data-wall=WEST] [data-ceiling-line]").count() == 1 and page.locator("[data-wall=WEST] [data-elev-structure=BEAM]").count() == 1)
    page.screenshot(path=f"{SHOTS}/shape_elevations.png", full_page=True)
    page.goto(f"{WEB}/design/3d"); pick_project(); page.locator("canvas").first.wait_for(); page.wait_for_timeout(6000)
    page.screenshot(path=f"{SHOTS}/shape_3d.png")
    check("3D editor renders the shaped room", page.locator("canvas").count() >= 1)
    r = c.get(f"{API}/projects/{pid}/drawing-set.pdf", params={"room_id": rid}, headers=H)
    t = pdf_text(r.content)
    check("working drawings print the beam and the column", "BEAM 1" in t and "COLUMN 1" in t and "U/S" in t, t[:200])
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
