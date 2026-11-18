"""Real-browser test of M21 multi-room generation on Design → AI Designer: a living room (skip the armchair; door drawn; reasons shown),
a U-shaped kitchen saved and wired (chimney point on the electrical drawing, modules grouped in the BOQ), a bathroom refused until a layout
type is picked, and an out-of-stock TV unit reported (not invented) until 'Use only items in stock' is unticked."""
import os, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
PN = f"IQ-MR-{RUN}"
pid = c.post(f"{API}/projects", json={"project_number": PN, "name": "Whole flat"}, headers=H).json()["id"]
def room(name, rtype, L, W, door=None):
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": name, "room_type": rtype}, headers=H).json()["id"]
    for l, v in (("Length", L), ("Width", W), ("Ceiling Height", 2900)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    if door: c.post(f"{API}/rooms/{rid}/openings", json={"kind": "DOOR", "wall": door[0], "offset_mm": door[1], "width_mm": 900, "height_mm": 2100}, headers=H).raise_for_status()
    return rid
living = room("Living", "LIVING", 5200, 4000, ("S", 300)); kitchen = room("Kitchen", "KITCHEN", 3600, 3000, ("S", 2500)); bath = room("Bath", "BATHROOM", 2400, 1800)
items = c.get(f"{API}/catalogue/items", params={"q": "TVU-"}, headers=H).json(); items = items.get("items", items) if isinstance(items, dict) else items
tvs = [i for i in items if i["category"] == "TV Unit" and i["stock"] > 0]

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1100}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "422" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status != 422 else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")
    page.goto(f"{WEB}/design/ai")
    page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
    sels = page.locator("main select")
    def pick_room(name):
        sels.nth(0).select_option(label=f"{PN} · Whole flat"); page.wait_for_selector(f"main select >> nth=1 >> option:has-text('{name}')", state="attached")
        sels.nth(1).select_option(label=name); page.wait_for_timeout(1200)
    gen = lambda: page.get_by_role("button", name="Generate").click()
    placed = lambda: page.locator("[data-placed]").evaluate_all("els => els.map(e => e.dataset.placed)")

    # living room
    pick_room("Living")
    check("living room picked → layout type follows the room", page.get_by_label("Layout type").input_value() == "LIVING")
    page.get_by_label("Include Armchair").uncheck(); gen(); page.get_by_test_id("layout-notes").wait_for()
    cats = placed()
    check("living layout valid", "Valid layout" in page.get_by_test_id("layout-validation").inner_text())
    check("sofa, TV unit and coffee table placed; armchair skipped", {"Sofa", "TV Unit", "Coffee Table"} <= set(cats) and "Armchair" not in cats, str(cats))
    notes = page.get_by_test_id("layout-notes").inner_text()
    check("reasons explain sofa ↔ TV viewing distance", "opposite" in notes and " m from the sofa" in notes)
    check("door drawn on the preview", page.get_by_test_id("layout-preview").locator("[data-opening=DOOR]").count() == 1)
    check("total shown from the server's string", page.get_by_test_id("layout-total").inner_text().startswith("₹"))
    page.get_by_role("button", name="Save as new version").click(); page.wait_for_selector("text=Saved as version 1")
    check("living layout saved as v1", True)
    # style + budget: a luxury pick, then a 2-lakh brief that has to swap / drop items
    page.get_by_label("Style").select_option("luxury"); gen(); page.wait_for_selector("[data-testid=layout-notes] >> text=Style 'luxury'")
    check("style picker → luxury sofa chosen", page.locator("[data-placed=Sofa]", has_text="Leather").count() == 1)
    page.get_by_label("Design brief").fill("living room under 2 lakh"); gen(); page.wait_for_selector("text=Within your")
    notes = page.get_by_test_id("layout-notes").inner_text()
    check("2-lakh brief: total brought within budget and the swaps explained", "To fit the" in notes or "Left out to stay within budget" in notes, notes[-200:])
    page.get_by_label("Style").select_option(""); page.get_by_label("Design brief").fill("")
    page.screenshot(path=f"{SHOTS}/ai_living.png", full_page=True)

    # kitchen, forced U
    pick_room("Kitchen")
    check("kitchen shape option appears", page.get_by_label("Kitchen shape").count() == 1)
    page.get_by_label("Kitchen shape").select_option("U"); gen(); page.get_by_test_id("layout-notes").wait_for()
    knotes = page.get_by_test_id("layout-notes").inner_text(); kc = placed()
    check("U-shaped kitchen with a working aisle", "U-shaped kitchen" in knotes and kc.count("Kitchen") >= 3)
    check("sink + hob units placed, work triangle reported", "Kitchen Sink" in kc and "Kitchen Hob" in kc and "Work triangle" in knotes)
    check("wall cabinets hang over the counter (dashed on the plan)", kc.count("Kitchen Wall") >= 3 and page.get_by_test_id("layout-preview").locator("[data-wall-mounted]").count() == kc.count("Kitchen Wall"))
    check("filler panels close the gaps", "Kitchen Filler" in kc and "filler panel" in knotes, str(kc))
    page.get_by_role("button", name="Save as new version").click(); page.wait_for_selector("text=Saved as version 1")
    page.screenshot(path=f"{SHOTS}/ai_kitchen.png", full_page=True)
    page.goto(f"{WEB}/design/electrical"); page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
    s = page.locator("main select"); s.nth(0).select_option(label=f"{PN} · Whole flat")
    page.wait_for_selector("main select >> nth=1 >> option:has-text('Kitchen')", state="attached"); s.nth(1).select_option(label="Kitchen")
    page.wait_for_selector("tr[data-point=SOCKET]:has-text('Chimney point')")
    check("hob point, sink socket and under-cabinet lights on the electrical drawing", page.locator("tr[data-point=SOCKET]", has_text="under the sink").count() == 1
          and page.locator("tr[data-point=LIGHT]", has_text="Under-cabinet LED strip").count() >= 3)
    page.wait_for_selector("tr[data-point=SOCKET]:has-text('16A hob point')")
    n_sock = page.locator("tr[data-point=SOCKET]", has_text="counter socket").count(); n_ac = page.locator("tr[data-point=AC]").count()
    check("electrical drawing for the kitchen: chimney + counter sockets, no AC", n_sock >= 2 and n_ac == 0, f"sockets={n_sock} ac={n_ac}")
    page.goto(f"{WEB}/design/elevations"); page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached")
    s2 = page.locator("main select"); s2.nth(0).select_option(label=f"{PN} · Whole flat")
    page.wait_for_selector("main select >> nth=1 >> option:has-text('Kitchen')", state="attached"); s2.nth(1).select_option(label="Kitchen")
    page.wait_for_selector("[data-elev-item^='Kitchen Wall Cabinet']")
    above = page.evaluate("""() => [...document.querySelectorAll('svg')].some(svg => {
        const w = svg.querySelector("[data-elev-item^='Kitchen Wall Cabinet'] rect"), b = svg.querySelector("[data-elev-item^='Kitchen Base'] rect, [data-elev-item^='Kitchen Sink'] rect");
        if (!w || !b) return false; const W = w.getBoundingClientRect(), B = b.getBoundingClientRect(); return W.bottom < B.top })""")
    check("elevation draws wall cabinets above the base units (same wall)", above)
    v = c.get(f"{API}/rooms/{kitchen}/designs", headers=H).json()[-1]["version"]
    b = c.post(f"{API}/rooms/{kitchen}/designs/{v}/boq", json={}, headers=H).json()
    check("BOQ groups the kitchen units with quantities", any(i["description"].startswith("Kitchen Wall Cabinet") and int(i["qty"]) >= 2 for i in b["items"]) and any("Sink" in i["description"] for i in b["items"]), str([(i["description"], i["qty"]) for i in b["items"]]))

    # bathroom: not covered until a type is chosen
    page.goto(f"{WEB}/design/ai"); page.wait_for_selector(f"select option:has-text('{PN} ·')", state="attached"); sels = page.locator("main select")
    pick_room("Bath")
    check("bathroom: explained, Generate disabled", page.locator("text=automatic layouts don't cover it").count() == 1 and page.get_by_role("button", name="Generate").is_disabled())
    page.get_by_label("Layout type").select_option("STUDY"); gen(); page.get_by_test_id("layout-notes").wait_for()
    check("bathroom laid out as a study once chosen", "Study" in placed())

    # out of stock → reported, not invented
    for tv in tvs: c.post(f"{API}/catalogue/items/{tv['id']}/stock", json={"delta": -tv["stock"], "reason": "e2e: all sold"}, headers=H).raise_for_status()
    pick_room("Living"); gen(); page.get_by_test_id("layout-missing").wait_for()
    check("out-of-stock TV unit reported, none placed", "TV unit" in page.get_by_test_id("layout-missing").inner_text() and "TV Unit" not in placed())
    page.get_by_label("Use only items in stock").uncheck(); gen(); page.wait_for_function("() => [...document.querySelectorAll('[data-placed]')].some(e => e.dataset.placed === 'TV Unit')")
    check("unticking 'in stock only' places it", page.get_by_test_id("layout-missing").count() == 0)
    for tv in tvs: c.post(f"{API}/catalogue/items/{tv['id']}/stock", json={"delta": tv["stock"], "reason": "e2e: restock"}, headers=H).raise_for_status()
    check("no browser errors or failed requests", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
