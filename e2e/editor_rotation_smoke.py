"""Real-browser test of M30 editor upgrades: turn an object by any angle (typed or ±15° buttons) and the SERVER re-validates the turned
footprint, set a colour, save → the version stores rotation + colour; switching room with unsaved edits asks first (Cancel keeps you in
the room and your edits; OK switches)."""
import os, re, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-ROT-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Rotate flat"}, headers=H).json()["id"]
rooms = []
for name in ("Living room", "Study"):
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": name, "room_type": "LIVING"}, headers=H).json()["id"]
    for l, v in (("Length", 4500), ("Width", 3600), ("Ceiling Height", 2750)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    rooms.append(rid)
objs = [dict(id="ct", name="Coffee table", category="Coffee Table", x=1750, y=1500, length=1000, width=500, height=400, price=12000),
        dict(id="sf", name="Sofa", category="Sofa", x=1250, y=200, length=2000, width=900, height=850, price=60000)]
c.post(f"{API}/rooms/{rooms[0]}/designs", json={"objects": objs}, headers=H).raise_for_status()

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = br.new_page(viewport={"width": 1500, "height": 950}); problems = []
    page.set_default_timeout(60000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/design/3d"); page.wait_for_selector(f"select[aria-label=Project] option:has-text('{PN}')", state="attached")
    page.get_by_label("Project", exact=True).select_option(label=f"{PN} · Rotate flat"); page.wait_for_selector("canvas"); page.wait_for_selector("text=/Valid · /")
    check("realistic view is on by default", page.get_by_role("button", name="Realistic").get_attribute("aria-pressed") == "true")
    page.get_by_role("button", name="Realistic").click(); page.wait_for_timeout(1500)      # editing checks on the quick box view (software GL in CI is slow)
    page.get_by_role("button", name=re.compile("Coffee table")).click()
    rot = page.get_by_label("Rotation degrees")
    rot.fill("45"); rot.press("Enter"); page.wait_for_timeout(1500)
    check("typed 45° is applied and the layout is still valid", page.get_by_text("turned 45°").count() == 1 and page.locator("text=/Valid · /").count() == 1)
    page.get_by_role("button", name="Turn 15 degrees anticlockwise").click(); page.wait_for_timeout(800)
    check("+15° button → 60°", page.get_by_text("turned 60°").count() == 1)
    # turn the sofa 90° about its centre: 2000 long becomes 2000 deep and hits the coffee table → server flags it
    page.get_by_role("button", name=re.compile("^Sofa")).click(); rot = page.get_by_label("Rotation degrees"); rot.fill("90"); rot.press("Enter")
    page.wait_for_selector("text=/problem\\(s\\)/", timeout=10000)
    check("server flags the collision of the TURNED sofa", page.locator("text=Collision").count() >= 1)
    page.keyboard.press("Control+z"); page.wait_for_selector("text=/Valid · /", timeout=10000)
    page.get_by_role("button", name=re.compile("Coffee table")).click()
    page.get_by_label("Object colour").fill("#8b5a2b"); page.wait_for_timeout(500)
    check("unsaved marker shows", page.get_by_text("Unsaved").count() == 1)
    page.screenshot(path=f"{SHOTS}/editor_rotation.png")

    # switching room with unsaved edits asks first
    page.once("dialog", lambda d: d.dismiss())
    page.get_by_label("Room", exact=True).select_option(rooms[1]); page.wait_for_timeout(800)
    check("Cancel keeps the room and the edits", page.get_by_label("Room", exact=True).input_value() == rooms[0] and page.get_by_text("Unsaved").count() == 1)
    page.get_by_role("button", name="Save version").click(); page.wait_for_selector("text=Saved as version 2", timeout=10000)
    v = c.get(f"{API}/rooms/{rooms[0]}/designs/2", headers=H).json()
    ct = next(o for o in (v.get("design_json") or v)["objects"] if o["id"] == "ct")
    check("saved version stores rotation and colour", ct.get("rotation") == 60 and (ct.get("colour") or "").lower() == "#8b5a2b", str(ct))
    page.get_by_role("button", name=re.compile("Coffee table")).click(); page.get_by_role("button", name="Turn 15 degrees clockwise").click(); page.wait_for_timeout(500)
    page.once("dialog", lambda d: d.accept())
    page.get_by_label("Room", exact=True).select_option(rooms[1]); page.wait_for_timeout(1500)
    check("OK switches to the other room", page.get_by_label("Room", exact=True).input_value() == rooms[1])
    # realistic view: eye level, evening with lights — no errors
    page.get_by_role("button", name="Realistic").click(); page.wait_for_timeout(3000)
    check("realistic view switched back on", page.get_by_role("button", name="Realistic").get_attribute("aria-pressed") == "true")
    page.get_by_role("button", name="Eye level").click(); page.wait_for_timeout(2500)
    page.get_by_label("Time of day").fill("20"); page.wait_for_timeout(1500)
    page.screenshot(path=f"{SHOTS}/editor_eye_level_evening.png")
    check("eye-level evening view renders", page.locator("canvas").count() == 1)
    page.get_by_role("button", name="Realistic").click(); page.wait_for_timeout(1500)
    check("quick box view can be switched back", page.get_by_role("button", name="Realistic").get_attribute("aria-pressed") == "false")
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
