"""Real-browser test of M19 doors & windows: record openings on Survey → Rooms (overlap refused; a door behind the wardrobe flags the saved
design), see them on the plan / elevations / electrical drawings (switchboard beside the door), the 3D editor flags the wardrobe, and a newly
generated layout keeps the door clear."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-DW-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Doors & windows flat"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Guest bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
c.post(f"{API}/rooms/{rid}/designs", json={"objects": [
    dict(id="bed", name="King Bed — Walnut", category="Bed", sku="BED-KNG-WLT-001", price=124000, x=1110, y=1520, length=1930, width=2030, height=1200),
    dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H)

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
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    def pick_project():
        page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
        s = page.locator("main select").first; s.select_option(label=next(o for o in s.locator("option").all_inner_texts() if o.startswith(PN + " ·"))); page.wait_for_timeout(1200)

    # Survey → Rooms: add a door right behind the wardrobe
    page.goto(f"{WEB}/survey/rooms"); pick_project(); card = page.get_by_test_id("openings-card"); card.wait_for()
    card.get_by_label("Wall").select_option("S"); card.get_by_label("Offset").fill("100"); card.get_by_role("button", name="Add door").click()
    page.wait_for_selector("[data-opening-row='Door 1']")
    alert = card.locator("[role=alert]", has_text="Latest design")
    check("a door behind the wardrobe flags the saved design", alert.count() == 1 and "blocks Door 1" in alert.inner_text())
    check("the door is drawn on the room plan", card.locator("svg [data-opening=DOOR]").count() == 1)
    card.get_by_label("Opening type").select_option("WINDOW"); card.get_by_label("Wall").select_option("N"); card.get_by_label("Offset").fill("1500")
    card.get_by_label("Sill height").fill("900"); card.get_by_role("button", name="Add window").click(); page.wait_for_selector("[data-opening-row='Window 1']")
    check("window added and drawn", card.locator("svg [data-opening=WINDOW]").count() == 1)
    card.get_by_label("Opening type").select_option("DOOR"); card.get_by_label("Wall").select_option("S"); card.get_by_label("Offset").fill("500"); card.get_by_role("button", name="Add door").click()
    err = card.locator("[role=alert]", has_text="Overlaps"); err.wait_for()
    check("an overlapping door is refused with the reason", "Overlaps Door 1" in err.inner_text())
    page.screenshot(path=f"{SHOTS}/openings.png", full_page=True)

    # 3D editor: the server flags the wardrobe against the door
    page.goto(f"{WEB}/design/3d"); pick_project(); page.wait_for_selector("text=blocks Door 1", timeout=30000)
    check("3D editor shows the wardrobe blocking Door 1 (server validation)", page.locator("text=blocks Door 1").count() >= 1)

    # a new AI layout keeps the door clear and becomes the latest version
    g = c.post(f"{API}/rooms/{rid}/designs/generate", json={}, headers=H).json()
    check("generated layout is valid with the door", g["validation"]["valid"] is True, str(g["validation"]["errors"]))
    c.post(f"{API}/rooms/{rid}/designs", json={"objects": g["objects"]}, headers=H)

    # drawings
    page.goto(f"{WEB}/design/plans"); pick_project(); page.wait_for_selector("svg[aria-label='Floor plan'] [data-opening=DOOR]")
    check("floor plan shows the door and the window", page.locator("svg[aria-label='Floor plan'] [data-opening]").count() == 2)
    page.goto(f"{WEB}/design/electrical"); pick_project(); page.wait_for_selector("[data-point=SWITCHBOARD]")
    sb = page.locator("[data-point=SWITCHBOARD]").inner_text()
    check("switchboard placed beside Door 1, no assumption left", "beside Door 1" in sb and "ASSUMED" not in page.locator("main").inner_text(), sb)
    page.goto(f"{WEB}/design/elevations"); pick_project(); page.wait_for_selector("[data-elev-opening]")
    check("elevations show the door (south) and window (north)", page.locator("svg[data-wall=SOUTH] [data-elev-opening=DOOR]").count() == 1 and page.locator("svg[data-wall=NORTH] [data-elev-opening=WINDOW]").count() == 1)

    # removing the door clears it
    page.goto(f"{WEB}/survey/rooms"); pick_project(); card = page.get_by_test_id("openings-card"); page.wait_for_selector("[data-opening-row='Door 1']")
    card.get_by_role("button", name="Remove Door 1").click(); page.wait_for_selector("[data-opening-row='Door 1']", state="detached")
    check("door removed", card.locator("[data-opening-row]").count() == 1)
    check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
