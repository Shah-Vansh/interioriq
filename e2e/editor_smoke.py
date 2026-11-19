"""Real-browser smoke test of the login -> 3D editor flow. Run via `bash e2e/run.sh` (starts both servers)."""
import os, re, sys
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
c = httpx.Client(timeout=30)
tok = c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
pid = c.post(f"{API}/projects", json={"project_number": "IQ-E2E", "name": "E2E"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master Bedroom", "room_type": "MASTER_BEDROOM"}, headers=H).json()["id"]
for label, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2750)):
    c.put(f"{API}/rooms/{rid}/measurements", json={"label": label, "value": v, "source": "USER_VERIFIED"}, headers=H)
design = c.post(f"{API}/rooms/{rid}/designs/generate", json={}, headers=H).json()
c.post(f"{API}/rooms/{rid}/designs", json={"objects": design["objects"]}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = br.new_page(viewport={"width": 1500, "height": 900}); problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)

    page.goto(f"{WEB}/design/3d"); page.wait_for_url("**/login", timeout=15000); check("unauthenticated -> /login", True)
    page.fill("input[type=password]", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/design/3d"); page.wait_for_selector("canvas", timeout=30000); page.wait_for_timeout(2500)
    page.get_by_role("button", name="Realistic").click(); page.wait_for_timeout(1500)     # pixel-exact drag checks run on the quick box view (software GL in CI is slow)
    check("saved design loads and validates", page.get_by_text("Objects (2)").count() == 1 and page.locator("text=/Valid · /").count() == 1)

    page.click("button:has-text('Top')"); page.wait_for_timeout(1200)
    page.get_by_role("button", name=re.compile("King Bed")).click()
    x = lambda: float(page.locator("label:has-text('X (east)') input").input_value())
    x0 = x(); page.keyboard.press("ArrowRight"); page.keyboard.press("ArrowRight"); page.wait_for_timeout(300)
    check("arrow keys nudge +100mm", abs(x() - (x0 + 100)) < 0.01)
    page.keyboard.press("Control+z"); page.keyboard.press("Control+z"); page.wait_for_timeout(300)
    check("undo restores + Unsaved clears", abs(x() - x0) < 0.01 and page.get_by_text("Unsaved").count() == 0)

    box = page.locator("canvas").bounding_box(); cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    ppm = min(box["width"] / (4.25 * 1.3), box["height"] / (3.6 * 1.3))      # orthographic top view: pixels per metre
    bed = (cx, cy - 0.735 * ppm)
    page.mouse.move(*bed); page.mouse.down(); page.mouse.move(bed[0] + 0.3 * ppm, bed[1] + 0.1 * ppm, steps=8)
    page.mouse.move(bed[0] + 0.6 * ppm, bed[1] + 0.2 * ppm, steps=8); page.mouse.up(); page.wait_for_timeout(500)
    check("mouse drag moves bed ~+600mm, snapped to 50", 550 <= x() - x0 <= 650 and x() % 50 == 0, f"{x0} -> {x()}")
    page.keyboard.press("Control+z"); page.wait_for_timeout(300); check("a drag is ONE undo step", abs(x() - x0) < 0.01)

    page.mouse.move(*bed); page.mouse.down(); page.mouse.move(cx - 0.725 * ppm, cy + 1.45 * ppm, steps=15); page.mouse.up()
    page.wait_for_selector("text=/problem\\(s\\)/", timeout=8000); check("overlap is flagged by the server", page.locator("text=Collision").count() >= 1)
    page.keyboard.press("Control+z"); page.wait_for_selector("text=/Valid · /", timeout=8000); check("undo restores a valid layout", True)

    page.click("button:has-text('3D')"); page.wait_for_timeout(1000); page.keyboard.press("ArrowUp"); page.wait_for_timeout(300)
    page.get_by_role("button", name="Save version").click(); page.wait_for_selector("text=Saved as version 2", timeout=8000)
    check("save creates version 2", True)

    for r in ["crm", "design", "catalogue", "estimation", "execution", "reports", "settings"]:   # breadcrumb parents must not 404
        page.goto(f"{WEB}/{r}")
        try: page.wait_for_url(lambda u: u.rstrip("/") != f"{WEB}/{r}", timeout=10000); page.wait_for_selector("main h1", timeout=10000)
        except Exception: pass
        check(f"/{r} redirects to a real page", page.locator("main h1").count() == 1 and page.url.rstrip("/") != f"{WEB}/{r}")
    br.close()

check("no browser errors / failed requests", not problems, str(problems) if problems else "")
print("RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
