"""Real-browser test of M28 catalogue photos: add a photo in the item drawer, it shows in the drawer and as a thumbnail in the list, a
non-image is refused with a message, the quotation PDF carries the picture, Remove clears it."""
import io, os, sys, tempfile, time
import httpx
import pypdfium2 as pdfium
from PIL import Image
from playwright.sync_api import sync_playwright

API, WEB = os.environ.get("IQ_API", "http://localhost:8000/api"), os.environ.get("IQ_WEB", "http://localhost:3000")
SHOTS = os.environ.get("SHOTS", os.path.join(tempfile.gettempdir(), "iq_shots")); os.makedirs(SHOTS, exist_ok=True)
RUN = str(int(time.time()))[-6:]
c = httpx.Client(timeout=60)
H = {"Authorization": "Bearer " + c.post(f"{API}/auth/login", json={"email": "admin@interioriq.com", "password": "ChangeMe123!"}).json()["access_token"]}
SKU = "WAR-SLD-WLT-001"
item = next(i for i in c.get(f"{API}/catalogue/items?kind=FURNITURE", headers=H).json() if i["sku"] == SKU)
c.delete(f"{API}/catalogue/items/{item['id']}/photo", headers=H)
tmp = tempfile.mkdtemp(); good, bad = os.path.join(tmp, "wardrobe.jpg"), os.path.join(tmp, "notes.png")
Image.new("RGB", (1400, 1000), (150, 100, 60)).save(good, "JPEG"); open(bad, "wb").write(b"this is not a picture")

fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

with sync_playwright() as p:
    br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 1000}); problems = []
    page.set_default_timeout(60000); page.set_default_navigation_timeout(90000)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("console", lambda m: problems.append(f"console.error: {m.text[:150]}") if m.type == "error" and "415" not in m.text and "404" not in m.text else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and r.status not in (415,) else None)
    page.goto(f"{WEB}/login"); page.fill("#email", "admin@interioriq.com"); page.fill("#password", "ChangeMe123!"); page.click("button:has-text('Sign in')"); page.wait_for_url("**/dashboard")

    page.goto(f"{WEB}/catalogue/furniture"); row = page.locator(f"tr[data-sku='{SKU}']"); row.wait_for()
    check("no thumbnail before a photo is added", row.locator("img").count() == 0)
    row.click(); ph = page.get_by_test_id("item-photo"); ph.wait_for()
    check("drawer says 'No photo'", "No photo" in ph.inner_text())
    ph.get_by_label("Item photo file").set_input_files(bad); ph.get_by_role("alert").wait_for()
    check("a non-image is refused with a message", "not a readable" in ph.get_by_role("alert").inner_text(), ph.get_by_role("alert").inner_text())
    ph.get_by_label("Item photo file").set_input_files(good); ph.locator("img").wait_for()
    check("photo shows in the drawer", ph.locator("img").evaluate("i => i.naturalWidth") == 1200)
    check("button now offers Replace / Remove", ph.get_by_role("button", name="Replace photo").count() == 1 and ph.get_by_role("button", name="Remove").count() == 1)
    page.keyboard.press("Escape"); row.locator("img").wait_for()
    check("thumbnail shows in the list", row.locator("img").evaluate("i => i.naturalWidth") == 240)
    page.screenshot(path=f"{SHOTS}/catalogue_photo.png", full_page=True)

    # the quotation PDF carries it
    cl = c.post(f"{API}/clients", json={"name": f"Photo Pooja {RUN}", "phone": f"92{RUN}55"[:10]}, headers=H).json()
    pid = c.post(f"{API}/projects", json={"project_number": f"IQ-PHO-{RUN}", "name": "Photo flat", "client_id": cl["id"]}, headers=H).json()["id"]
    rid = c.post(f"{API}/projects/{pid}/rooms", json={"name": "Bedroom", "room_type": "BEDROOM"}, headers=H).json()["id"]
    for l, v in (("Length", 4250), ("Width", 3600)): c.put(f"{API}/rooms/{rid}/measurements", json={"label": l, "value": v, "source": "USER_VERIFIED"}, headers=H)
    ver = c.post(f"{API}/rooms/{rid}/designs", json={"objects": [dict(id="w", name=item["name"], category=item["category"], sku=SKU, price=185000, x=50, y=50, length=2700, width=600, height=2200)]}, headers=H).json()["version"]
    b = c.post(f"{API}/rooms/{rid}/designs/{ver}/boq", json={"gst_enabled": False}, headers=H).json()
    d = pdfium.PdfDocument(c.get(f"{API}/boqs/{b['id']}/quotation.pdf", headers=H).content)
    check("quotation PDF has the item photo", sum(1 for o in d[0].get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE) == 1)

    row.click(); ph = page.get_by_test_id("item-photo"); ph.wait_for(); ph.get_by_role("button", name="Remove").click(); ph.get_by_text("No photo").wait_for()
    page.keyboard.press("Escape"); page.wait_for_timeout(800)
    check("Remove clears the drawer and the list thumbnail", row.locator("img").count() == 0)
    check("no page errors", not problems, "; ".join(problems[:5]))
    br.close()

print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
