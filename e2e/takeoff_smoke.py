"""Real-browser test of M18 material take-off: map catalogue items on Estimation → Take-off (unit mismatch refused), preview the quantities
for a saved design, and create BOQs with the take-off switch on (tagged lines, warnings for unmapped items) and off (furniture only).
Resets the rules at the end so later suites keep furniture-only BOQs."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")   # override when 8000/3000 are taken
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=30)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
mk = lambda **kw: c.post(f"{API}/catalogue/items", json=kw, headers=H).json()
gyp = mk(sku=f"E2E-GYP-{RUN}", name=f"Gypsum board ceiling {RUN}", kind="MATERIAL", category="Ceiling", unit="sq.m", price="85")
dl = mk(sku=f"E2E-DL-{RUN}", name=f"Downlight 7W {RUN}", kind="LIGHTING", category="Downlight", unit="No.", price="450")
paint = mk(sku=f"E2E-PNT-{RUN}", name=f"Royale emulsion {RUN}", kind="MATERIAL", category="Paint", unit="sq.ft", price="22")
tile = mk(sku=f"E2E-TILE-{RUN}", name=f"Vitrified tiles {RUN}", kind="MATERIAL", category="Flooring", unit="box", price="1200")
PN = f"IQ-TKO-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Take-off home"}, headers=H).json()["id"]
rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Master", "room_type": "BEDROOM"}, headers=H).json()["id"]
for l, v in (("Length", 4250), ("Width", 3600), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
c.post(f"{API}/rooms/{rid}/designs", json={"objects": [
    dict(id="bed", name="King Bed — Walnut", category="Bed", sku="BED-KNG-WLT-001", price=124000, x=1110, y=1520, length=1930, width=2030, height=1200),
    dict(id="war", name="6-Door Wardrobe", category="Wardrobe", sku="WAR-SLD-WLT-001", price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H)

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

try:
    with sync_playwright() as p:
        br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}); problems = []
        page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
        page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
        page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (409, 422) else None)
        page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

        # map items; a box-priced item for an area is refused
        page.goto(f"{WEB}/estimation/takeoff"); page.wait_for_selector("[data-rule=FLOORING] select option", state="attached")
        page.wait_for_selector(f"[data-rule=FLOORING] option[value='{tile['sku']}']", state="attached")
        page.get_by_label("Item for Flooring").select_option(value=tile["sku"]); page.get_by_role("button", name="Save rules").click()
        err = page.locator("main [role=alert]"); err.wait_for()
        check("an area priced per box is refused with the reason", "sold per box" in err.inner_text(), err.inner_text())
        page.get_by_label("Item for Flooring").select_option(value="")
        page.get_by_label("Item for Gypsum false ceiling").select_option(value=gyp["sku"]); page.get_by_label("Item for Downlights").select_option(value=dl["sku"])
        page.get_by_label("Item for Wall paint (walls not hidden by tall units)").select_option(value=paint["sku"])
        page.get_by_label("Waste for Wall paint (walls not hidden by tall units)").fill("10")
        page.get_by_role("button", name="Save rules").click(); page.wait_for_selector("[role=status] >> text=Take-off rules saved")
        check("take-off rules saved", True)

        # preview for the saved design
        pick = [s for s in page.locator("main select").all() if any(o.startswith(PN + " ·") for o in s.locator("option").all_inner_texts())][0]
        pick.select_option(label=next(o for o in pick.locator("option").all_inner_texts() if o.startswith(PN + " ·")))
        page.wait_for_selector("[data-takeoff=CEILING_GYPSUM]")
        gy = page.locator("[data-takeoff=CEILING_GYPSUM]").inner_text(); pt = page.locator("[data-takeoff=WALL_PAINT]").inner_text()
        check("preview: gypsum 15.3 sq.m + 5% → buys 16.07 sq.m", "15.3 sq.m" in gy and "16.07 sq.m" in gy and "added to BOQ" in gy, gy)
        check("preview: paint 38.27 sq.m + 10% → buys 454 sq.ft", "38.27 sq.m" in pt and "454 sq.ft" in pt, pt)
        check("preview: unmapped flooring is shown, not guessed", "no item mapped" in page.locator("[data-takeoff=FLOORING]").inner_text())
        page.screenshot(path=f"{SHOTS}/takeoff.png", full_page=True)

        # BOQ with take-off on, then off
        page.goto(f"{WEB}/estimation/boq")
        page.wait_for_selector(f"select option:has-text('{PN}')", state="attached")
        s0 = page.locator("select").first; s0.select_option(label=next(o for o in s0.locator("option").all_inner_texts() if o.startswith(PN))); page.wait_for_timeout(900)
        sw = page.get_by_role("switch", name="Include material take-off"); sw.wait_for()
        check("take-off switch starts ON once rules are mapped", sw.get_attribute("aria-checked") == "true")
        page.get_by_role("button", name="Create BOQ").first.click(); page.wait_for_selector("[data-testid=grand-total]")
        page.wait_for_selector("[data-testid=takeoff-tag]")
        check("BOQ has 3 take-off lines (gypsum, downlights, paint), tagged", page.get_by_test_id("takeoff-tag").count() == 3)
        body = page.locator("main").inner_text()
        check("BOQ shows the measured basis and warns about unmapped quantities", "16.07 sq.m" in body and "454 sq.ft" in body and "Take-off: Flooring" in body)
        total_on = page.get_by_test_id("grand-total").inner_text()
        sw.click(); page.get_by_role("button", name="Create BOQ").first.click(); page.wait_for_timeout(1500); page.wait_for_selector("[data-testid=grand-total]")
        check("with the switch off the new BOQ is furniture only and cheaper", page.get_by_test_id("takeoff-tag").count() == 0 and page.get_by_test_id("grand-total").inner_text() != total_on)
        check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
        br.close()
finally:
    c.put(f"{API}/takeoff/rules", json={k: {"sku": None} for k in ("CEILING_GYPSUM", "DOWNLIGHT", "WALL_PAINT", "FLOORING")}, headers=H)

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
